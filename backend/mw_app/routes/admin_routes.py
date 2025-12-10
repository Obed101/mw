from flask import Blueprint, jsonify, request
from backend.mw_app import db
from backend.mw_app.models import Category, Shop, User, VerificationStatus
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

