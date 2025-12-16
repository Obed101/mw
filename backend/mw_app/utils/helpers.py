from functools import wraps
from flask import jsonify
from flask_jwt_extended import get_jwt_identity
from ..models import User, USER_ROLE_ADMIN, USER_ROLE_SELLER

def admin_required(f):
    """Decorator to ensure the user is an admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user or not user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
            
        return f(*args, **kwargs)
    return decorated_function

def seller_required(f):
    """Decorator to ensure the user is a seller"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user or not user.is_seller:
            return jsonify({"error": "Seller access required"}), 403
            
        return f(*args, **kwargs)
    return decorated_function
