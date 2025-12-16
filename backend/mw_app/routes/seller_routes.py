from flask import Blueprint, jsonify, request
from ..extensions import db
from ..models import Shop, UserFollowShop, User, Product, StockUpdate, VerificationOTP, VerificationStatus
from datetime import datetime

seller_bp = Blueprint('seller_bp', __name__, url_prefix='/seller')

@seller_bp.route("/")
def seller_dashboard():
    """Seller dashboard with shop overview and product statistics"""
    return jsonify({"message": "Seller dashboard"})

@seller_bp.route("/shop")
def my_shop():
    """Get seller's shop information"""
    return jsonify({"message": "My shop"})

@seller_bp.route("/shop", methods=["PUT"])
def update_shop():
    """Update shop information"""
    return jsonify({"message": "Update shop"})

@seller_bp.route("/products")
def my_products():
    """Get all products in seller's shop with filtering"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get query parameters
        search = request.args.get('search', '').strip()
        in_stock = request.args.get('in_stock')
        low_stock = request.args.get('low_stock')
        out_of_stock = request.args.get('out_of_stock')
        low_stock_threshold = request.args.get('low_stock_threshold', 10, type=int)
        needs_update = request.args.get('needs_update')  # Shows low/out of stock items
        
        # Build query
        query = Product.query.filter_by(shop_id=shop.id)
        
        # Filter by search term
        if search:
            query = query.filter(
                db.or_(
                    Product.name.ilike(f'%{search}%'),
                    Product.description.ilike(f'%{search}%')
                )
            )
        
        # Filter by stock status
        if in_stock and in_stock.lower() in ('true', '1', 'yes'):
            query = query.filter(Product.stock > 0)
        
        if out_of_stock and out_of_stock.lower() in ('true', '1', 'yes'):
            query = query.filter(Product.stock <= 0)
        
        if low_stock and low_stock.lower() in ('true', '1', 'yes'):
            query = query.filter(
                db.and_(
                    Product.stock > 0,
                    Product.stock <= low_stock_threshold
                )
            )
        
        if needs_update and needs_update.lower() in ('true', '1', 'yes'):
            # Show products that need attention (low or out of stock)
            query = query.filter(Product.stock <= low_stock_threshold)
        
        # Order by stock (lowest first) if filtering by stock issues
        if needs_update or low_stock or out_of_stock:
            query = query.order_by(Product.stock.asc(), Product.name.asc())
        else:
            query = query.order_by(Product.name.asc())
        
        products = query.all()
        
        # Build response
        products_list = []
        for product in products:
            product_dict = {
                'id': product.id,
                'name': product.name,
                'price': product.price,
                'stock': product.stock,
                'is_low_stock': product.is_low_stock(low_stock_threshold),
                'is_out_of_stock': product.is_out_of_stock(),
                'category_id': product.category_id,
                'is_active': product.is_active
            }
            products_list.append(product_dict)
        
        return jsonify({
            'success': True,
            'count': len(products_list),
            'products': products_list
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching products',
            'error': str(e)
        }), 500

@seller_bp.route("/products", methods=["POST"])
def add_product():
    """Add a new product to the shop"""
    return jsonify({"message": "Add product"})

@seller_bp.route("/products/<int:product_id>")
def get_product(product_id):
    """Get a specific product details"""
    return jsonify({"message": f"Get product {product_id}"})

@seller_bp.route("/products/<int:product_id>", methods=["PUT"])
def update_product(product_id):
    """Update product information (name, price, stock, images, description)"""
    return jsonify({"message": f"Update product {product_id}"})

@seller_bp.route("/products/<int:product_id>", methods=["DELETE"])
def delete_product(product_id):
    """Remove a product from the shop"""
    return jsonify({"message": f"Delete product {product_id}"})

# Stock Management Routes
@seller_bp.route("/products/<int:product_id>/stock", methods=["PATCH"])
def update_stock(product_id):
    """Quick stock update - supports both absolute and incremental updates"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get product and verify ownership
        product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or does not belong to your shop'
            }), 404
        
        # Get update data
        stock = data.get('stock')
        stock_change = data.get('stock_change')
        reason = data.get('reason', '').strip()
        if not reason:
            # Determine type of stock update for autogenerated reason
            if stock is not None:
                # Absolute stock change
                if int(stock) > product.stock:
                    reason = "restocked"
                elif int(stock) < product.stock:
                    reason = "goods sold"
                else:
                    reason = "stock adjusted"
            elif stock_change is not None:
                if int(stock_change) > 0:
                    reason = "restocked"
                elif int(stock_change) < 0:
                    reason = "goods sold"
                else:
                    reason = "stock adjusted"
            else:
                reason = "stock adjusted"
        
        # Validate that either stock or stock_change is provided
        if stock is None and stock_change is None:
            return jsonify({
                'success': False,
                'message': 'Either "stock" (absolute value) or "stock_change" (incremental) is required'
            }), 400
        
        # Calculate new stock
        old_stock = product.stock
        if stock is not None:
            # Absolute stock update
            new_stock = int(stock)
            stock_change = new_stock - old_stock
        else:
            # Incremental stock update
            stock_change = int(stock_change)
            new_stock = old_stock + stock_change
            # Prevent negative stock
            if new_stock < 0:
                new_stock = 0
                stock_change = -old_stock
        
        # Update product stock
        product.stock = new_stock
        product.updated_at = datetime.now(datetime.timezone.utc)
        
        # Create stock update history record
        stock_update = StockUpdate(
            product_id=product_id,
            old_stock=old_stock,
            new_stock=new_stock,
            stock_change=stock_change,
            updated_by=seller_id,
            reason=reason
        )
        
        db.session.add(stock_update)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Stock updated successfully',
            'product': {
                'id': product.id,
                'name': product.name,
                'old_stock': old_stock,
                'new_stock': new_stock,
                'stock_change': stock_change,
                'is_low_stock': product.is_low_stock(),
                'is_out_of_stock': product.is_out_of_stock()
            },
            'update': stock_update.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Invalid stock value',
            'error': str(e)
        }), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error updating stock',
            'error': str(e)
        }), 500

@seller_bp.route("/products/stock/bulk", methods=["POST"])
def bulk_update_stock():
    """Bulk update stock for multiple products"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get updates array
        updates = data.get('updates', [])
        if not updates or not isinstance(updates, list):
            return jsonify({
                'success': False,
                'message': 'Updates array is required'
            }), 400
        
        results = []
        errors = []
        
        for update_item in updates:
            try:
                product_id = update_item.get('product_id')
                stock = update_item.get('stock')
                stock_change = update_item.get('stock_change')
                reason = update_item.get('reason', '').strip() or None
                
                if not product_id:
                    errors.append({'product_id': None, 'error': 'Product ID is required'})
                    continue
                
                # Get product and verify ownership
                product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
                if not product:
                    errors.append({'product_id': product_id, 'error': 'Product not found or does not belong to your shop'})
                    continue
                
                # Calculate new stock
                old_stock = product.stock
                if stock is not None:
                    new_stock = int(stock)
                    stock_change = new_stock - old_stock
                elif stock_change is not None:
                    stock_change = int(stock_change)
                    new_stock = old_stock + stock_change
                    if new_stock < 0:
                        new_stock = 0
                        stock_change = -old_stock
                else:
                    errors.append({'product_id': product_id, 'error': 'Either "stock" or "stock_change" is required'})
                    continue
                
                # Update product
                product.stock = new_stock
                product.updated_at = datetime.now(datetime.timezone.utc)
                
                # Create stock update history
                stock_update = StockUpdate(
                    product_id=product_id,
                    old_stock=old_stock,
                    new_stock=new_stock,
                    stock_change=stock_change,
                    updated_by=seller_id,
                    reason=reason
                )
                db.session.add(stock_update)
                
                results.append({
                    'product_id': product_id,
                    'product_name': product.name,
                    'old_stock': old_stock,
                    'new_stock': new_stock,
                    'stock_change': stock_change
                })
                
            except ValueError as e:
                errors.append({'product_id': product_id, 'error': f'Invalid stock value: {str(e)}'})
                continue
            except Exception as e:
                errors.append({'product_id': product_id, 'error': str(e)})
                continue
        
        if results:
            db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Updated {len(results)} product(s)',
            'updated': results,
            'errors': errors if errors else None
        }), 200 if not errors else 207  # 207 Multi-Status if there are errors
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error performing bulk update',
            'error': str(e)
        }), 500

@seller_bp.route("/products/<int:product_id>/stock/history")
def get_stock_history(product_id):
    """Get stock update history for a product"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Verify product belongs to shop
        product = Product.query.filter_by(id=product_id, shop_id=shop.id).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or does not belong to your shop'
            }), 404
        
        # Get history
        limit = request.args.get('limit', 50, type=int)
        history = StockUpdate.query.filter_by(product_id=product_id).order_by(
            StockUpdate.updated_at.desc()
        ).limit(limit).all()
        
        return jsonify({
            'success': True,
            'product_id': product_id,
            'product_name': product.name,
            'current_stock': product.stock,
            'count': len(history),
            'history': [update.to_dict() for update in history]
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching stock history',
            'error': str(e)
        }), 500


@seller_bp.route("/shop/followers")
def get_shop_followers():
    """Get all followers of the seller's shop"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get all followers
        follows = UserFollowShop.query.filter_by(shop_id=shop.id).order_by(
            UserFollowShop.followed_at.desc()
        ).all()
        
        # Get follower details
        followers = []
        for follow in follows:
            user = User.query.get(follow.user_id)
            if user and user.is_active:
                follower_dict = {
                    'user_id': user.id,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'followed_at': follow.followed_at.isoformat() if follow.followed_at else None
                }
                followers.append(follower_dict)
        
        return jsonify({
            'success': True,
            'shop_id': shop.id,
            'shop_name': shop.name,
            'follower_count': len(followers),
            'followers': followers
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching shop followers',
            'error': str(e)
        }), 500

@seller_bp.route("/analytics")
def shop_analytics():
    """View shop analytics (views, popular products, followers, etc.)"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get follower count
        follower_count = UserFollowShop.query.filter_by(shop_id=shop.id).count()
        
        # TODO: Add more analytics (product views, popular products, etc.)
        return jsonify({
            'success': True,
            'shop_id': shop.id,
            'shop_name': shop.name,
            'analytics': {
                'follower_count': follower_count,
                'product_count': len(shop.products) if shop.products else 0
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching shop analytics',
            'error': str(e)
        }), 500

# Shop Verification Routes
@seller_bp.route("/shop/verification-status")
def get_verification_status():
    """Get shop verification status and requirements"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        return jsonify({
            'success': True,
            'shop_id': shop.id,
            'shop_name': shop.name,
            'verification_status': shop.verification_status.value if shop.verification_status else None,
            'phone_verified': shop.phone_verified,
            'email_verified': shop.email_verified,
            'can_request_verification': shop.can_request_verification(),
            'verification_requested_at': shop.verification_requested_at.isoformat() if shop.verification_requested_at else None,
            'verified_at': shop.verified_at.isoformat() if shop.verified_at else None,
            'rejection_reason': shop.rejection_reason
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching verification status',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-phone/request-otp", methods=["POST"])
def request_phone_otp():
    """Request OTP for phone verification"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        if not shop.phone:
            return jsonify({
                'success': False,
                'message': 'Shop phone number is not set'
            }), 400
        
        if shop.phone_verified:
            return jsonify({
                'success': False,
                'message': 'Phone is already verified'
            }), 400
        
        # Generate and create OTP
        otp_record, otp_code = VerificationOTP.create_otp(
            shop_id=shop.id,
            otp_type='phone',
            contact_value=shop.phone
        )
        
        # TODO: Send OTP via SMS service (Twilio, etc.)
        # For now, return OTP in response for testing
        return jsonify({
            'success': True,
            'message': 'OTP sent to phone',
            'otp': otp_code,  # Remove in production - only for testing
            'expires_in_minutes': 15,
            'phone': shop.phone[-4:]  # Show last 4 digits only
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error requesting phone OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-phone/verify", methods=["POST"])
def verify_phone_otp():
    """Verify phone using OTP"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        otp_code = data.get('otp')
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        if not otp_code:
            return jsonify({
                'success': False,
                'message': 'OTP code is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get active OTP
        otp_record = VerificationOTP.get_active_otp(shop.id, 'phone')
        if not otp_record:
            return jsonify({
                'success': False,
                'message': 'No active OTP found. Please request a new one.'
            }), 404
        
        # Verify OTP
        is_valid, message = otp_record.verify_otp(otp_code)
        if not is_valid:
            return jsonify({
                'success': False,
                'message': message
            }), 400
        
        # Mark phone as verified
        shop.phone_verified = True
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Phone verified successfully',
            'phone_verified': True
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error verifying phone OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-email/request-otp", methods=["POST"])
def request_email_otp():
    """Request OTP for email verification"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        if not shop.email:
            return jsonify({
                'success': False,
                'message': 'Shop email is not set'
            }), 400
        
        if shop.email_verified:
            return jsonify({
                'success': False,
                'message': 'Email is already verified'
            }), 400
        
        # Generate and create OTP
        otp_record, otp_code = VerificationOTP.create_otp(
            shop_id=shop.id,
            otp_type='email',
            contact_value=shop.email
        )
        
        # TODO: Send OTP via email service (SendGrid, etc.)
        # For now, return OTP in response for testing
        return jsonify({
            'success': True,
            'message': 'OTP sent to email',
            'otp': otp_code,  # Remove in production - only for testing
            'expires_in_minutes': 15,
            'email': shop.email  # For testing only
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error requesting email OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/verify-email/verify", methods=["POST"])
def verify_email_otp():
    """Verify email using OTP"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        otp_code = data.get('otp')
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        if not otp_code:
            return jsonify({
                'success': False,
                'message': 'OTP code is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Get active OTP
        otp_record = VerificationOTP.get_active_otp(shop.id, 'email')
        if not otp_record:
            return jsonify({
                'success': False,
                'message': 'No active OTP found. Please request a new one.'
            }), 404
        
        # Verify OTP
        is_valid, message = otp_record.verify_otp(otp_code)
        if not is_valid:
            return jsonify({
                'success': False,
                'message': message
            }), 400
        
        # Mark email as verified
        shop.email_verified = True
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Email verified successfully',
            'email_verified': True
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error verifying email OTP',
            'error': str(e)
        }), 500

@seller_bp.route("/shop/request-verification", methods=["POST"])
def request_verification():
    """Request shop verification (after phone and email are verified)"""
    try:
        # Get seller's user_id from request
        seller_id = request.args.get('seller_id', type=int)
        data = request.get_json() or {}
        seller_id = data.get('seller_id') or seller_id
        
        if not seller_id:
            return jsonify({
                'success': False,
                'message': 'Seller ID is required'
            }), 400
        
        # Get seller's shop
        seller = User.query.get(seller_id)
        if not seller or seller.role != 'seller':
            return jsonify({
                'success': False,
                'message': 'Seller not found'
            }), 404
        
        shop = seller.shop
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found for this seller'
            }), 404
        
        # Check if phone and email are verified
        if not shop.phone_verified:
            return jsonify({
                'success': False,
                'message': 'Phone must be verified before requesting shop verification'
            }), 400
        
        if not shop.email_verified:
            return jsonify({
                'success': False,
                'message': 'Email must be verified before requesting shop verification'
            }), 400
        
        # Check if already verified or under review
        if shop.verification_status == VerificationStatus.VERIFIED:
            return jsonify({
                'success': False,
                'message': 'Shop is already verified'
            }), 400
        
        if shop.verification_status == VerificationStatus.UNDER_REVIEW:
            return jsonify({
                'success': False,
                'message': 'Shop verification is already under review'
            }), 400
        
        # Request verification
        shop.verification_status = VerificationStatus.PENDING
        shop.verification_requested_at = datetime.now(datetime.timezone.utc)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Verification request submitted. Admin will review your shop.',
            'verification_status': shop.verification_status.value,
            'verification_requested_at': shop.verification_requested_at.isoformat()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error requesting verification',
            'error': str(e)
        }), 500

