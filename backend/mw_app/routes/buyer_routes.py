from flask import Blueprint, jsonify, request, render_template
from sqlalchemy import or_
from ..extensions import db
from ..models import (
    Category,
    User,
    UserBrowsingHistory,
    Product,
    Shop,
    UserFollowShop,
    VERIFICATION_STATUS_VERIFIED,
)

buyer_bp = Blueprint('buyer_bp', __name__, url_prefix='/explore')
SHOPS_PER_PAGE = 3
PRODUCTS_PER_PAGE = 12


def _is_htmx_request():
    return request.headers.get('HX-Request') == 'true'

@buyer_bp.route("/")
def buyer_dashboard():
    """Marketplace dashboard showing available products and shops"""
    return jsonify({"message": "Marketplace dashboard"})

@buyer_bp.route("/shops")
def browse_shops():
    """Browse all shops in the marketplace"""
    try:
        search_term = request.args.get('search', '').strip()
        sort_by = request.args.get('sort_by', 'name')
        category_id = request.args.get('category_id', type=int) or request.args.get('category', type=int)
        user_id = request.args.get('user_id', type=int)
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', SHOPS_PER_PAGE, type=int)

        query = Shop.query.filter(
            Shop.is_active.is_(True),
            Shop.verification_status == VERIFICATION_STATUS_VERIFIED,
        )

        if search_term:
            query = query.filter(
                or_(
                    Shop.name.ilike(f'%{search_term}%'),
                    Shop.description.ilike(f'%{search_term}%'),
                    Shop.region.ilike(f'%{search_term}%'),
                    Shop.town.ilike(f'%{search_term}%'),
                )
            )

        if category_id:
            query = query.join(Product).filter(
                Product.category_id == category_id,
                Product.is_active.is_(True),
            )

        query = query.distinct()

        if sort_by == 'last_updated':
            query = query.order_by(Shop.last_updated.desc())
        elif sort_by == 'promoted':
            query = query.order_by(Shop.promoted.desc(), Shop.name.asc())
        else:
            query = query.order_by(Shop.name.asc())

        shops = query.paginate(page=page, per_page=per_page, error_out=False)

        followed_shop_ids = set()
        if user_id:
            follows = UserFollowShop.query.filter_by(user_id=user_id).all()
            followed_shop_ids = {follow.shop_id for follow in follows}

        if _is_htmx_request():
            return render_template(
                'buyer/shop_cards.html',
                shops=shops.items,
                followed_shop_ids=followed_shop_ids,
                user_id=user_id,
                has_next=shops.has_next,
                next_page=shops.next_num,
                search_term=search_term,
                sort_by=sort_by,
                category_id=category_id,
            )

        shop_rows = []
        for shop in shops.items:
            shop_rows.append(
                {
                    'id': shop.id,
                    'name': shop.name,
                    'description': shop.description,
                    'region': shop.region,
                    'town': shop.town,
                    'product_count': len([p for p in shop.products if p.is_active]),
                }
            )

        return jsonify(
            {
                'success': True,
                'count': len(shop_rows),
                'total': shops.total,
                'page': shops.page,
                'pages': shops.pages,
                'has_next': shops.has_next,
                'shops': shop_rows,
            }
        ), 200

    except Exception as e:
        if _is_htmx_request():
            return "<div class='alert alert-danger'>Error loading shops</div>", 500
        return jsonify({
            'success': False,
            'message': 'Error browsing shops',
            'error': str(e)
        }), 500

@buyer_bp.route("/shops/<int:shop_id>")
def view_shop(shop_id):
    """View a specific shop and its products"""
    try:
        # Only allow viewing verified shops
        shop = Shop.query.filter_by(
            id=shop_id,
            is_active=True,
            verification_status=VERIFICATION_STATUS_VERIFIED
        ).first_or_404()
        
        # Get user_id from request (for checking if user follows)
        user_id = request.args.get('user_id', type=int)
        is_following = False
        
        if user_id:
            # Check if user follows this shop
            follow = UserFollowShop.query.filter_by(
                user_id=user_id,
                shop_id=shop_id
            ).first()
            is_following = follow is not None
        
        # Return shop details
        return jsonify({
            'success': True,
            'shop': {
                'id': shop.id,
                'name': shop.name,
                'description': shop.description,
                'address': shop.address,
                'phone': shop.phone,
                'email': shop.email,
                'is_following': is_following
            }
        }), 200
    
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching shop',
            'error': str(e)
        }), 500

@buyer_bp.route("/shops/<int:shop_id>/products")
def shop_products(shop_id):
    """View all products available in a specific shop"""
    try:
        # Only allow viewing products from verified shops
        shop = Shop.query.filter_by(
            id=shop_id,
            is_active=True,
            verification_status=VERIFICATION_STATUS_VERIFIED
        ).first_or_404()
        
        # Query params: search, min_price, max_price, in_stock (true/false)
        # TODO: Implement actual product filtering logic
        return jsonify({
            'success': True,
            'shop_id': shop_id,
            'shop_name': shop.name,
            'message': f"Products in shop {shop_id}"
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Shop not found or not verified',
            'error': str(e)
        }), 404

@buyer_bp.route("/categories")
def get_categories():
    """Get all active product categories for filtering"""
    try:
        # Only return active categories for buyers
        categories = Category.query.filter_by(is_active=True).order_by(Category.name).all()
        
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

@buyer_bp.route("/categories/recommended")
def get_recommended_categories():
    """Get recommended categories based on user's browsing history"""
    try:
        # Get user_id from request (from session, JWT token, or query param)
        # For now, using query param - in production, get from authenticated session
        user_id = request.args.get('user_id', type=int)
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found'
            }), 404
        
        # Get limit and days_back from query params
        limit = request.args.get('limit', 5, type=int)
        days_back = request.args.get('days_back', 30, type=int)
        
        # Get recommended categories
        recommended = user.get_recommended_categories(limit=limit, days_back=days_back)
        
        return jsonify({
            'success': True,
            'count': len(recommended),
            'recommended_categories': recommended
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching recommended categories',
            'error': str(e)
        }), 500

@buyer_bp.route("/browse/track", methods=["POST"])
def track_browsing():
    """Track a browsing event (product view, category view, etc.)"""
    try:
        data = request.get_json(silent=True) or {}
        
        # Get user_id from request
        user_id = data.get('user_id') or request.args.get('user_id', type=int)
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found'
            }), 404
        
        # Track the browsing event
        browsing_event = UserBrowsingHistory.track_view(
            user_id=user_id,
            product_id=data.get('product_id'),
            category_id=data.get('category_id'),
            shop_id=data.get('shop_id'),
            interaction_type=data.get('interaction_type', 'view')
        )
        
        return jsonify({
            'success': True,
            'message': 'Browsing event tracked',
            'event_id': browsing_event.id
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error tracking browsing event',
            'error': str(e)
        }), 500

@buyer_bp.route("/products")
def browse_products():
    """Browse all products across all shops with filters"""
    try:
        user_id = request.args.get('user_id', type=int)
        category_id = request.args.get('category_id', type=int)
        search_term = request.args.get('search', '').strip()
        sort_by = request.args.get('sort_by', 'name')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', PRODUCTS_PER_PAGE, type=int)
        
        # Track category view if user_id and category_id are provided
        if user_id and category_id:
            try:
                UserBrowsingHistory.track_view(
                    user_id=user_id,
                    category_id=category_id,
                    interaction_type='browse'
                )
            except Exception:
                # Don't fail the request if tracking fails
                pass
        
        query = Product.query.join(Shop).filter(
            Shop.verification_status == VERIFICATION_STATUS_VERIFIED,
            Shop.is_active.is_(True),
            Product.is_active.is_(True),
        )
        
        # Filter by category
        if category_id:
            query = query.filter(Product.category_id == category_id)
        
        # Filter by shop
        shop_id = request.args.get('shop_id', type=int)
        if shop_id:
            query = query.filter(Product.shop_id == shop_id)
        
        min_price = request.args.get('min_price', type=float)
        max_price = request.args.get('max_price', type=float)
        if min_price is not None:
            query = query.filter(Product.price >= min_price)
        if max_price is not None:
            query = query.filter(Product.price <= max_price)

        in_stock = request.args.get('in_stock')
        if in_stock and in_stock.lower() in ('true', '1', 'yes'):
            query = query.filter(Product.stock > 0)

        if search_term:
            query = query.filter(
                or_(
                    Product.name.ilike(f'%{search_term}%'),
                    Product.description.ilike(f'%{search_term}%'),
                    Shop.name.ilike(f'%{search_term}%'),
                )
            )

        if sort_by == 'price':
            query = query.order_by(Product.price.asc())
        elif sort_by == 'price_desc':
            query = query.order_by(Product.price.desc())
        elif sort_by == 'stock':
            query = query.order_by(Product.stock.desc())
        elif sort_by == 'newest':
            query = query.order_by(Product.created_at.desc())
        else:
            query = query.order_by(Product.name.asc())

        products = query.paginate(page=page, per_page=per_page, error_out=False)

        if _is_htmx_request():
            return render_template(
                'buyer/product_cards.html',
                products=products.items,
                has_next=products.has_next,
                next_page=products.next_num,
                search_term=search_term,
                category_id=category_id,
                shop_id=shop_id,
                min_price=min_price,
                max_price=max_price,
                in_stock=in_stock,
                sort_by=sort_by,
            )

        products_list = []
        for product in products.items:
            products_list.append(
                {
                    'id': product.id,
                    'name': product.name,
                    'price': product.price,
                    'stock': product.stock,
                    'category_id': product.category_id,
                    'shop_id': product.shop_id,
                    'shop_name': product.shop.name if product.shop else None,
                }
            )

        return jsonify({
            'success': True,
            'total': products.total,
            'page': products.page,
            'pages': products.pages,
            'count': len(products_list),
            'products': products_list
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error browsing products',
            'error': str(e)
        }), 500

@buyer_bp.route("/products/<int:product_id>")
def view_product(product_id):
    """View product details including price, availability, and shop info"""
    try:
        # Only show products from verified shops
        product = Product.query.join(Shop).filter(
            Product.id == product_id,
            Shop.verification_status == VERIFICATION_STATUS_VERIFIED,
            Shop.is_active.is_(True),
        ).first_or_404()
        
        # Get user_id from request (from session, JWT token, or query param)
        user_id = request.args.get('user_id', type=int)
        
        # Automatically track browsing if user_id is provided
        if user_id:
            try:
                UserBrowsingHistory.track_view(
                    user_id=user_id,
                    product_id=product_id,
                    interaction_type='view'
                )
            except Exception:
                # Don't fail the request if tracking fails
                pass
        
        # Return product details (you'll implement full product serialization later)
        return jsonify({
            'success': True,
            'product': {
                'id': product.id,
                'name': product.name,
                'price': product.price,
                'stock': product.stock,
                'category_id': product.category_id,
                'shop_id': product.shop_id,
                'shop_name': product.shop.name if product.shop else None,
                'description': product.description,
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching product',
            'error': str(e)
        }), 500

@buyer_bp.route("/products/search")
def search_products():
    """Search products by name across all shops"""
    # Query params: q (search query), shop_id, min_price, max_price
    return jsonify({"message": "Search products"})

@buyer_bp.route("/products/compare")
def compare_prices():
    """Compare prices of a product across different shops"""
    # Query params: product_name or product_id
    return jsonify({"message": "Compare prices across shops"})

@buyer_bp.route("/products/availability")
def check_availability():
    """Check real-time availability of products"""
    # Query params: product_id, shop_id
    return jsonify({"message": "Check product availability"})

# Shop Following Routes
@buyer_bp.route("/shops/<int:shop_id>/follow", methods=["POST"])
def follow_shop(shop_id):
    """Follow a shop"""
    try:
        # Get user_id from request
        data = request.get_json() or {}
        user_id = data.get('user_id') or request.args.get('user_id', type=int)
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400
        
        # Verify user exists
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found'
            }), 404
        
        # Verify shop exists
        shop = Shop.query.get(shop_id)
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found'
            }), 404
        
        # Check if already following
        existing_follow = UserFollowShop.query.filter_by(
            user_id=user_id,
            shop_id=shop_id
        ).first()
        
        if existing_follow:
            return jsonify({
                'success': False,
                'message': 'Already following this shop'
            }), 409
        
        # Create follow relationship
        follow = UserFollowShop(
            user_id=user_id,
            shop_id=shop_id
        )
        
        db.session.add(follow)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Now following {shop.name}',
            'follow': follow.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error following shop',
            'error': str(e)
        }), 500

@buyer_bp.route("/shops/<int:shop_id>/follow", methods=["DELETE"])
def unfollow_shop(shop_id):
    """Unfollow a shop"""
    try:
        # Get user_id from request
        user_id = request.args.get('user_id', type=int)
        data = request.get_json() or {}
        user_id = data.get('user_id') or user_id
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400
        
        # Find and delete follow relationship
        follow = UserFollowShop.query.filter_by(
            user_id=user_id,
            shop_id=shop_id
        ).first()
        
        if not follow:
            return jsonify({
                'success': False,
                'message': 'Not following this shop'
            }), 404
        
        db.session.delete(follow)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Unfollowed shop successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error unfollowing shop',
            'error': str(e)
        }), 500

@buyer_bp.route("/shops/following")
def get_followed_shops():
    """Get all shops that the user follows"""
    try:
        # Get user_id from request
        user_id = request.args.get('user_id', type=int)
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400
        
        user = User.query.get(user_id)
        if not user:
            return jsonify({
                'success': False,
                'message': 'User not found'
            }), 404
        
        # Get all followed shops
        follows = UserFollowShop.query.filter_by(user_id=user_id).order_by(
            UserFollowShop.followed_at.desc()
        ).all()
        
        # Get shop details - only verified shops
        shops = []
        for follow in follows:
            shop = Shop.query.get(follow.shop_id)
            if shop and shop.is_active and shop.verification_status == VERIFICATION_STATUS_VERIFIED:
                shop_dict = {
                    'id': shop.id,
                    'name': shop.name,
                    'description': shop.description,
                    'address': shop.address,
                    'phone': shop.phone,
                    'email': shop.email,
                    'followed_at': follow.followed_at.isoformat() if follow.followed_at else None
                }
                shops.append(shop_dict)
        
        return jsonify({
            'success': True,
            'count': len(shops),
            'shops': shops
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching followed shops',
            'error': str(e)
        }), 500

@buyer_bp.route("/shops/<int:shop_id>/is-following")
def check_following_status(shop_id):
    """Check if user follows a specific shop"""
    try:
        # Get user_id from request
        user_id = request.args.get('user_id', type=int)
        
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400
        
        # Check if following
        follow = UserFollowShop.query.filter_by(
            user_id=user_id,
            shop_id=shop_id
        ).first()
        
        return jsonify({
            'success': True,
            'is_following': follow is not None,
            'followed_at': follow.followed_at.isoformat() if follow and follow.followed_at else None
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error checking follow status',
            'error': str(e)
        }), 500

