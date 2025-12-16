from flask import Blueprint, jsonify, request
from ..extensions import db
from ..models import Category, Shop, User, VerificationStatus, Subscription, SubscriptionType, \
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
                'verification_status': shop.verification_status.value if shop.verification_status else None,
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
            status_enum = VerificationStatus.UNDER_REVIEW
        else:
            status_enum = VerificationStatus.PENDING
        
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
        shop.verification_status = VerificationStatus.VERIFIED
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
                'verification_status': shop.verification_status.value,
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
        shop.verification_status = VerificationStatus.REJECTED
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
                'verification_status': shop.verification_status.value,
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
        shop.verification_status = VerificationStatus.SUSPENDED
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Shop "{shop.name}" has been suspended',
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'verification_status': shop.verification_status.value
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
        shop.verification_status = VerificationStatus.UNDER_REVIEW
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Shop "{shop.name}" is now under review',
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'verification_status': shop.verification_status.value
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

@admin_bp.route("/categories", methods=["POST"])
def create_category():
    """Create a new product category"""
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data or 'name' not in data:
            return jsonify({
                'success': False,
                'message': 'Category name is required'
            }), 400
        
        name = data['name'].strip()
        if not name:
            return jsonify({
                'success': False,
                'message': 'Category name cannot be empty'
            }), 400
        
        # Check if category with same name already exists
        existing_category = Category.query.filter_by(name=name).first()
        if existing_category:
            return jsonify({
                'success': False,
                'message': f'Category with name "{name}" already exists'
            }), 409
        
        # Create new category
        category = Category(
            name=name,
            description=data.get('description', '').strip() or None,
            is_active=data.get('is_active', True)
        )
        
        db.session.add(category)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Category created successfully',
            'category': category.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error creating category',
            'error': str(e)
        }), 500

@admin_bp.route("/categories/<int:category_id>")
def get_category(category_id):
    """Get specific category details"""
    try:
        category = Category.query.get_or_404(category_id)
        
        return jsonify({
            'success': True,
            'category': category.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching category',
            'error': str(e)
        }), 500

@admin_bp.route("/categories/<int:category_id>", methods=["PUT"])
def update_category(category_id):
    """Update category information"""
    try:
        category = Category.query.get_or_404(category_id)
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'message': 'No data provided'
            }), 400
        
        # Update name if provided
        if 'name' in data:
            new_name = data['name'].strip()
            if not new_name:
                return jsonify({
                    'success': False,
                    'message': 'Category name cannot be empty'
                }), 400
            
            # Check if another category with this name exists
            existing = Category.query.filter(
                Category.name == new_name,
                Category.id != category_id
            ).first()
            
            if existing:
                return jsonify({
                    'success': False,
                    'message': f'Category with name "{new_name}" already exists'
                }), 409
            
            category.name = new_name
        
        # Update description if provided
        if 'description' in data:
            category.description = data['description'].strip() or None
        
        # Update is_active if provided
        if 'is_active' in data:
            category.is_active = bool(data['is_active'])
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Category updated successfully',
            'category': category.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating category',
            'error': str(e)
        }), 500

@admin_bp.route("/categories/<int:category_id>", methods=["DELETE"])
def delete_category(category_id):
    """Delete or deactivate a category"""
    try:
        category = Category.query.get_or_404(category_id)
        
        # Check if category has products
        product_count = len(category.products) if category.products else 0
        
        if product_count > 0:
            # Soft delete: deactivate instead of deleting
            category.is_active = False
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Category deactivated (has {product_count} associated products)',
                'category': category.to_dict()
            }), 200
        else:
            # Hard delete: no products associated
            db.session.delete(category)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Category deleted successfully'
            }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error deleting category',
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
            "user": (SubscriptionType.USER, User),
            "product": (SubscriptionType.PRODUCT, Product),
            "shop": (SubscriptionType.SHOP, Shop)
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
            "user": SubscriptionType.USER,
            "product": SubscriptionType.PRODUCT,
            "shop": SubscriptionType.SHOP
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

