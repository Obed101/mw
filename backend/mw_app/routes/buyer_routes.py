import meilisearch
from flask import Blueprint, jsonify, request, render_template, current_app, session
from flask_login import current_user
from sqlalchemy import or_, nullslast
from ..extensions import db
from ..models import (
    Category,
    Notification,
    User,
    UserBrowsingHistory,
    USER_ROLE_ADMIN,
    USER_ROLE_BUYER,
    Product,
    Shop,
    UserFavoriteProduct,
    UserFollowShop,
)
from ..utils.location import get_user_location, haversine_distance_expr, NEAR_YOU_KM

buyer_bp = Blueprint('buyer_bp', __name__, url_prefix='/explore')
SHOPS_PER_PAGE = 3
PRODUCTS_PER_PAGE = 12


def _is_htmx_request():
    return request.headers.get('HX-Request') == 'true'


def _request_json():
    return request.get_json(silent=True) or {}


def _resolve_user_id(raw_user_id=None, body=None):
    if raw_user_id:
        return raw_user_id
    if body and body.get('user_id'):
        return body.get('user_id')
    if current_user.is_authenticated:
        return current_user.id
    return None


def _load_buyer_user(user_id):
    user = User.query.get(user_id)
    if not user:
        return None, (
            jsonify({
                'success': False,
                'message': 'User not found'
            }),
            404,
        )
    return user, None


def _render_shop_favorite_button(shop_id, is_favorited):
    return render_template(
        'buyer/partials/shop_favorite_button.html',
        shop_id=shop_id,
        is_favorited=is_favorited,
    )


def _render_product_favorite_button(product_id, is_favorited, product_detail=None):
    return render_template(
        'buyer/partials/product_favorite_button.html',
        product_id=product_id,
        is_favorited=is_favorited,
        product_detail=product_detail,
    )


def _notify_shop_owner_and_admins_for_favorite(user, shop, product=None):
    admin_ids = [
        admin.id
        for admin in User.query.filter_by(role=USER_ROLE_ADMIN).all()
    ]
    recipient_ids = set(admin_ids)
    if shop and shop.owner_id:
        recipient_ids.add(shop.owner_id)

    if product:
        title = 'Product Favorited'
        message = f'{user.username} favorited "{product.name}" from {shop.name}.'
        notification_type = 'product_favorited'
    else:
        title = 'Shop Favorited'
        message = f'{user.username} favorited your shop "{shop.name}".'
        notification_type = 'shop_favorited'

    Notification.create_for_users(
        user_ids=recipient_ids,
        notification_type=notification_type,
        title=title,
        message=message,
        actor_user_id=user.id,
        related_shop_id=shop.id if shop else None,
        related_product_id=product.id if product else None,
        payload={
            'buyer_id': user.id,
            'shop_id': shop.id if shop else None,
            'product_id': product.id if product else None,
        },
        exclude_user_id=user.id,
    )

@buyer_bp.route('/location', methods=['POST'])
def update_location():
    """Store user GPS coordinates (from browser Geolocation API).

    Accepts JSON: {"latitude": float, "longitude": float}
    - If authenticated: persists to User.latitude / User.longitude
    - Always writes to session for anonymous users too
    - Never overwrites valid data with null; silently ignores invalid coords
    """
    try:
        data = request.get_json(silent=True) or {}
        lat = data.get('latitude')
        lng = data.get('longitude')

        # Validate bounds
        if lat is None or lng is None:
            return jsonify({'ok': False, 'error': 'Missing coordinates'}), 422
        try:
            lat = float(lat)
            lng = float(lng)
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'Invalid coordinate format'}), 422

        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return jsonify({'ok': False, 'error': 'Coordinates out of range'}), 422

        # Persist to user record if logged in
        if current_user.is_authenticated:
            current_user.latitude = lat
            current_user.longitude = lng
            db.session.commit()

        # Always store in session (works for both anon and logged-in users)
        session['user_lat'] = lat
        session['user_lng'] = lng

        return jsonify({'ok': True}), 200

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(exc)
        # Return success anyway — location failure must never break the UI
        return jsonify({'ok': False}), 200


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
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', SHOPS_PER_PAGE, type=int)

        # Resolve user location for distance-aware sorting
        user_lat, user_lng = get_user_location(current_user)
        dist_expr = haversine_distance_expr(user_lat, user_lng) if user_lat is not None else None

        query = Shop.query.filter(Shop.is_active.is_(True))

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

        # Primary sort (user choice) + location as secondary tiebreaker
        if sort_by == 'last_updated':
            primary = [Shop.last_updated.desc()]
        elif sort_by == 'promoted':
            primary = [Shop.promoted.desc(), Shop.name.asc()]
        else:
            primary = [Shop.name.asc()]

        if dist_expr is not None:
            query = query.order_by(*primary, nullslast(dist_expr.asc()))
        else:
            query = query.order_by(*primary)

        # Annotate distance so templates can show 'Near you' badge
        if dist_expr is not None:
            query = query.add_columns(dist_expr.label('distance_km'))
            shops_page = query.paginate(page=page, per_page=per_page, error_out=False)
            shop_items = [(row[0], row[1]) for row in shops_page.items]  # (shop, dist)
        else:
            shops_page = query.paginate(page=page, per_page=per_page, error_out=False)
            shop_items = [(shop, None) for shop in shops_page.items]

        followed_shop_ids = set()
        if user_id:
            follows = UserFollowShop.query.filter_by(user_id=user_id).all()
            followed_shop_ids = {follow.shop_id for follow in follows}

        # Attach distance / near_you onto shop objects for template use
        shops_annotated = []
        for shop, dist_km in shop_items:
            shop._distance_km = dist_km
            shop._near_you = (dist_km is not None and dist_km <= NEAR_YOU_KM)
            shops_annotated.append(shop)

        if _is_htmx_request():
            return render_template(
                'buyer/shop_cards.html',
                shops=shops_annotated,
                followed_shop_ids=followed_shop_ids,
                user_id=user_id,
                has_next=shops_page.has_next,
                next_page=shops_page.next_num,
                search_term=search_term,
                sort_by=sort_by,
                category_id=category_id,
                user_has_location=(user_lat is not None),
            )

        shop_rows = []
        for shop in shops_annotated:
            shop_rows.append(
                {
                    'id': shop.id,
                    'name': shop.name,
                    'description': shop.description,
                    'region': shop.region,
                    'town': shop.town,
                    'product_count': len([p for p in shop.products if p.is_active]),
                    'image_urls': shop.image_urls,
                    'primary_image_url': shop.primary_image_url,
                    'is_favorited': shop.id in followed_shop_ids,
                    'verification_status': shop.verification_status,
                    'distance_km': round(shop._distance_km, 1) if shop._distance_km is not None else None,
                    'near_you': shop._near_you,
                }
            )

        return jsonify(
            {
                'success': True,
                'count': len(shop_rows),
                'total': shops_page.total,
                'page': shops_page.page,
                'pages': shops_page.pages,
                'has_next': shops_page.has_next,
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
        shop = Shop.query.filter_by(
            id=shop_id,
            is_active=True,
        ).first_or_404()
        
        # Get user_id from request (for checking if user follows)
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
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
                'gps': shop.gps,
                'phone': shop.phone,
                'email': shop.email,
                'image_urls': shop.image_urls,
                'primary_image_url': shop.primary_image_url,
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
        shop = Shop.query.filter_by(
            id=shop_id,
            is_active=True,
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

@buyer_bp.route("/products/<int:product_id>")
def product_detail(product_id):
    """View detailed information for a specific product"""
    try:
        product = Product.query.options(
            db.joinedload(Product.shop)
        ).get_or_404(product_id)

        shop = product.shop

        is_favorited = False
        is_following = False

        if current_user.is_authenticated:
            is_favorited = UserFavoriteProduct.query.filter_by(
                user_id=current_user.id,
                product_id=product_id
            ).first() is not None

            is_following = UserFollowShop.query.filter_by(
                user_id=current_user.id,
                shop_id=shop.id
            ).first() is not None

        related_products = Product.query.join(Shop).filter(
            Product.category_id == product.category_id,
            Product.id != product.id,
            Product.is_active == True,
            Shop.is_active.is_(True),
        ).limit(4).all()

        # IMPORTANT: controls UI variation (card vs details view)
        variant = request.args.get("variant", "product_card")

        return render_template(
            "buyer/product_detail.html",
            product=product,
            shop=shop,
            is_favorited=is_favorited,
            is_following=is_following,
            related_products=related_products,
            variant=variant
        )

    except Exception as e:
        raise e

        
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
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
        is_favorited = False
        
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
        data = _request_json()
        
        # Get user_id from request
        user_id = _resolve_user_id(request.args.get('user_id', type=int), data)
        
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
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
        category_id = request.args.get('category_id', type=int)
        search_term = request.args.get('search', '').strip()
        sort_by = request.args.get('sort_by', 'name')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', PRODUCTS_PER_PAGE, type=int)

        # Resolve user location for distance-aware secondary sort
        user_lat, user_lng = get_user_location(current_user)
        dist_expr = haversine_distance_expr(user_lat, user_lng) if user_lat is not None else None

        # Track category view if user_id and category_id are provided
        if user_id and category_id:
            try:
                UserBrowsingHistory.track_view(
                    user_id=user_id,
                    category_id=category_id,
                    interaction_type='browse'
                )
            except Exception:
                pass

        query = Product.query.join(Shop).filter(
            Shop.is_active.is_(True),
            Product.is_active.is_(True),
        )

        # Filters
        if category_id:
            query = query.filter(Product.category_id == category_id)

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

        # Primary sort (user choice) + location as secondary tiebreaker
        if sort_by == 'price':
            primary = [Product.price.asc()]
        elif sort_by == 'price_desc':
            primary = [Product.price.desc()]
        elif sort_by == 'stock':
            primary = [Product.stock.desc()]
        elif sort_by == 'newest':
            primary = [Product.created_at.desc()]
        else:
            primary = [Product.name.asc()]

        if dist_expr is not None:
            query = query.order_by(*primary, nullslast(dist_expr.asc()))
        else:
            query = query.order_by(*primary)

        # Annotate distance for Near You badge
        if dist_expr is not None:
            query = query.add_columns(dist_expr.label('distance_km'))
            products_page = query.paginate(page=page, per_page=per_page, error_out=False)
            product_items = [(row[0], row[1]) for row in products_page.items]
        else:
            products_page = query.paginate(page=page, per_page=per_page, error_out=False)
            product_items = [(p, None) for p in products_page.items]

        favorite_product_ids = set()
        if user_id:
            try:
                favorites = UserFavoriteProduct.query.filter_by(user_id=user_id).all()
                favorite_product_ids = {favorite.product_id for favorite in favorites}
            except Exception:
                db.session.rollback()
                favorite_product_ids = set()

        # Attach distance / near_you onto product objects for template use
        products_annotated = []
        for product, dist_km in product_items:
            product._distance_km = dist_km
            product._near_you = (dist_km is not None and dist_km <= NEAR_YOU_KM)
            products_annotated.append(product)

        if _is_htmx_request():
            return render_template(
                'buyer/product_cards.html',
                products=products_annotated,
                favorite_product_ids=favorite_product_ids,
                user_id=user_id,
                has_next=products_page.has_next,
                next_page=products_page.next_num,
                search_term=search_term,
                category_id=category_id,
                shop_id=shop_id,
                min_price=min_price,
                max_price=max_price,
                in_stock=in_stock,
                sort_by=sort_by,
                user_has_location=(user_lat is not None),
            )

        products_list = []
        for product in products_annotated:
            products_list.append(
                {
                    'id': product.id,
                    'name': product.name,
                    'price': product.price,
                    'stock': product.stock,
                    'category_id': product.category_id,
                    'shop_id': product.shop_id,
                    'shop_name': product.shop.name if product.shop else None,
                    'image_urls': product.image_urls,
                    'primary_image_url': product.primary_image_url,
                    'is_favorited': product.id in favorite_product_ids,
                    'distance_km': round(product._distance_km, 1) if product._distance_km is not None else None,
                    'near_you': product._near_you,
                }
            )

        return jsonify({
            'success': True,
            'total': products_page.total,
            'page': products_page.page,
            'pages': products_page.pages,
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
        product = Product.query.join(Shop).filter(
            Product.id == product_id,
            Shop.is_active.is_(True),
            Product.is_active.is_(True),
        ).first_or_404()
        
        # Get user_id from request (from session, JWT token, or query param)
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
        is_favorited = False
        
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
            try:
                is_favorited = UserFavoriteProduct.query.filter_by(
                    user_id=user_id,
                    product_id=product_id,
                ).first() is not None
            except Exception:
                db.session.rollback()
                is_favorited = False
        
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
                'image_urls': product.image_urls,
                'primary_image_url': product.primary_image_url,
                'is_favorited': is_favorited,
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching product',
            'error': str(e)
        }), 500

@buyer_bp.route("/global-search")
def global_search():
    """Global search across products, shops, and categories using MeiliSearch."""
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return ""

    products_hits = []
    shops_hits = []
    categories_hits = []

    try:
        # Connect to MeiliSearch
        ms_url = current_app.config.get('MEILISEARCH_URL', 'http://127.0.0.1:7700')
        ms_key = current_app.config.get('MEILISEARCH_KEY', 'masterKey')
        client = meilisearch.Client(ms_url, ms_key)

        # Execute searches (handles typo tolerance naturally)
        products_res = client.index('products').search(q, {'limit': 5})
        products_hits = products_res.get('hits', [])

        shops_res = client.index('shops').search(q, {'limit': 3})
        shops_hits = shops_res.get('hits', [])

        categories_res = client.index('categories').search(q, {'limit': 3})
        categories_hits = categories_res.get('hits', [])

    except Exception as e:
        # Fallback to DB search if MeiliSearch is unavailable
        products_db = Product.query.filter(
            Product.name.ilike(f'%{q}%'), 
            Product.is_active.is_(True)
        ).limit(5).all()
        
        shops_db = Shop.query.filter(
            Shop.name.ilike(f'%{q}%'), 
            Shop.is_active.is_(True)
        ).limit(3).all()
        
        categories_db = Category.query.filter(
            Category.name.ilike(f'%{q}%'), 
            Category.is_active.is_(True)
        ).limit(3).all()

        # Format exactly like MeiliSearch hits for the template
        products_hits = [{'id': p.id, 'name': p.name, 'price': p.price, 'primary_image_url': p.primary_image_url, 'shop_name': p.shop.name if p.shop else ''} for p in products_db]
        shops_hits = [{'id': s.id, 'name': s.name, 'town': s.town, 'primary_image_url': s.primary_image_url} for s in shops_db]
        categories_hits = [{'id': c.id, 'name': c.name} for c in categories_db]

    return render_template(
        'public/partials/global_search_results.html',
        products=products_hits,
        shops=shops_hits,
        categories=categories_hits,
        query=q
    )

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

# Shop Following / Favorite Routes
@buyer_bp.route("/shops/<int:shop_id>/follow", methods=["POST"])
@buyer_bp.route("/shops/<int:shop_id>/favorite", methods=["POST"])
def follow_shop(shop_id):
    """Toggle shop follow status - adds if not following, removes if following."""
    try:
        data = _request_json()
        user_id = _resolve_user_id(request.args.get('user_id', type=int), data)
        text_only = request.args.get('text_only', type=bool) or data.get('text_only', False)

        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        shop = Shop.query.filter(
            Shop.id == shop_id,
            Shop.is_active.is_(True),
        ).first()
        if not shop:
            return jsonify({
                'success': False,
                'message': 'Shop not found or unavailable'
            }), 404

        existing_follow = UserFollowShop.query.filter_by(
            user_id=user_id,
            shop_id=shop_id
        ).first()

        if existing_follow:
            # Already following - unfollow it (toggle off)
            db.session.delete(existing_follow)
            db.session.commit()

            if _is_htmx_request():
                if request.args.get('wishlist', '').lower() in ('1', 'true', 'yes'):
                    return '', 200
                if text_only:
                    return 'Follow', 200
                return _render_shop_favorite_button(shop_id=shop_id, is_favorited=False), 200

            return jsonify({
                'success': True,
                'message': f'Removed {shop.name} from favorites',
                'is_favorited': False,
            }), 200
        else:
            # Not following - follow it (toggle on)
            follow = UserFollowShop(
                user_id=user_id,
                shop_id=shop_id
            )
            db.session.add(follow)
            _notify_shop_owner_and_admins_for_favorite(user=user, shop=shop, product=None)
            db.session.commit()

            if _is_htmx_request():
                if text_only:
                    return 'Following', 200
                return _render_shop_favorite_button(shop_id=shop_id, is_favorited=True), 200

            return jsonify({
                'success': True,
                'message': f'Added {shop.name} to favorites',
                'follow': follow.to_dict(),
                'is_favorited': True,
            }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error toggling shop follow',
            'error': str(e)
        }), 500

@buyer_bp.route("/shops/following")
@buyer_bp.route("/shops/favorites")
def get_followed_shops():
    """Get all shops that the user has favorited."""
    try:
        user_id = _resolve_user_id(request.args.get('user_id', type=int))

        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        follows = UserFollowShop.query.filter_by(user_id=user_id).order_by(
            UserFollowShop.followed_at.desc()
        ).all()

        shops = []
        for follow in follows:
            shop = Shop.query.get(follow.shop_id)
            if shop and shop.is_active:
                shop_dict = {
                    'id': shop.id,
                    'name': shop.name,
                    'description': shop.description,
                    'address': shop.address,
                    'phone': shop.phone,
                    'email': shop.email,
                    'image_urls': shop.image_urls,
                    'primary_image_url': shop.primary_image_url,
                    'followed_at': follow.followed_at.isoformat() if follow.followed_at else None
                }
                shops.append(shop_dict)
        
        return jsonify({
            'success': True,
            'user_id': user.id,
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
@buyer_bp.route("/shops/<int:shop_id>/is-favorited")
def check_following_status(shop_id):
    """Check if user has favorited a specific shop."""
    try:
        user_id = _resolve_user_id(request.args.get('user_id', type=int))

        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        follow = UserFollowShop.query.filter_by(
            user_id=user_id,
            shop_id=shop_id
        ).first()

        return jsonify({
            'success': True,
            'user_id': user.id,
            'is_following': follow is not None,
            'is_favorited': follow is not None,
            'followed_at': follow.followed_at.isoformat() if follow and follow.followed_at else None
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error checking follow status',
            'error': str(e)
        }), 500


@buyer_bp.route("/products/<int:product_id>/favorite", methods=["POST"])
def favorite_product(product_id):
    """Toggle product favorite status - adds if not favorited, removes if favorited."""
    try:
        data = _request_json()
        user_id = _resolve_user_id(request.args.get('user_id', type=int), data)
        product_detail = request.args.get('product_detail', type=bool) or data.get('product_detail', False)

        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        product = Product.query.join(Shop).filter(
            Product.id == product_id,
            Product.is_active.is_(True),
            Shop.is_active.is_(True),
        ).first()
        if not product:
            return jsonify({
                'success': False,
                'message': 'Product not found or unavailable'
            }), 404

        existing_favorite = UserFavoriteProduct.query.filter_by(
            user_id=user_id,
            product_id=product_id,
        ).first()
        
        if existing_favorite:
            # Already favorited - unfavorite it (toggle off)
            db.session.delete(existing_favorite)
            db.session.commit()
            
            if _is_htmx_request():
                if request.args.get('wishlist', '').lower() in ('1', 'true', 'yes'):
                    return '', 200
                return _render_product_favorite_button(product_id=product_id, is_favorited=False, product_detail=product_detail), 200
            print(f'Removed "{product.name}" from favorites')
            return jsonify({
                'success': True,
                'message': f'Removed "{product.name}" from favorites',
                'is_favorited': False,
            }), 200
        else:
            # Not favorited - favorite it (toggle on)
            favorite = UserFavoriteProduct(user_id=user_id, product_id=product_id)
            db.session.add(favorite)
            _notify_shop_owner_and_admins_for_favorite(
                user=user,
                shop=product.shop,
                product=product,
            )
            db.session.commit()

            if _is_htmx_request():
                return _render_product_favorite_button(product_id=product_id, is_favorited=True, product_detail=product_detail), 200

            return jsonify({
                'success': True,
                'message': f'Added "{product.name}" to favorites',
                'favorite': favorite.to_dict(),
                'is_favorited': True,
            }), 201

    except Exception as e:
        db.session.rollback()
        print(e)
        return jsonify({
            'success': False,
            'message': 'Error adding product to favorites',
            'error': str(e)
        }), 500


@buyer_bp.route("/products/<int:product_id>/favorite", methods=["DELETE"])
def unfavorite_product(product_id):
    """Remove a product from buyer favorites."""
    try:
        data = _request_json()
        user_id = _resolve_user_id(request.args.get('user_id', type=int), data)

        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        favorite = UserFavoriteProduct.query.filter_by(
            user_id=user_id,
            product_id=product_id,
        ).first()
        if not favorite:
            if _is_htmx_request():
                return _render_product_favorite_button(product_id=product_id, is_favorited=False, product_detail=True), 200
            return jsonify({
                'success': False,
                'message': 'Product is not in favorites'
            }), 404

        db.session.delete(favorite)
        db.session.commit()

        if _is_htmx_request():
            return _render_product_favorite_button(product_id=product_id, is_favorited=False, product_detail=True), 200

        return jsonify({
            'success': True,
            'message': f'Removed product from favorites for {user.username}'
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error removing product from favorites',
            'error': str(e)
        }), 500


@buyer_bp.route("/products/favorites")
def get_favorite_products():
    """List buyer favorite products."""
    try:
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        favorites = UserFavoriteProduct.query.filter_by(user_id=user_id).order_by(
            UserFavoriteProduct.favorited_at.desc()
        ).all()

        products = []
        for favorite in favorites:
            product = Product.query.get(favorite.product_id)
            if not product or not product.is_active:
                continue
            shop = product.shop
            if not shop or not shop.is_active:
                continue
            products.append({
                'favorite_id': favorite.id,
                'favorited_at': favorite.favorited_at.isoformat() if favorite.favorited_at else None,
                'product': {
                    'id': product.id,
                    'name': product.name,
                    'price': product.price,
                    'stock': product.stock,
                    'shop_id': shop.id,
                    'shop_name': shop.name,
                    'image_urls': product.image_urls,
                    'primary_image_url': product.primary_image_url,
                }
            })

        return jsonify({
            'success': True,
            'user_id': user.id,
            'count': len(products),
            'products': products
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching favorite products',
            'error': str(e)
        }), 500


@buyer_bp.route("/products/<int:product_id>/is-favorited")
def check_product_favorite_status(product_id):
    """Check whether buyer has favorited a product."""
    try:
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        favorite = UserFavoriteProduct.query.filter_by(
            user_id=user_id,
            product_id=product_id,
        ).first()

        return jsonify({
            'success': True,
            'user_id': user.id,
            'is_favorited': favorite is not None,
            'favorited_at': favorite.favorited_at.isoformat() if favorite and favorite.favorited_at else None,
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error checking product favorite status',
            'error': str(e)
        }), 500


@buyer_bp.route("/notifications")
def buyer_notifications():
    """Get notifications for a buyer."""
    try:
        user_id = _resolve_user_id(request.args.get('user_id', type=int))
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        unread_only = request.args.get('unread_only', '').lower() in ('1', 'true', 'yes')
        limit = request.args.get('limit', 20, type=int)
        limit = min(max(limit, 1), 100)

        query = Notification.query.filter_by(recipient_user_id=user.id)
        if unread_only:
            query = query.filter_by(is_read=False)

        notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()
        unread_count = Notification.query.filter_by(
            recipient_user_id=user.id,
            is_read=False,
        ).count()

        return jsonify({
            'success': True,
            'user_id': user.id,
            'count': len(notifications),
            'unread_count': unread_count,
            'notifications': [notification.to_dict() for notification in notifications],
        }), 200

    except Exception as e:
        return jsonify({
            'success': False,
            'message': 'Error fetching notifications',
            'error': str(e)
        }), 500


@buyer_bp.route("/notifications/<int:notification_id>/read", methods=["PATCH"])
def mark_buyer_notification_read(notification_id):
    """Mark one buyer notification as read."""
    try:
        data = _request_json()
        user_id = _resolve_user_id(request.args.get('user_id', type=int), data)
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        notification = Notification.query.filter_by(
            id=notification_id,
            recipient_user_id=user.id,
        ).first()
        if not notification:
            return jsonify({
                'success': False,
                'message': 'Notification not found'
            }), 404

        if not notification.is_read:
            notification.mark_read()
            db.session.commit()

        return jsonify({
            'success': True,
            'notification': notification.to_dict(),
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error marking notification as read',
            'error': str(e)
        }), 500


@buyer_bp.route("/notifications/read-all", methods=["POST"])
def mark_all_buyer_notifications_read():
    """Mark all buyer notifications as read."""
    try:
        data = _request_json()
        user_id = _resolve_user_id(request.args.get('user_id', type=int), data)
        if not user_id:
            return jsonify({
                'success': False,
                'message': 'User ID is required'
            }), 400

        user, error_response = _load_buyer_user(user_id)
        if error_response:
            return error_response

        notifications = Notification.query.filter_by(
            recipient_user_id=user.id,
            is_read=False,
        ).all()

        for notification in notifications:
            notification.mark_read()

        db.session.commit()
        return jsonify({
            'success': True,
            'updated': len(notifications),
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': 'Error marking notifications as read',
            'error': str(e)
        }), 500

