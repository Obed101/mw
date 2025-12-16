from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, create_refresh_token, 
    jwt_required, get_jwt_identity, get_jwt,
    verify_jwt_in_request, get_jti
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone, timedelta
from ..extensions import db, jwt, token_blacklist
from ..models import User, USER_STATUS_ACTIVE, USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER, AuthToken, TOKEN_TYPE_API

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user"""
    data = request.get_json()
    
    # Validate required fields
    required = ['username', 'email', 'password', 'role']
    if not all(field in data for field in required):
        return jsonify({"error": "Missing required fields"}), 400
    
    # Validate role
    valid_roles = [USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER]
    if data['role'] not in valid_roles:
        return jsonify({"error": "Invalid role"}), 400
    
    # Check if user already exists
    if User.query.filter_by(email=data['email']).first():
        return jsonify({"error": "Email already registered"}), 400
    
    if User.query.filter_by(username=data['username']).first():
        return jsonify({"error": "Username already taken"}), 400
    
    # Create new user
    try:
        user = User(
            username=data['username'],
            email=data['email'],
            role=data['role'],
            status=USER_STATUS_ACTIVE
        )
        user.set_password(data['password'])
        
        # Add optional fields
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        if 'phone' in data:
            user.phone = data['phone']
        if 'region' in data:
            user.region = data['region']
        if 'district' in data:
            user.district = data['district']
        if 'town' in data:
            user.town = data['town']
        
        db.session.add(user)
        db.session.commit()
        
        # Generate tokens
        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)
        
        return jsonify({
            "message": "User registered successfully",
            "user": user.to_dict(),
            "access_token": access_token,
            "refresh_token": refresh_token
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@auth_bp.route('/login', methods=['POST'])
def login():
    """User login"""
    data = request.get_json()
    
    # Validate required fields
    if not data or not data.get('email') or not data.get('password'):
        return jsonify({"error": "Email and password are required"}), 400
    
    # Find user
    user = User.query.filter_by(email=data['email']).first()
    if not user or not user.check_password(data['password']):
        return jsonify({"error": "Invalid email or password"}), 401
    
    # Check if user is active
    if not user.is_active():
        return jsonify({"error": "Account is not active"}), 401
    
    # Update last login
    user.update_last_login()
    
    # Generate tokens
    access_token = create_access_token(identity=user.id)
    refresh_token = create_refresh_token(identity=user.id)
    
    return jsonify({
        "message": "Login successful",
        "user": user.to_dict(),
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "Bearer"
    }), 200

@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token"""
    current_user_id = get_jwt_identity()
    access_token = create_access_token(identity=current_user_id)
    return jsonify({"access_token": access_token}), 200

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """Logout user and revoke token"""
    jti = get_jwt()['jti']
    current_user_id = get_jwt_identity()
    
    # Add token to blacklist
    token_blacklist.add(jti)
    
    # Also mark as used in database if record exists
    try:
        auth_token = AuthToken.query.filter_by(token=jti).first()
        if auth_token:
            auth_token.mark_as_used()
        
        return jsonify({"message": "Successfully logged out"}), 200
    except Exception as e:
        return jsonify({"error": "Error during logout"}), 500

@auth_bp.route('/revoke', methods=['POST'])
@jwt_required()
def revoke_token():
    """Revoke a specific token"""
    data = request.get_json()
    if not data or not data.get('token'):
        return jsonify({"error": "Token is required"}), 400
    
    try:
        # Add to blacklist
        token_blacklist.add(data['token'])
        
        # Also mark as used in database
        auth_token = AuthToken.query.filter_by(token=data['token']).first()
        if auth_token and auth_token.user_id == get_jwt_identity():
            auth_token.mark_as_used()
            return jsonify({"message": "Token revoked successfully"}), 200
        else:
            return jsonify({"error": "Invalid token"}), 404
    except Exception as e:
        return jsonify({"error": "Error revoking token"}), 500

@auth_bp.route('/tokens', methods=['GET'])
@jwt_required()
def list_active_tokens():
    """List all active tokens for the current user"""
    current_user_id = get_jwt_identity()
    
    try:
        tokens = AuthToken.query.filter_by(
            user_id=current_user_id,
            is_used=False
        ).filter(
            AuthToken.expires_at > datetime.now(timezone.utc)
        ).all()
        
        return jsonify({
            "tokens": [
                {
                    "id": token.id,
                    "token_type": token.token_type,
                    "created_at": token.created_at.isoformat(),
                    "expires_at": token.expires_at.isoformat()
                }
                for token in tokens
            ]
        }), 200
    except Exception as e:
        return jsonify({"error": "Error fetching tokens"}), 500

@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """Get current user info"""
    current_user_id = get_jwt_identity()
    user = User.query.get(current_user_id)
    return jsonify(user.to_dict()) if user else ({"error": "User not found"}, 404)
