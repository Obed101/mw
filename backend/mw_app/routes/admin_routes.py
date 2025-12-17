from flask import Blueprint, jsonify, request
from ..extensions import db
from ..models import Category, Shop, User, Subscription, \
    VERIFICATION_STATUS_VERIFIED, VERIFICATION_STATUS_PENDING, VERIFICATION_STATUS_UNDER_REVIEW, \
    VERIFICATION_STATUS_REJECTED, VERIFICATION_STATUS_SUSPENDED, \
    SUBSCRIPTION_TYPE_USER, SUBSCRIPTION_TYPE_PRODUCT, SUBSCRIPTION_TYPE_SHOP, \
    CATEGORY_LEVEL_TRUNK, CATEGORY_LEVEL_BRANCH, CATEGORY_LEVEL_LEAF
from datetime import datetime

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')

@admin_bp.route("/")
def admin_dashboard():
    """Admin dashboard with marketplace overview"""
    return jsonify({"message": "Admin dashboard"})

# User Management
@admin_bp.route("/users")
def manage_users():
    """Get all users (buyers and sellers)"""
    # Query params: role (buyer/seller), search, status, shops_owned
    return jsonify({"message": "Manage users"})

@admin_bp.route("/users/<int:user_id>")
def get_user(user_id):
    """Get specific user details"""
    return jsonify({"message": f"Get user {user_id}"})

@admin_bp.route("/users/<int:user_id>", methods=["PUT"])
def update_user(user_id):
    """Update user information"""
    return jsonify({"message": f"Update user {user_id}"})

@admin_bp.route("/users/<int:user_id>", methods=["DELETE"])
def delete_user(user_id):
    """Deactivate or delete a user"""
    return jsonify({"message": f"Delete user {user_id}"})

# Category Management
@admin_bp.route("/categories/trunks", methods=["GET"])
def get_trunk_categories():
    """Get all trunk categories"""
    from ..models import Category
    trunks = Category.get_trunk_categories()
    return jsonify([trunk.to_dict(include_children=True) for trunk in trunks])

@admin_bp.route("/categories/branches/<int:trunk_id>", methods=["GET"])
def get_branches(trunk_id):
    """Get all branches under a trunk"""
    from ..models import Category
    branches = Category.get_branches_for_trunk(trunk_id)
    return jsonify([branch.to_dict(include_children=True) for branch in branches])

@admin_bp.route("/categories/leaves/<int:branch_id>", methods=["GET"])
def get_leaves(branch_id):
    """Get all leaves under a branch"""
    from ..models import Category
    leaves = Category.get_leaves_for_branch(branch_id)
    return jsonify([leaf.to_dict() for leaf in leaves])

@admin_bp.route("/categories", methods=["POST"])
def create_category():
    """Create a new category (admin only)"""
    from ..utils.helpers import admin_required
    from flask_jwt_extended import jwt_required, get_jwt_identity
    
    data = request.get_json()
    
    # Validate required fields
    required = ['name', 'level']
    if not all(field in data for field in required):
        return jsonify({"error": "Missing required fields"}), 400
    
    # Validate category level
    try:
        category_level = int(data['level'])
        if category_level not in VALID_CATEGORY_LEVELS:
            return jsonify({"error": "Invalid category level"}), 400
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid category level format"}), 400
    
    # Validate parent_id based on level
    parent_id = data.get('parent_id')
    if category_level == CATEGORY_LEVEL_TRUNK and parent_id is not None:
        return jsonify({"error": "Trunk categories cannot have a parent"}), 400
    elif category_level == CATEGORY_LEVEL_BRANCH and not parent_id:
        return jsonify({"error": "Branch categories require a trunk parent"}), 400
    elif category_level == CATEGORY_LEVEL_LEAF and not parent_id:
        return jsonify({"error": "Leaf categories require a branch parent"}), 400
    
    # Check if parent exists and is of correct level
    if parent_id:
        parent = Category.query.get(parent_id)
        if not parent:
            return jsonify({"error": "Parent category not found"}), 404
        
        if (category_level == CATEGORY_LEVEL_BRANCH and parent.level != CATEGORY_LEVEL_TRUNK) or \
           (category_level == CATEGORY_LEVEL_LEAF and parent.level != CATEGORY_LEVEL_BRANCH):
            level_names = {0: 'trunk', 1: 'branch', 2: 'leaf'}
            return jsonify({"error": f"Invalid parent category level for {level_names[category_level]}"}), 400
    
    # Create category
    try:
        category = Category(
            name=data['name'],
            level=category_level,
            parent_id=parent_id,
            description=data.get('description'),
            is_active=data.get('is_active', True)
        )
        db.session.add(category)
        db.session.commit()
        return jsonify(category.to_dict()), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/categories/<int:category_id>")
def get_category(category_id):
    """Get a specific category by ID"""
    category = Category.query.get_or_404(category_id)
    return jsonify(category.to_dict())

@admin_bp.route("/categories/<int:category_id>", methods=["PUT"])
def update_category(category_id):
    """Update a category (admin only)"""
    from ..utils.helpers import admin_required
    from flask_jwt_extended import jwt_required, get_jwt_identity
    
    category = Category.query.get_or_404(category_id)
    data = request.get_json()
    
    # Prevent changing level of category with children
    if 'level' in data:
        try:
            new_level = int(data['level'])
            if new_level not in VALID_CATEGORY_LEVELS:
                return jsonify({"error": "Invalid category level"}), 400
            if new_level != category.level and category.children:
                return jsonify({"error": "Cannot change level of category with children"}), 400
            category.level = new_level
        except (ValueError, TypeError):
            return jsonify({"error": "Invalid category level format"}), 400
    
    # Update fields
    if 'name' in data:
        category.name = data['name']
    if 'description' in data:
        category.description = data['description']
    if 'is_active' in data:
        category.is_active = data['is_active']
    
    try:
        db.session.commit()
        return jsonify(category.to_dict())
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@admin_bp.route("/categories/<int:category_id>", methods=["DELETE"])
def delete_category(category_id):
    """Delete a category (admin only)"""
    from ..models import db, Category
    from ..utils.helpers import admin_required
    from flask_jwt_required import jwt_required, get_jwt_identity
    
    category = Category.query.get_or_404(category_id)
    
    # Prevent deleting categories with children or products
    if category.children:
        return jsonify({"error": "Cannot delete category with subcategories"}), 400
    if category.products:
        return jsonify({"error": "Cannot delete category with products"}), 400
    
    try:
        db.session.delete(category)
        db.session.commit()
        return jsonify({"message": "Category deleted successfully"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

# Shop Management
@admin_bp.route("/shops")
def manage_shops():
    """Get all shops in the marketplace with filtering"""
    try:
        # Get query parameters
        search = request.args.get('search', '').strip()
        verification_status = request.args.get('verification_status')
        is_active = request.args.get('is_active')
        sort_by = request.args.get('sort_by', 'created_at')  # created_at, name, verification_status
        
        # Build query
        query = Shop.query
        
        # Filter by search term
        if search:
            query = query.filter(
                db.or_(
                    Shop.name.ilike(f'%{search}%'),
                    Shop.description.ilike(f'%{search}%'),
                    Shop.address.ilike(f'%{search}%')
                )
            )
        
        # Filter by verification status
        if verification_status:
            try:
                status_enum = VerificationStatus(verification_status)
                query = query.filter(Shop.verification_status == status_enum)
            except ValueError:
                pass  # Invalid status, ignore
        
        # Filter by active status
        if is_active is not None:
            is_active_bool = is_active.lower() in ('true', '1', 'yes')
            query = query.filter(Shop.is_active == is_active_bool)
        
        # Sort
        if sort_by == 'name':
            query = query.order_by(Shop.name)
        elif sort_by == 'verification_status':
            query = query.order_by(Shop.verification_status, Shop.name)
        else:
            query = query.order_by(Shop.created_at.desc())
        
        shops = query.all()
        
        # Build response
        shops_list = []
        for shop in shops:
            shop_dict = {
                'id': shop.id,
                'name': shop.name,
                'description': shop.description,
                'address': shop.address,
                'region': shop.region,
                'district': shop.district,
                'town': shop.town,
                'phone': shop.phone,
                'email': shop.email,
                'is_active': shop.is_active,
                'verification_status': shop.verification_status if shop.verification_status else None,
                'phone_verified': shop.phone_verified,
                'email_verified': shop.email_verified,
                'verification_requested_at': shop.verification_requested_at.isoformat() if shop.verification_requested_at else None,
                'verified_at': shop.verified_at.isoformat() if shop.verified_at else None,
                'rejection_reason': shop.rejection_reason,
                'owner_id': shop.owner_id,
                'created_at': shop.created_at.isoformat() if shop.created_at else None
            }
            shops_list.append(shop_dict)
        
        return jsonify({
            'success': True,
            'count': len(shops_list),
            'shops': shops_list
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching shops',
            'error': str(e)
        }), 500

@admin_bp.route("/shops/pending-verification")
def get_pending_verification():
    """Get shops pending verification review"""
    try:
        # Get query parameters
        status = request.args.get('status', 'pending')  # pending or under_review
        
        if status == 'under_review':
            status_enum = VERIFICATION_STATUS_UNDER_REVIEW
        else:
            status_enum = VERIFICATION_STATUS_PENDING
        
        shops = Shop.query.filter_by(verification_status=status_enum).order_by(
            Shop.verification_requested_at.desc()
        ).all()
        
        shops_list = []
        for shop in shops:
            shop_dict = {
                'id': shop.id,
                'name': shop.name,
                'description': shop.description,
                'address': shop.address,
                'region': shop.region,
                'district': shop.district,
                'town': shop.town,
                'phone': shop.phone,
                'email': shop.email,
                'phone_verified': shop.phone_verified,
                'email_verified': shop.email_verified,
                'verification_requested_at': shop.verification_requested_at.isoformat() if shop.verification_requested_at else None,
                'verification_notes': shop.verification_notes,
                'owner_id': shop.owner_id
            }
            shops_list.append(shop_dict)
        
        return jsonify({
            'success': True,
            'count': len(shops_list),
            'shops': shops_list
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching pending verification shops',
            'error': str(e)
        }), 500

@admin_bp.route("/shops/<int:shop_id>")
def get_shop(shop_id):
    """Get specific shop details"""
    return jsonify({"message": f"Get shop {shop_id}"})

@admin_bp.route("/shops/<int:shop_id>", methods=["PUT"])
def update_shop(shop_id):
    """Update shop information"""
    return jsonify({"message": f"Update shop {shop_id}"})

@admin_bp.route("/shops/<int:shop_id>/verify", methods=["POST"])
def verify_shop(shop_id):
    """Approve shop verification"""
    try:
        # Get admin user_id from request
        admin_id = request.args.get('admin_id', type=int)
        data = request.get_json() or {}
        admin_id = data.get('admin_id') or admin_id
        
        if not admin_id:
            return jsonify({
                'success': False,
                'message': 'Admin ID is required'
            }), 400
        
        # Verify admin
        admin = User.query.get(admin_id)
        if not admin or admin.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Admin not found or unauthorized'
            }), 403
        
        # Get shop
        shop = Shop.query.get(shop_id)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found'
            }), 404
        
        # Verify shop
        shop.verification_status = VERIFICATION_STATUS_VERIFIED
        shop.verified_at = datetime.now(datetime.timezone.utc)
        shop.verified_by = admin_id
        shop.rejection_reason = None  # Clear rejection reason if any
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Shop "{shop.name}" has been verified',
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'verification_status': shop.verification_status,
                'verified_at': shop.verified_at.isoformat(),
                'verified_by': admin_id
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error verifying shop',
            'error': str(e)
        }), 500

@admin_bp.route("/shops/<int:shop_id>/reject", methods=["POST"])
def reject_shop(shop_id):
    """Reject shop verification"""
    try:
        # Get admin user_id from request
        admin_id = request.args.get('admin_id', type=int)
        data = request.get_json() or {}
        admin_id = data.get('admin_id') or admin_id
        rejection_reason = data.get('rejection_reason', '').strip()
        
        if not admin_id:
            return jsonify({
                'success': False,
                'message': 'Admin ID is required'
            }), 400
        
        if not rejection_reason:
            return jsonify({
                'success': False,
                'message': 'Rejection reason is required'
            }), 400
        
        # Verify admin
        admin = User.query.get(admin_id)
        if not admin or admin.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Admin not found or unauthorized'
            }), 403
        
        # Get shop
        shop = Shop.query.get(shop_id)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found'
            }), 404
        
        # Reject shop
        shop.verification_status = VERIFICATION_STATUS_REJECTED
        shop.rejection_reason = rejection_reason
        shop.verified_by = None
        shop.verified_at = None
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Shop "{shop.name}" verification has been rejected',
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'verification_status': shop.verification_status,
                'rejection_reason': shop.rejection_reason
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error rejecting shop',
            'error': str(e)
        }), 500

@admin_bp.route("/shops/<int:shop_id>/suspend", methods=["POST"])
def suspend_shop(shop_id):
    """Suspend a verified shop"""
    try:
        # Get admin user_id from request
        admin_id = request.args.get('admin_id', type=int)
        data = request.get_json() or {}
        admin_id = data.get('admin_id') or admin_id
        
        if not admin_id:
            return jsonify({
                'success': False,
                'message': 'Admin ID is required'
            }), 400
        
        # Verify admin
        admin = User.query.get(admin_id)
        if not admin or admin.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Admin not found or unauthorized'
            }), 403
        
        # Get shop
        shop = Shop.query.get(shop_id)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found'
            }), 404
        
        # Suspend shop
        shop.verification_status = VERIFICATION_STATUS_SUSPENDED
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Shop "{shop.name}" has been suspended',
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'verification_status': shop.verification_status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error suspending shop',
            'error': str(e)
        }), 500

@admin_bp.route("/shops/<int:shop_id>/under-review", methods=["POST"])
def put_shop_under_review(shop_id):
    """Put shop verification under review"""
    try:
        # Get admin user_id from request
        admin_id = request.args.get('admin_id', type=int)
        data = request.get_json() or {}
        admin_id = data.get('admin_id') or admin_id
        
        if not admin_id:
            return jsonify({
                'success': False,
                'message': 'Admin ID is required'
            }), 400
        
        # Verify admin
        admin = User.query.get(admin_id)
        if not admin or admin.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Admin not found or unauthorized'
            }), 403
        
        # Get shop
        shop = Shop.query.get(shop_id)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found'
            }), 404
        
        # Put under review
        shop.verification_status = VERIFICATION_STATUS_UNDER_REVIEW
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Shop "{shop.name}" is now under review',
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'verification_status': shop.verification_status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating shop status',
            'error': str(e)
        }), 500

@admin_bp.route("/shops/<int:shop_id>/verification-notes", methods=["PUT"])
def update_verification_notes(shop_id):
    """Update verification notes for a shop"""
    try:
        # Get admin user_id from request
        admin_id = request.args.get('admin_id', type=int)
        data = request.get_json() or {}
        admin_id = data.get('admin_id') or admin_id
        notes = data.get('notes', '').strip()
        
        if not admin_id:
            return jsonify({
                'success': False,
                'message': 'Admin ID is required'
            }), 400
        
        # Verify admin
        admin = User.query.get(admin_id)
        if not admin or admin.role != 'admin':
            return jsonify({
                'success': False,
                'message': 'Admin not found or unauthorized'
            }), 403
        
        # Get shop
        shop = Shop.query.get(shop_id)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found'
            }), 404
        
        # Update notes
        shop.verification_notes = notes or None
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Verification notes updated',
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'verification_notes': shop.verification_notes
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating verification notes',
            'error': str(e)
        }), 500

@admin_bp.route("/shops/<int:shop_id>", methods=["DELETE"])
def delete_shop(shop_id):
    """Deactivate or delete a shop"""
    return jsonify({"message": f"Delete shop {shop_id}"})

@admin_bp.route("/shops/<int:shop_id>/products")
def shop_products(shop_id):
    """View all products in a shop"""
    return jsonify({"message": f"Products in shop {shop_id}"})

# Product Management
@admin_bp.route("/products")
def manage_products():
    """Get all products across all shops"""
    # Query params: search, shop_id, min_price, max_price, in_stock
    return jsonify({"message": "Manage products"})

@admin_bp.route("/products/<int:product_id>")
def get_product(product_id):
    """Get specific product details"""
    return jsonify({"message": f"Get product {product_id}"})

@admin_bp.route("/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    """Update product information"""
    return jsonify({"message": f"Update product {product_id}"})

@admin_bp.route("/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    """Delete a product"""
    return jsonify({"message": f"Delete product {product_id}"})

# Category Management
@admin_bp.route("/categories")
def manage_categories():
    """Get all product categories with optional filtering"""
    try:
        # Get query parameters
        search = request.args.get('search', '').strip()
        is_active = request.args.get('is_active')
        
        # Build query
        query = Category.query
        
        # Filter by search term (name or description)
        if search:
            query = query.filter(
                db.or_(
                    Category.name.ilike(f'%{search}%'),
                    Category.description.ilike(f'%{search}%')
                )
            )
        
        # Filter by active status
        if is_active is not None:
            is_active_bool = is_active.lower() in ('true', '1', 'yes')
            query = query.filter(Category.is_active == is_active_bool)
        
        # Order by name
        categories = query.order_by(Category.name).all()
        
        return jsonify({
            'success': True,
            'count': len(categories),
            'categories': [category.to_dict() for category in categories]
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching categories',
            'error': str(e)
        }), 500

# Marketplace Analytics
@admin_bp.route("/analytics")
def marketplace_analytics():
    """View marketplace-wide analytics"""
    return jsonify({"message": "Marketplace analytics"})

@admin_bp.route("/analytics/products")
def product_analytics():
    """View product statistics across marketplace"""
    return jsonify({"message": "Product analytics"})

@admin_bp.route("/analytics/shops")
def shop_analytics():
    """View shop statistics"""
    return jsonify({"message": "Shop analytics"})

# Bulk Operations
@admin_bp.route("/bulk/categories", methods=["POST"])
def bulk_update_categories():
    """Bulk update categories (activate/deactivate, move, etc.)"""
    try:
        data = request.get_json()
        operation = data.get("operation")  # "activate", "deactivate", "move", "delete"
        category_ids = data.get("category_ids", [])
        
        if not operation or not category_ids:
            return jsonify({
                'success': False,
                'message': 'operation and category_ids are required'
            }), 400
        
        if operation not in ["activate", "deactivate", "move", "delete"]:
            return jsonify({
                'success': False,
                'message': 'Invalid operation. Must be activate, deactivate, move, or delete'
            }), 400
        
        results = []
        errors = []
        
        for category_id in category_ids:
            try:
                category = Category.query.get(category_id)
                if not category:
                    errors.append({'category_id': category_id, 'error': 'Category not found'})
                    continue
                
                if operation == "activate":
                    category.is_active = True
                    results.append({'category_id': category_id, 'action': 'activated'})
                
                elif operation == "deactivate":
                    # Check if category has products
                    if category.products:
                        errors.append({'category_id': category_id, 'error': 'Cannot deactivate category with products'})
                        continue
                    category.is_active = False
                    results.append({'category_id': category_id, 'action': 'deactivated'})
                
                elif operation == "delete":
                    # Check if category has children or products
                    if category.children:
                        errors.append({'category_id': category_id, 'error': 'Cannot delete category with subcategories'})
                        continue
                    if category.products:
                        errors.append({'category_id': category_id, 'error': 'Cannot delete category with products'})
                        continue
                    db.session.delete(category)
                    results.append({'category_id': category_id, 'action': 'deleted'})
                
                elif operation == "move":
                    new_parent_id = data.get("new_parent_id")
                    if not new_parent_id:
                        errors.append({'category_id': category_id, 'error': 'new_parent_id required for move operation'})
                        continue
                    
                    new_parent = Category.query.get(new_parent_id)
                    if not new_parent:
                        errors.append({'category_id': category_id, 'error': 'New parent category not found'})
                        continue
                    
                    # Validate parent-child relationship
                    if category.level == CATEGORY_LEVEL_TRUNK:
                        errors.append({'category_id': category_id, 'error': 'Cannot move trunk categories'})
                        continue
                    
                    if (category.level == CATEGORY_LEVEL_BRANCH and new_parent.level != CATEGORY_LEVEL_TRUNK) or \
                       (category.level == CATEGORY_LEVEL_LEAF and new_parent.level != CATEGORY_LEVEL_BRANCH):
                        errors.append({'category_id': category_id, 'error': 'Invalid parent category level'})
                        continue
                    
                    category.parent_id = new_parent_id
                    results.append({'category_id': category_id, 'action': 'moved', 'new_parent_id': new_parent_id})
                
            except Exception as e:
                errors.append({'category_id': category_id, 'error': str(e)})
                continue
        
        if results:
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Bulk {operation} completed',
            'processed': len(results),
            'errors': len(errors),
            'results': results,
            'errors': errors
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error performing bulk operation',
            'error': str(e)
        }), 500

@admin_bp.route("/bulk/shops/verify", methods=["POST"])
def bulk_verify_shops():
    """Bulk verify shops (approve, reject, under_review)"""
    try:
        data = request.get_json()
        action = data.get("action")  # "verify", "reject", "under_review"
        shop_ids = data.get("shop_ids", [])
        rejection_reason = data.get("rejection_reason", "")
        admin_id = data.get("admin_id")
        
        if not action or not shop_ids:
            return jsonify({
                'success': False,
                'message': 'action and shop_ids are required'
            }), 400
        
        if action not in ["verify", "reject", "under_review"]:
            return jsonify({
                'success': False,
                'message': 'Invalid action. Must be verify, reject, or under_review'
            }), 400
        
        if action == "reject" and not rejection_reason:
            return jsonify({
                'success': False,
                'message': 'rejection_reason is required for reject action'
            }), 400
        
        results = []
        errors = []
        
        for shop_id in shop_ids:
            try:
                shop = Shop.query.get(shop_id)
                if not shop:
                    errors.append({'shop_id': shop_id, 'error': 'Shop not found'})
                    continue
                
                if action == "verify":
                    shop.verification_status = VERIFICATION_STATUS_VERIFIED
                    shop.verified_at = datetime.now(datetime.timezone.utc)
                    shop.verified_by = admin_id
                    shop.rejection_reason = None
                    results.append({'shop_id': shop_id, 'action': 'verified'})
                
                elif action == "reject":
                    shop.verification_status = VERIFICATION_STATUS_REJECTED
                    shop.rejection_reason = rejection_reason
                    shop.verified_at = None
                    shop.verified_by = None
                    results.append({'shop_id': shop_id, 'action': 'rejected', 'reason': rejection_reason})
                
                elif action == "under_review":
                    shop.verification_status = VERIFICATION_STATUS_UNDER_REVIEW
                    shop.rejection_reason = None
                    results.append({'shop_id': shop_id, 'action': 'under_review'})
                
            except Exception as e:
                errors.append({'shop_id': shop_id, 'error': str(e)})
                continue
        
        if results:
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Bulk shop {action} completed',
            'processed': len(results),
            'errors': len(errors),
            'results': results,
            'errors': errors
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error performing bulk shop verification',
            'error': str(e)
        }), 500

# Subscription Management
@admin_bp.route("/subscription/toggle", methods=["POST"])
def toggle_subscription():
    """Toggle premium status and manage subscription for user/product/shop"""
    try:
        data = request.get_json()
        target_type = data.get("target_type")  # "user", "product", or "shop"
        target_id = data.get("target_id")
        is_premium = data.get("is_premium", False)
        start_date = data.get("start_date")
        end_date = data.get("end_date")
        
        if not all([target_type, target_id]):
            return jsonify({
                'success': False,
                'message': 'target_type and target_id are required'
            }), 400
        
        # Validate target_type
        if target_type not in ["user", "product", "shop"]:
            return jsonify({
                'success': False,
                'message': 'target_type must be user, product, or shop'
            }), 400
        
        # Map target_type to enum and model
        type_map = {
            "user": (SUBSCRIPTION_TYPE_USER, User),
            "product": (SUBSCRIPTION_TYPE_PRODUCT, Product),
            "shop": (SUBSCRIPTION_TYPE_SHOP, Shop)
        }
        subscription_type, model_class = type_map[target_type]
        
        # Get the target object
        target = model_class.query.get(target_id)
        if not target:
            return jsonify({
                'success': False,
                'message': f'{target_type.title()} not found'
            }), 404
        
        # Update premium flag if model has it
        if hasattr(target, 'premium'):
            target.premium = is_premium
        else:
            # For models without premium flag, we'll rely on subscription existence
            pass
        
        # Handle subscription dates
        if is_premium and start_date and end_date:
            # Parse dates if they're strings
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date.replace('Z', '+23:59'))
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date.replace('Z', '+23:59'))
            
            # Create or update subscription
            subscription = Subscription.create_subscription(
                subscription_type=subscription_type,
                target_id=target_id,
                end_date=end_date,
                created_by=admin_id
            )
            subscription.start_date = start_date
            db.session.commit()
        elif not is_premium:
            # Deactivate any existing subscription
            existing = Subscription.get_active_subscription(subscription_type, target_id)
            if existing:
                existing.deactivate()
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{target_type.title()} premium status updated',
            'target': {
                'id': target.id,
                'type': target_type,
                'is_premium': is_premium,
                'subscription': subscription.to_dict() if is_premium and 'subscription' in locals() else None
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating subscription',
            'error': str(e)
        }), 500

@admin_bp.route("/subscription/<target_type>/<int:target_id>")
def get_subscription(target_type, target_id):
    """Get current subscription for a target"""
    try:
        if target_type not in ["user", "product", "shop"]:
            return jsonify({
                'success': False,
                'message': 'Invalid target_type'
            }), 400
        
        type_map = {
            "user": SUBSCRIPTION_TYPE_USER,
            "product": SUBSCRIPTION_TYPE_PRODUCT,
            "shop": SUBSCRIPTION_TYPE_SHOP
        }
        subscription_type = type_map[target_type]
        
        subscription = Subscription.get_active_subscription(subscription_type, target_id)
        
        return jsonify({
            'success': True,
            'subscription': subscription.to_dict() if subscription else None
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching subscription',
            'error': str(e)
        }), 500

# Report Generation and Data Export
@admin_bp.route("/reports/export", methods=["POST"])
def export_data():
    """Export data in various formats (CSV, JSON, Excel)"""
    try:
        data = request.get_json()
        report_type = data.get("report_type")  # "users", "shops", "products", "categories", "verification"
        export_format = data.get("format", "json")  # "json", "csv", "excel"
        filters = data.get("filters", {})
        
        if not report_type:
            return jsonify({
                'success': False,
                'message': 'report_type is required'
            }), 400
        
        if export_format not in ["json", "csv"]:
            return jsonify({
                'success': False,
                'message': 'format must be json or csv'
            }), 400
        
        # Get data based on report type
        if report_type == "users":
            query = User.query
            if filters.get("role"):
                query = query.filter(User.role == filters["role"])
            if filters.get("status"):
                query = query.filter(User.status == filters["status"])
            if filters.get("premium") is not None:
                query = query.filter(User.premium == filters["premium"])
            records = query.all()
            
        elif report_type == "shops":
            query = Shop.query
            if filters.get("verification_status"):
                query = query.filter(Shop.verification_status == filters["verification_status"])
            if filters.get("is_active") is not None:
                query = query.filter(Shop.is_active == filters["is_active"])
            records = query.all()
            
        elif report_type == "products":
            query = Product.query
            if filters.get("is_active") is not None:
                query = query.filter(Product.is_active == filters["is_active"])
            if filters.get("shop_id"):
                query = query.filter(Product.shop_id == filters["shop_id"])
            if filters.get("category_id"):
                query = query.filter(Product.category_id == filters["category_id"])
            records = query.all()
            
        elif report_type == "categories":
            query = Category.query
            if filters.get("level") is not None:
                query = query.filter(Category.level == filters["level"])
            if filters.get("is_active") is not None:
                query = query.filter(Category.is_active == filters["is_active"])
            records = query.all()
            
        elif report_type == "verification":
            # Verification status report
            query = Shop.query
            if filters.get("status"):
                query = query.filter(Shop.verification_status == filters["status"])
            records = query.all()
            
        else:
            return jsonify({
                'success': False,
                'message': 'Invalid report_type'
            }), 400
        
        # Generate export data
        export_data = []
        for record in records:
            if report_type == "users":
                export_data.append({
                    'id': record.id,
                    'username': record.username,
                    'email': record.email,
                    'role': record.role,
                    'status': record.status,
                    'premium': record.premium,
                    'created_at': record.created_at.isoformat() if record.created_at else None,
                    'last_login': record.last_login.isoformat() if record.last_login else None
                })
            elif report_type == "shops":
                export_data.append({
                    'id': record.id,
                    'name': record.name,
                    'owner_id': record.owner_id,
                    'verification_status': record.verification_status,
                    'phone_verified': record.phone_verified,
                    'email_verified': record.email_verified,
                    'is_active': record.is_active,
                    'created_at': record.created_at.isoformat() if record.created_at else None,
                    'verified_at': record.verified_at.isoformat() if record.verified_at else None
                })
            elif report_type == "products":
                export_data.append({
                    'id': record.id,
                    'name': record.name,
                    'shop_id': record.shop_id,
                    'category_id': record.category_id,
                    'price': record.price,
                    'stock': record.stock,
                    'is_active': record.is_active,
                    'created_at': record.created_at.isoformat() if record.created_at else None
                })
            elif report_type == "categories":
                export_data.append({
                    'id': record.id,
                    'name': record.name,
                    'level': record.level,
                    'parent_id': record.parent_id,
                    'is_active': record.is_active,
                    'created_at': record.created_at.isoformat() if record.created_at else None
                })
            elif report_type == "verification":
                export_data.append({
                    'shop_id': record.id,
                    'shop_name': record.name,
                    'verification_status': record.verification_status,
                    'phone_verified': record.phone_verified,
                    'email_verified': record.email_verified,
                    'verification_requested_at': record.verification_requested_at.isoformat() if record.verification_requested_at else None,
                    'verified_at': record.verified_at.isoformat() if record.verified_at else None,
                    'rejection_reason': record.rejection_reason
                })
        
        # Format response
        if export_format == "json":
            return jsonify({
                'success': True,
                'report_type': report_type,
                'format': export_format,
                'count': len(export_data),
                'generated_at': datetime.now(datetime.timezone.utc).isoformat(),
                'data': export_data
            }), 200
        
        elif export_format == "csv":
            # Simple CSV generation (in production, use csv library)
            if not export_data:
                csv_content = "No data found"
            else:
                headers = list(export_data[0].keys())
                csv_rows = [",".join(headers)]
                for row in export_data:
                    csv_row = ",".join([str(row.get(h, "")) for h in headers])
                    csv_rows.append(csv_row)
                csv_content = "\n".join(csv_rows)
            
            return jsonify({
                'success': True,
                'report_type': report_type,
                'format': export_format,
                'count': len(export_data),
                'generated_at': datetime.now(datetime.timezone.utc).isoformat(),
                'csv_content': csv_content
            }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error generating report',
            'error': str(e)
        }), 500

@admin_bp.route("/reports/compliance")
def compliance_report():
    """Generate compliance reports (verification status, premium subscriptions, etc.)"""
    try:
        # Verification compliance
        total_shops = Shop.query.count()
        verified_shops = Shop.query.filter_by(verification_status=VERIFICATION_STATUS_VERIFIED).count()
        pending_shops = Shop.query.filter_by(verification_status=VERIFICATION_STATUS_PENDING).count()
        under_review_shops = Shop.query.filter_by(verification_status=VERIFICATION_STATUS_UNDER_REVIEW).count()
        rejected_shops = Shop.query.filter_by(verification_status=VERIFICATION_STATUS_REJECTED).count()
        
        # Phone/Email verification compliance
        phone_verified_shops = Shop.query.filter_by(phone_verified=True).count()
        email_verified_shops = Shop.query.filter_by(email_verified=True).count()
        fully_verified_shops = Shop.query.filter(
            Shop.phone_verified == True,
            Shop.email_verified == True
        ).count()
        
        # User compliance
        total_users = User.query.count()
        premium_users = User.query.filter_by(premium=True).count()
        active_users = User.query.filter_by(status='active').count()
        
        # Product compliance
        total_products = Product.query.count()
        active_products = Product.query.filter_by(is_active=True).count()
        out_of_stock_products = Product.query.filter(Product.stock <= 0).count()
        
        # Category structure
        total_categories = Category.query.count()
        active_categories = Category.query.filter_by(is_active=True).count()
        
        return jsonify({
            'success': True,
            'report_type': 'compliance',
            'generated_at': datetime.now(datetime.timezone.utc).isoformat(),
            'verification_compliance': {
                'total_shops': total_shops,
                'verified_shops': verified_shops,
                'pending_shops': pending_shops,
                'under_review_shops': under_review_shops,
                'rejected_shops': rejected_shops,
                'verification_rate': round((verified_shops / total_shops * 100) if total_shops > 0 else 0, 2),
                'phone_verified': phone_verified_shops,
                'email_verified': email_verified_shops,
                'fully_verified': fully_verified_shops
            },
            'user_compliance': {
                'total_users': total_users,
                'premium_users': premium_users,
                'active_users': active_users,
                'premium_rate': round((premium_users / total_users * 100) if total_users > 0 else 0, 2)
            },
            'product_compliance': {
                'total_products': total_products,
                'active_products': active_products,
                'out_of_stock_products': out_of_stock_products,
                'active_rate': round((active_products / total_products * 100) if total_products > 0 else 0, 2)
            },
            'category_compliance': {
                'total_categories': total_categories,
                'active_categories': active_categories,
                'active_rate': round((active_categories / total_categories * 100) if total_categories > 0 else 0, 2)
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error generating compliance report',
            'error': str(e)
        }), 500

