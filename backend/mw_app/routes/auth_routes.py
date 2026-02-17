from flask import request, jsonify, url_for, redirect, flash, Blueprint
from flask_jwt_extended import create_access_token, create_refresh_token, jwt_required, get_jwt_identity, get_jwt
from flask_login import login_user, logout_user, current_user
from datetime import datetime, timezone
from ..extensions import db, token_blacklist
from ..models.user_model import User, USER_STATUS_ACTIVE, USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER, AuthToken

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

@auth_bp.route('/register', methods=['POST'])
def register():
    """Register a new user"""
    # Handle both JSON and form data
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()
    
    # Check if this is OAuth registration (no password required)
    is_oauth = data.get('is_oauth', False)
    
    # Validate required fields
    if is_oauth:
        required = ['username', 'email', 'role']
    else:
        required = ['username', 'email', 'password', 'confirm_password', 'role']
    
    if not all(field in data for field in required):
        error_msg = "Missing required fields"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.register'))
    
    # Validate password confirmation (only for non-OAuth users)
    if not is_oauth:
        if data['password'] != data['confirm_password']:
            error_msg = "Passwords do not match"
            if request.is_json:
                return jsonify({"error": error_msg}), 400
            else:
                flash(error_msg, 'error')
                return redirect(url_for('main_bp.register'))
    
    # Validate terms agreement
    if 'terms' not in data or not data['terms']:
        error_msg = "You must agree to the terms of service"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.register'))
    
    # Validate role
    valid_roles = [USER_ROLE_ADMIN, USER_ROLE_SELLER, USER_ROLE_BUYER]
    if data['role'] not in valid_roles:
        error_msg = "Invalid role"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.register'))
    
    # Check if user already exists
    if User.query.filter_by(email=data['email']).first():
        error_msg = "Email already registered"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.register'))
    
    if User.query.filter_by(username=data['username']).first():
        error_msg = "Username already taken"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.register'))
    
    # Create new user
    try:
        user = User(
            username=data['username'],
            email=data['email'],
            role=data['role'],
            status=USER_STATUS_ACTIVE
        )
        
        # Set password only for non-OAuth users
        if not is_oauth:
            user.set_password(data['password'])
        
        # Add optional fields
        if 'first_name' in data and data['first_name']:
            user.first_name = data['first_name']
        if 'last_name' in data and data['last_name']:
            user.last_name = data['last_name']
        if 'phone' in data and data['phone']:
            user.phone = data['phone']
        if 'region' in data and data['region']:
            user.region = data['region']
        if 'district' in data and data['district']:
            user.district = data['district']
        if 'town' in data and data['town']:
            user.town = data['town']
        
        db.session.add(user)
        db.session.commit()
        
        # Log user in automatically after registration
        user.update_last_login()
        
        # Log user in with Flask-Login for session management
        login_user(user)
        
        # Generate tokens for API usage
        access_token = create_access_token(identity=user.id)
        refresh_token = create_refresh_token(identity=user.id)
        
        # Handle form vs API responses
        if request.is_json:
            return jsonify({
                "message": "User registered successfully",
                "user": user.to_dict(),
                "access_token": access_token,
                "refresh_token": refresh_token
            }), 201
        else:
            # For form submissions, flash message and redirect
            flash('Registration successful! You are now logged in.', 'success')
            return redirect(url_for('main_bp.login'))
        
    except Exception as e:
        db.session.rollback()
        if request.is_json:
            return jsonify({"error": str(e)}), 500
        else:
            flash('An error occurred during registration. Please try again.', 'error')
            return redirect(url_for('main_bp.register'))

@auth_bp.route('/login', methods=['POST'])
def login():
    """User login"""
    # Handle both JSON and form data
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form.to_dict()
    
    # Validate required fields
    if not data or not data.get('username'):
        error_msg = "Username is required"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # Check if this is OAuth login (no password required)
    is_oauth = data.get('is_oauth', False)
    
    if not is_oauth and not data.get('password'):
        error_msg = "Password is required"
        if request.is_json:
            return jsonify({"error": error_msg}), 400
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # Find user (try username first, then email)
    user = User.query.filter_by(username=data['username']).first()
    if not user:
        user = User.query.filter_by(email=data['username']).first()
    
    if not user:
        error_msg = "Invalid username/email"
        if request.is_json:
            return jsonify({"error": error_msg}), 401
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # For OAuth users, no password check needed
    if not is_oauth:
        if not user.password_hash or not user.check_password(data['password']):
            error_msg = "Invalid password"
            if request.is_json:
                return jsonify({"error": error_msg}), 401
            else:
                flash(error_msg, 'error')
                return redirect(url_for('main_bp.login'))
    
    # Check if user is active
    if not user.is_active():
        error_msg = "Account is not active"
        if request.is_json:
            return jsonify({"error": error_msg}), 401
        else:
            flash(error_msg, 'error')
            return redirect(url_for('main_bp.login'))
    
    # Update last login
    user.update_last_login()
    
    # Log user in with Flask-Login for session management
    login_user(user)
    
    # Generate tokens for API usage
    access_token = create_access_token(identity=user.id)
    refresh_token = create_refresh_token(identity=user.id)
    
    # Handle form vs API responses
    if request.is_json:
        return jsonify({
            "message": "Login successful",
            "user": user.to_dict(),
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "Bearer"
        }), 200
    else:
        # For form submissions, flash message and redirect to appropriate dashboard
        flash(f'Welcome back! {user.first_name} {user.last_name}', 'success')
        
        # Redirect based on user role
        if user.role == 'admin':
            return redirect(url_for('admin_template_bp.admin_dashboard'))
        elif user.role == 'seller':
            return redirect(url_for('seller_template_bp.seller_dashboard'))
        else:
            return redirect(url_for('main_bp.index'))

@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """Refresh access token"""
    current_user_id = get_jwt_identity()
    access_token = create_access_token(identity=current_user_id)
    return jsonify({"access_token": access_token}), 200

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """Logout user"""
    # Handle both JSON and form requests
    if request.is_json:
        # For API requests, revoke JWT token
        jti = get_jwt()['jti']
        token_blacklist.add(jti)
        return jsonify({"message": "Successfully logged out"}), 200
    else:
        # For form requests, use Flask-Login logout
        logout_user()
        flash('You have been logged out successfully.', 'success')
        return redirect(url_for('main_bp.index'))

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
