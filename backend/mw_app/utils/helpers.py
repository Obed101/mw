from functools import wraps
from flask import jsonify, session, redirect, url_for, flash, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request
from flask_login import current_user
from ..models import User, Shop, USER_ROLE_ADMIN, USER_ROLE_SELLER

def admin_required(f):
    """Decorator to ensure the user is an admin (JWT based)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user or not user.is_admin:
            return jsonify({"error": "Admin access required"}), 403
            
        return f(*args, **kwargs)
    return decorated_function

def seller_required(f):
    """Decorator to ensure the user is a seller (JWT based)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        verify_jwt_in_request()
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user or user.role != 'seller':
            return jsonify({"error": "Seller access required"}), 403
            
        return f(*args, **kwargs)
    return decorated_function

def shop_owner_required(f):
    """
    Decorator to ensure the user is logged in (session based) 
    and owns at least one shop, or is an admin.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('main_bp.login', next=request.url))
        
        # Check if they own any shops or are admin
        if current_user.role != USER_ROLE_ADMIN and not current_user.owned_shops:
            flash("You do not have any shops to manage.", "warning")
            return redirect(url_for('main_bp.index'))
            
        return f(*args, **kwargs)
    return decorated_function

def get_managed_shop(user, shop_id=None):
    """
    Resolve which shop the user is currently managing.
    Priority:
    1. shop_id parameter
    2. session['managed_shop_id']
    3. first owned shop
    
    Returns (shop_object, error_message or None)
    """
    if not user.is_authenticated:
        return None, "Authentication required"

    # If user is admin, they can manage any shop if shop_id is provided
    if user.role == USER_ROLE_ADMIN and shop_id:
        shop = Shop.query.get(shop_id)
        if shop:
            return shop, None
        return None, "Shop not found"

    # Resolve from parameters/session
    target_id = shop_id or session.get('managed_shop_id')
    
    if target_id:
        shop = Shop.query.get(target_id)
        if shop:
            # Verify ownership (or admin)
            if shop.owner_id == user.id or user.role == USER_ROLE_ADMIN:
                return shop, None
            return None, "Unauthorized access to this shop"
    
    # Fallback to first owned shop
    if user.owned_shops:
        shop = user.owned_shops[0]
        session['managed_shop_id'] = shop.id
        return shop, None
        
    # Admins managing their own "zero" shops case
    if user.role == USER_ROLE_ADMIN:
        # Just grab the first shop in the DB if none selected? 
        # Or let them pick one. For now, first available.
        shop = Shop.query.first()
        if shop:
            session['managed_shop_id'] = shop.id
            return shop, None

    return None, "No shop found to manage"
