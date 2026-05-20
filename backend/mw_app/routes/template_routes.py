# Template routes for HTMX frontend
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, make_response, jsonify
from sqlalchemy import func, or_, nullslast
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from flask_login import login_user, current_user, logout_user
from urllib.parse import quote_plus
from werkzeug.utils import secure_filename
from ..forms import LoginForm, RegistrationForm
from ..utils.location import get_user_location, haversine_distance_expr, NEAR_YOU_KM
from ..models import (
    Category,
    Product,
    Shop,
    StockUpdate,
    UserFollowShop,
    UserFavoriteProduct,
    UserBrowsingHistory,
    Notification,
    User,
    USER_ROLE_BUYER,
    USER_ROLE_SELLER,
    USER_ROLE_ADMIN,
    CATEGORY_LEVEL_LEAF,
)
from ..extensions import oauth, db
import secrets
from functools import wraps

main_bp = Blueprint('main_bp', __name__)
auth_bp = Blueprint('auth_template_bp', __name__, url_prefix='/auth')
seller_bp = Blueprint('seller_template_bp', __name__, url_prefix='/seller')
buyer_bp = Blueprint('buyer_template_bp', __name__, url_prefix='/buyer')
admin_bp = Blueprint('admin_template_bp', __name__, url_prefix='/admin')

DEFAULT_SHOP_PLACEHOLDER_IMAGE = '/static/images/mw_logo_trans.png'
ALLOWED_SHOP_IMAGE_EXTENSIONS = {
    '.jpg',
    '.jpeg',
    '.png',
    '.webp',
}


def login_required(func):
    """Overwrites the flask_login's login_required"""
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            next_link = request.url
            flash('A quick login is required first.', 'info')
            return redirect(url_for('login', next=next_link))
        return func(*args, **kwargs)
    return decorated_view

def admin_required(func):
    """Decorator to ensure the user is an admin (Session based)"""
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not (current_user.is_authenticated and current_user.can_access_admin()):
            flash('Admin access is required for that page.', 'error')
            return redirect(url_for('main_bp.index'))
        return func(*args, **kwargs)
    return decorated_view


def _simple_datetime_label(value):
    if not value:
        return None
    return f"{value.strftime('%b')} {value.day}, {value.year} {value.strftime('%I:%M %p').lstrip('0')}"


def _time_ago(value):
    if not value:
        return "Just now"

    now = datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    delta = now - value
    seconds = max(int(delta.total_seconds()), 0)
    if seconds < 60:
        return "Just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    return f"{days // 365}y ago"


def _timestamp_or_zero(value):
    if not value:
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _notification_icon(notification):
    payload = notification.get_payload() or {}
    if payload.get('icon'):
        return payload['icon']

    notification_type = notification.notification_type or ''
    if 'support' in notification_type:
        return 'support'
    if 'shop' in notification_type:
        return 'shop'
    if 'product' in notification_type or 'stock' in notification_type:
        return 'product'
    if 'user' in notification_type:
        return 'user'
    return 'system'


def _bootstrap_icon_name(icon):
    return {
        'support': 'headset',
        'product': 'box-seam',
        'system': 'bell',
        'user': 'person',
    }.get(icon, icon)


def _notification_action_url(notification):
    payload = notification.get_payload() or {}
    if payload.get('action_url'):
        return payload['action_url']
    if payload.get('conversation_id') and 'support' in (notification.notification_type or ''):
        if current_user.is_authenticated and current_user.role == USER_ROLE_ADMIN:
            return url_for('support_bp.admin_support_chat', id=payload['conversation_id'])
        return url_for('support_bp.my_support_chat', id=payload['conversation_id'])
    return None


def _notification_to_dict(notification):
    data = notification.to_dict()
    data.update({
        'icon': _notification_icon(notification),
        'action_url': _notification_action_url(notification),
        'created_at_label': _simple_datetime_label(notification.created_at),
    })
    return data


def _normalize_gps(gps_value):
    """Validate and normalize GPS coordinate string in 'lat,lng' format."""
    if not gps_value:
        return None

    parts = [part.strip() for part in str(gps_value).split(',')]
    if len(parts) != 2:
        return None

    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError:
        return None

    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None

    return f"{lat:.6f},{lng:.6f}"


def _build_shop_map_embed_url(shop):
    gps = _normalize_gps(shop.gps)
    if gps:
        return f"https://maps.google.com/maps?q={quote_plus(gps)}&z=15&output=embed"

    fallback_query = ", ".join(
        [item for item in [shop.address, shop.town, shop.region, "Ghana"] if item]
    ).strip(", ")
    if fallback_query:
        return f"https://maps.google.com/maps?q={quote_plus(fallback_query)}&z=14&output=embed"

    return None


def _infer_image_suffix(file_storage):
    filename = secure_filename(file_storage.filename or '')
    suffix = Path(filename).suffix.lower()
    if suffix in ALLOWED_SHOP_IMAGE_EXTENSIONS:
        return suffix

    mime_to_suffix = {
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/webp': '.webp',
    }
    return mime_to_suffix.get(file_storage.mimetype or '')


def _store_shop_front_image(file_storage, shop_id):
    suffix = _infer_image_suffix(file_storage)
    if not suffix:
        raise ValueError('Upload a JPG, PNG, or WEBP image.')

    upload_dir = Path(current_app.static_folder) / 'uploads' / 'shops'
    upload_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"shop-{shop_id}-{uuid4().hex}{suffix}"
    file_storage.save(upload_dir / stored_name)
    return url_for('static', filename=f'uploads/shops/{stored_name}')


def _build_shop_directions_url(shop):
    gps = _normalize_gps(shop.gps)
    if gps:
        return f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(gps)}"

    fallback_query = ", ".join(
        [item for item in [shop.address, shop.town, shop.region, "Ghana"] if item]
    ).strip(", ")
    if fallback_query:
        return f"https://www.google.com/maps/dir/?api=1&destination={quote_plus(fallback_query)}"

    return None


def _resolve_user_shop(user):
    shops = _resolve_user_shops(user)
    return shops[0] if shops else None


def _resolve_user_shops(user):
    if not user:
        return []

    shops = getattr(user, 'owned_shops', None)
    if isinstance(shops, list):
        def sort_key(item):
            value = item.last_updated or item.created_at or datetime.min
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value

        return sorted(
            shops,
            key=sort_key,
            reverse=True,
        )

    single_shop = shops or getattr(user, 'shop', None)
    return [single_shop] if single_shop else []


def _resolve_owned_shop(user, shop_id=None, allow_default=False):
    shops = _resolve_user_shops(user)
    if not shops:
        return None

    if shop_id is None:
        if allow_default:
            return shops[0]
        return None

    for shop in shops:
        if shop.id == shop_id:
            return shop
    return None


def _seller_guard_redirect():
    if not current_user.is_authenticated:
        flash('Please sign in to manage your seller account.', 'warning')
        return redirect(url_for('main_bp.login'))
    if current_user.role != USER_ROLE_SELLER:
        flash('Seller access is required for that page.', 'error')
        return redirect(url_for('main_bp.index'))
    return None


def _build_shop_payload(shop):
    if not shop:
        return None

    return {
        'id': shop.id,
        'name': shop.name,
        'description': shop.description,
        'phone': shop.phone,
        'email': shop.email,
        'address': shop.address,
        'region': shop.region,
        'district': shop.district,
        'town': shop.town,
        'gps': shop.gps,
        'is_active': bool(shop.is_active),
        'image_urls': shop.image_urls,
        'primary_image_url': shop.primary_image_url,
        'verification_status': shop.verification_status,
        'phone_verified': bool(shop.phone_verified),
        'email_verified': bool(shop.email_verified),
        'can_request_verification': bool(shop.can_request_verification()),
    }


def _shop_has_custom_image(shop):
    if not shop:
        return False
    return any(
        image_url and image_url != DEFAULT_SHOP_PLACEHOLDER_IMAGE
        for image_url in shop.image_urls
    )


def _build_shop_setup_state(shop):
    step_order = ['basic', 'image', 'contact', 'description']

    state = {
        'basic_complete': bool(shop and shop.name and _normalize_gps(shop.gps) and (shop.address or '').strip()),
        'image_complete': _shop_has_custom_image(shop),
        'contact_complete': bool(shop and (shop.phone or shop.email)),
        'description_complete': bool(shop and (shop.description or '').strip()),
    }
    state['completed_count'] = sum(1 for step in step_order if state[f'{step}_complete'])

    next_step = 'complete'
    for step in step_order:
        if not state[f'{step}_complete']:
            next_step = step
            break
    state['active_step'] = next_step
    return state


def _next_shop_setup_step(setup_state):
    return setup_state.get('active_step', 'basic')


def _build_shop_feedback_response(message, tone='success', trigger_payload=None):
    response = make_response(
        render_template(
            'seller/partials/shop_setup_feedback.html',
            message=message,
            tone=tone,
        )
    )
    if trigger_payload:
        response.headers['HX-Trigger'] = json.dumps(trigger_payload)
    return response


def _build_shop_setup_success(step, message, shop):
    setup_state = _build_shop_setup_state(shop)
    return _build_shop_feedback_response(
        message=message,
        tone='success',
        trigger_payload={
            'shop-step-saved': {
                'step': step,
                'nextStep': _next_shop_setup_step(setup_state),
                'setupState': setup_state,
                'shop': _build_shop_payload(shop),
            }
        },
    )


def _load_shop_categories(shop_id):
    return (
        db.session.query(Category)
        .join(Product, Product.category_id == Category.id)
        .filter(
            Product.shop_id == shop_id,
            Product.is_active.is_(True),
        )
        .distinct()
        .order_by(Category.name.asc())
        .all()
    )


def _requested_shop_id():
    return request.values.get('shop_id', type=int)


def _serialize_template_product(product):
    return {
        'id': product.id,
        'name': product.name,
        'code': product.code,
        'type_': product.type_,
        'description': product.description,
        'tags': product.tags,
        'price': float(product.price or 0),
        'stock': product.stock,
        'category_id': product.category_id,
        'category_name': product.category.name if product.category else None,
        'is_active': product.is_active,
        'image_urls': product.image_urls,
        'primary_image_url': product.primary_image_url,
        'updated_at': product.updated_at.isoformat() if product.updated_at else None,
    }

# Public pages
@main_bp.route('/')
def index():
    """Homepage - marketplace overview"""
    try:
        from ..services.analytics_service import track_event
        track_event('homepage_visit', user=current_user)
    except Exception:
        pass
    # Resolve user location for proximity-aware sorting
    user_lat, user_lng = get_user_location(current_user)
    dist_expr = haversine_distance_expr(user_lat, user_lng) if user_lat is not None else None
    user_has_location = user_lat is not None

    active_shops_q = Shop.query.filter(Shop.is_active.is_(True))

    if dist_expr is not None:
        featured_shops = active_shops_q.order_by(
            nullslast(dist_expr.asc()),
            Shop.promoted.desc(),
            Shop.last_updated.desc(),
        ).limit(6).all()
    else:
        featured_shops = active_shops_q.order_by(
            Shop.promoted.desc(),
            Shop.last_updated.desc(),
        ).limit(6).all()

    products_q = Product.query.join(Shop).filter(
        Product.is_active.is_(True),
        Shop.is_active.is_(True),
    )

    if dist_expr is not None:
        products_q = products_q.add_columns(dist_expr.label('distance_km'))
        raw_products = products_q.order_by(
            nullslast(dist_expr.asc()),
            Product.created_at.desc(),
        ).limit(12).all()
        featured_products = []
        for product, dist_km in raw_products:
            product._distance_km = dist_km
            product._near_you = (dist_km is not None and dist_km <= NEAR_YOU_KM)
            featured_products.append(product)
    else:
        featured_products = products_q.order_by(
            Product.created_at.desc(),
        ).limit(12).all()
        for product in featured_products:
            product._distance_km = None
            product._near_you = False

    category_rows = db.session.query(
        Category.id,
        Category.name,
        func.count(Product.id).label("product_count"),
    ).outerjoin(
        Product, Product.category_id == Category.id
    ).group_by(
        Category.id, Category.name
    ).order_by(
        func.count(Product.id).desc(), Category.name.asc()
    ).limit(12).all()

    # Fetch personalized grids for the homepage
    from ..services.personalization_service import (
        get_trending_products,
        get_personalized_products,
        get_fresh_listings
    )

    trending_products = get_trending_products(limit=12, user_lat=user_lat, user_lng=user_lng)
    personalized_products = get_personalized_products(current_user, limit=12)
    fresh_products = get_fresh_listings(limit=12, user_lat=user_lat, user_lng=user_lng)
    
    followed_shop_products = []
    continue_browsing_products = []
    
    if current_user.is_authenticated:
        # From followed shops
        followed_shops = UserFollowShop.query.filter_by(user_id=current_user.id).all()
        shop_ids = [f.shop_id for f in followed_shops]
        if shop_ids:
            followed_shop_products = Product.query.join(Shop).filter(
                Product.shop_id.in_(shop_ids),
                Product.is_active.is_(True),
                Shop.is_active.is_(True)
            ).order_by(Product.created_at.desc()).limit(12).all()
            
        # Continue browsing (recently viewed)
        browsing_history = UserBrowsingHistory.query.filter_by(user_id=current_user.id).order_by(UserBrowsingHistory.viewed_at.desc()).limit(12).all()
        seen_bh_ids = set()
        for bh in browsing_history:
            if bh.product_id and bh.product_id not in seen_bh_ids:
                if bh.product and bh.product.is_active and bh.product.shop.is_active:
                    continue_browsing_products.append(bh.product)
                    seen_bh_ids.add(bh.product_id)

    return render_template(
        'public/index.html',
        featured_shops=featured_shops,
        featured_products=featured_products,
        trending_products=trending_products,
        personalized_products=personalized_products,
        fresh_products=fresh_products,
        followed_shop_products=followed_shop_products,
        continue_browsing_products=continue_browsing_products,
        top_categories=category_rows,
        user_has_location=user_has_location,
    )

@main_bp.route('/login')
def login():
    """Login page"""
    form = LoginForm()
    return render_template('auth/login.html', form=form)

@main_bp.route('/register')
def register():
    """Registration page"""
    form = RegistrationForm()
    return render_template('auth/register.html', form=form)

@main_bp.route('/shops')
def shops():
    """Browse shops page"""
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()
    return render_template('buyer/shops.html', categories=categories)


@main_bp.route('/shops/add')
@login_required
def add_shop():
    """Public shop onboarding page for any authenticated user."""
    requested_shop_id = request.args.get('shop_id', type=int)
    create_new = request.args.get('new', '').lower() in {'1', 'true', 'yes', 'on'}
    shop = None if create_new else _resolve_owned_shop(current_user, requested_shop_id, allow_default=True)
    map_embed_url = _build_shop_map_embed_url(shop) if shop else None
    shop_payload = _build_shop_payload(shop)
    setup_state = _build_shop_setup_state(shop)

    return render_template(
        'seller/shop.html',
        seller_id=current_user.id,
        shop=shop,
        shop_payload=shop_payload,
        map_embed_url=map_embed_url,
        setup_state=setup_state,
        onboarding_mode=True,
    )


@main_bp.route('/shops/<int:shop_id>')
def shop_detail(shop_id):
    """Public shop detail page with location and product listing."""
    shop = Shop.query.filter(
        Shop.id == shop_id,
        Shop.is_active.is_(True),
    ).first_or_404()

    map_embed_url = _build_shop_map_embed_url(shop)
    directions_url = _build_shop_directions_url(shop)
    child_categories = _load_shop_categories(shop.id)
    shop_is_favorited = False
    if current_user.is_authenticated:
        shop_is_favorited = UserFollowShop.query.filter_by(
            user_id=current_user.id,
            shop_id=shop.id,
        ).first() is not None

    # Fetch other active shops near user/this shop
    user_lat, user_lng = get_user_location(current_user)
    lat, lng = user_lat, user_lng
    if lat is None and shop.gps:
        from ..services.personalization_service import parse_gps
        lat, lng = parse_gps(shop.gps)

    more_shops_query = Shop.query.filter(
        Shop.is_active.is_(True),
        Shop.id != shop.id
    )

    if lat is not None and lng is not None:
        from sqlalchemy import nullslast
        dist_expr = haversine_distance_expr(lat, lng)
        more_shops_query = more_shops_query.order_by(nullslast(dist_expr.asc()))
        more_shops = more_shops_query.limit(4).all()
        # Annotate distance
        for s in more_shops:
            s_lat, s_lng = None, None
            if s.gps:
                from ..services.personalization_service import parse_gps
                s_lat, s_lng = parse_gps(s.gps)
            if s_lat is not None and s_lng is not None:
                from ..services.personalization_service import haversine_distance
                s._distance_km = haversine_distance(lat, lng, s_lat, s_lng)
                s._near_you = (s._distance_km <= NEAR_YOU_KM)
    else:
        more_shops = more_shops_query.order_by(Shop.name.asc()).limit(4).all()

    return render_template(
        'buyer/shop_detail.html',
        shop=shop,
        map_embed_url=map_embed_url,
        directions_url=directions_url,
        shop_categories=child_categories,
        shop_is_favorited=shop_is_favorited,
        more_shops=more_shops,
    )


@seller_bp.route('/shop/preview')
@login_required
def seller_shop_preview():
    """Preview the current seller shop using the buyer-facing layout."""
    shop = _resolve_owned_shop(current_user, request.args.get('shop_id', type=int), allow_default=True)
    if not shop:
        flash('Create your shop details first before previewing it.', 'warning')
        return redirect(url_for('main_bp.add_shop'))

    map_embed_url = _build_shop_map_embed_url(shop)
    directions_url = _build_shop_directions_url(shop)
    child_categories = _load_shop_categories(shop.id)

    return render_template(
        'buyer/shop_detail.html',
        shop=shop,
        map_embed_url=map_embed_url,
        directions_url=directions_url,
        shop_categories=child_categories,
        shop_is_favorited=False,
    )

@main_bp.route('/products')
def products():
    """Browse products page"""
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()
    return render_template('buyer/products.html', categories=categories)

@main_bp.route('/notifications')
@login_required
def notifications():
    """Notifications page for all user types"""
    notifications = Notification.query.filter_by(
        recipient_user_id=current_user.id,
    ).order_by(Notification.created_at.desc()).limit(100).all()
    
    notifications_data = [_notification_to_dict(n) for n in notifications]
    return render_template('public/notifications.html', notifications=notifications_data)


@main_bp.route('/notifications/feed')
@login_required
def notification_feed():
    """Return the current user's personal notification list for the bell menu."""
    limit = min(max(request.args.get('limit', 8, type=int), 1), 30)
    notifications = Notification.query.filter_by(
        recipient_user_id=current_user.id,
    ).order_by(Notification.created_at.desc()).limit(limit).all()
    unread_count = Notification.query.filter_by(
        recipient_user_id=current_user.id,
        is_read=False,
    ).count()

    return jsonify({
        'success': True,
        'unread_count': unread_count,
        'notifications': [_notification_to_dict(notification) for notification in notifications],
    })


@main_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Mark one notification read for the current user."""
    notification = Notification.query.filter_by(
        id=notification_id,
        recipient_user_id=current_user.id,
    ).first_or_404()

    if not notification.is_read:
        notification.mark_read()
        db.session.commit()

    return jsonify({
        'success': True,
        'notification': _notification_to_dict(notification),
    })


@main_bp.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_notifications_read():
    """Mark the current user's personal notifications read."""
    notifications = Notification.query.filter_by(
        recipient_user_id=current_user.id,
        is_read=False,
    ).all()

    for notification in notifications:
        notification.mark_read()

    db.session.commit()
    return jsonify({
        'success': True,
        'updated': len(notifications),
    })

@main_bp.route('/notifications/<int:notification_id>', methods=['DELETE'])
@login_required
def delete_notification(notification_id):
    """Delete one notification for the current user."""
    notification = Notification.query.filter_by(
        id=notification_id,
        recipient_user_id=current_user.id,
    ).first_or_404()

    db.session.delete(notification)
    db.session.commit()

    return jsonify({'success': True})

@main_bp.route('/notifications/clear-all', methods=['DELETE'])
@login_required
def clear_all_notifications():
    """Delete all notifications for the current user."""
    Notification.query.filter_by(
        recipient_user_id=current_user.id,
    ).delete()
    db.session.commit()
    
    return jsonify({'success': True})

@main_bp.route('/categories')
def categories():
    """Browse categories page"""
    search_term = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', 'name')
    with_products = request.args.get('with_products', '').lower() in ('1', 'true', 'yes', 'on')
    selected_category_id = request.args.get('category_id', type=int)

    parent_category = aliased(Category)

    categories_data = db.session.query(
        Category.id,
        Category.name,
        Category.description,
        Category.level,
        Category.parent_id,
        parent_category.name.label("parent_name"),
        func.count(Product.id).label("product_count"),
    ).outerjoin(
        Product, Product.category_id == Category.id
    ).outerjoin(
        parent_category, Category.parent_id == parent_category.id
    ).group_by(
        Category.id, Category.name, Category.description, Category.level, Category.parent_id, parent_category.name
    )

    if search_term:
        categories_data = categories_data.filter(
            or_(
                Category.name.ilike(f'%{search_term}%'),
                Category.description.ilike(f'%{search_term}%'),
                parent_category.name.ilike(f'%{search_term}%'),
            )
        )

    if with_products:
        categories_data = categories_data.having(func.count(Product.id) > 0)

    if sort_by == 'product_count_desc':
        categories_data = categories_data.order_by(func.count(Product.id).desc(), Category.name.asc())
    elif sort_by == 'product_count_asc':
        categories_data = categories_data.order_by(func.count(Product.id).asc(), Category.name.asc())
    else:
        categories_data = categories_data.order_by(Category.name.asc())

    selected_category = None
    selected_children = []
    if selected_category_id:
        selected_category = Category.query.filter_by(id=selected_category_id, is_active=True).first()
        if selected_category:
            selected_children = Category.query.filter_by(
                parent_id=selected_category.id,
                is_active=True
            ).order_by(Category.name.asc()).all()

    if request.headers.get('HX-Request') == 'true':
        return render_template(
            'public/partials/category_cards.html',
            categories=categories_data.all(),
        )

    return render_template(
        'public/categories.html',
        categories=categories_data.all(),
        search_term=search_term,
        sort_by=sort_by,
        with_products=with_products,
        selected_category=selected_category,
        selected_children=selected_children,
    )

@main_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page"""
    from datetime import datetime, timedelta

    def cleaned_value(field_name):
        value = request.form.get(field_name, '')
        value = value.strip() if isinstance(value, str) else ''
        return value or None
    
    if request.method == 'POST':
        try:
            # Update user profile fields
            current_user.first_name = cleaned_value('first_name')
            current_user.last_name = cleaned_value('last_name')
            current_user.phone = cleaned_value('phone')
            current_user.region = cleaned_value('region')
            current_user.district = cleaned_value('district')
            current_user.town = cleaned_value('town')
            current_user.address = cleaned_value('address')
            
            # Update timestamp
            current_user.updated_at = datetime.now()
            
            # Commit changes to database
            db.session.commit()
            
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('main_bp.profile'))
            
        except IntegrityError:
            db.session.rollback()
            flash('That phone number is already in use by another account.', 'error')

        except Exception as e:
            db.session.rollback()
            flash('Error updating profile. Please try again.', 'error')
            print(f"Profile update error: {e}")
    
    # Calculate membership duration
    if current_user.created_at:
        days_since_creation = (datetime.now() - current_user.created_at.replace(tzinfo=None)).days
        if days_since_creation < 30:
            member_duration = f"{days_since_creation}d"
        elif days_since_creation < 365:
            member_duration = f"{days_since_creation // 30}m"
        else:
            member_duration = f"{days_since_creation // 365}y"
    else:
        member_duration = "New"

    owned_shops = _resolve_user_shops(current_user)
    favorite_rows = UserFavoriteProduct.query.filter_by(
        user_id=current_user.id,
    ).order_by(UserFavoriteProduct.favorited_at.desc()).limit(5).all()
    followed_rows = UserFollowShop.query.filter_by(
        user_id=current_user.id,
    ).order_by(UserFollowShop.followed_at.desc()).limit(5).all()
    recent_notifications = Notification.query.filter_by(
        recipient_user_id=current_user.id,
    ).order_by(Notification.created_at.desc()).limit(5).all()

    favorites_count = UserFavoriteProduct.query.filter_by(user_id=current_user.id).count()
    following_count = UserFollowShop.query.filter_by(user_id=current_user.id).count()
    unread_count = Notification.query.filter_by(
        recipient_user_id=current_user.id,
        is_read=False,
    ).count()

    user_stats = {
        'shops_count': len(owned_shops),
        'favorites_count': favorites_count,
        'following_count': following_count,
        'unread_count': unread_count,
        'member_since': current_user.created_at,
        'member_duration': member_duration,
    }

    recent_activity = []
    for notification in recent_notifications:
        recent_activity.append({
            'title': notification.title,
            'description': notification.message,
            'time_ago': _time_ago(notification.created_at),
            'icon': _bootstrap_icon_name(_notification_icon(notification)),
            'color': 'info' if not notification.is_read else 'secondary',
            'url': _notification_action_url(notification),
            'sort_at': _timestamp_or_zero(notification.created_at),
        })

    for favorite in favorite_rows:
        recent_activity.append({
            'title': 'Saved Product',
            'description': favorite.product.name if favorite.product else 'A product was saved',
            'time_ago': _time_ago(favorite.favorited_at),
            'icon': 'heart',
            'color': 'warning',
            'url': url_for('buyer_template_bp.wishlist'),
            'sort_at': _timestamp_or_zero(favorite.favorited_at),
        })

    for follow in followed_rows:
        recent_activity.append({
            'title': 'Followed Shop',
            'description': follow.shop.name if follow.shop else 'A shop was followed',
            'time_ago': _time_ago(follow.followed_at),
            'icon': 'shop',
            'color': 'primary',
            'url': url_for('buyer_template_bp.wishlist'),
            'sort_at': _timestamp_or_zero(follow.followed_at),
        })

    for shop in owned_shops[:3]:
        recent_activity.append({
            'title': 'Shop Updated',
            'description': shop.name,
            'time_ago': _time_ago(shop.last_updated or shop.created_at),
            'icon': 'shop-window',
            'color': 'success',
            'url': url_for('seller_template_bp.seller_shop', shop_id=shop.id),
            'sort_at': _timestamp_or_zero(shop.last_updated or shop.created_at),
        })

    recent_activity = sorted(
        recent_activity,
        key=lambda item: item.get('sort_at', 0),
        reverse=True,
    )[:8]
    
    return render_template('public/profile.html', 
                         user_stats=user_stats,
                         recent_activity=recent_activity,
                         owned_shops=owned_shops)

@auth_bp.route('/register', methods=['POST'])
def register_post():
    """Handle registration - returns redirect or error"""
    form = RegistrationForm()
    if form.validate_on_submit():
        # TODO: Implement actual registration logic
        flash('Registration functionality coming soon!', 'info')
        return redirect(url_for('main_bp.login'))
    
    if request.headers.get('HX-Request'):
        return render_template('auth/register.html', form=form)
    return redirect(url_for('main_bp.register'))

@auth_bp.route('/logout')
def logout():
    """Logout user"""
    logout_user()
    flash('You have been logged out successfully.', 'success')
    return redirect(url_for('main_bp.index'))

###################################
####################################
@main_bp.route('/oauth/login')
def oauth_login():
    redirect_uri = url_for('main_bp.oauth_authorize', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@main_bp.route('/oauth/authorize')
def oauth_authorize():
    try:
        # 1. Exchange code for token
        token = oauth.google.authorize_access_token()

        # 2. Fetch user info (prefer endpoint from metadata, fallback to Google OIDC URL)
        user_info = token.get('userinfo')
        if not user_info:
            userinfo_url = 'https://openidconnect.googleapis.com/v1/userinfo'
            try:
                metadata = oauth.google.load_server_metadata()
                userinfo_url = metadata.get('userinfo_endpoint', userinfo_url)
            except Exception:
                pass

            resp = oauth.google.get(userinfo_url)
            if resp.ok:
                user_info = resp.json()

        if not user_info:
            flash('Failed to get user information from Google', 'error')
            return redirect(url_for('main_bp.login'))

        email = user_info.get('email')
        first_name = user_info.get('given_name', '')
        last_name = user_info.get('family_name', '')

        if not email:
            flash('Email is required from Google account', 'error')
            return redirect(url_for('main_bp.login'))

        # 3. Find or create user
        user = User.query.filter_by(email=email).first()

        if user:
            login_user(user)
            from ..services.analytics_service import track_event
            track_event('login', user)
            flash(f"Welcome back, {user.first_name or user.username}!", "success")
        else:
            username = email.split('@')[0]
            counter = 1
            base = username
            while User.query.filter_by(username=username).first():
                username = f"{base}{counter}"
                counter += 1

            user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                role=USER_ROLE_BUYER,
                status='active'
            )
            user.set_password(secrets.token_urlsafe(16))

            db.session.add(user)
            db.session.commit()

            login_user(user)
            from ..services.analytics_service import track_event
            track_event('signup', user)
            flash(f"Welcome to Market Window, {user.first_name or user.username}!", "success")

        # 4. Redirect
        if user.role == 'admin':
            return redirect(url_for('admin_template_bp.admin_dashboard'))
        elif user.role == 'seller':
            return redirect(url_for('seller_template_bp.seller_dashboard'))
        return redirect(url_for('main_bp.index'))

    except Exception as e:
        flash('Authentication failed', 'error')
        current_app.logger.exception(e)
        return redirect(url_for('main_bp.login'))

# Seller template routes
@seller_bp.route('/dashboard')
@login_required
def seller_dashboard():
    """Seller dashboard - main overview"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response

    shops = _resolve_user_shops(current_user)
    shop_ids = [shop.id for shop in shops]
    products = []
    product_ids = []

    if shop_ids:
        products = Product.query.filter(
            Product.shop_id.in_(shop_ids)
        ).order_by(Product.updated_at.desc()).all()
        product_ids = [product.id for product in products]

    active_products = [product for product in products if product.is_active]
    low_stock_products = [product for product in products if product.stock is not None and 0 < product.stock <= 10]
    out_of_stock_products = [product for product in products if product.stock is not None and product.stock <= 0]
    total_stock = sum(max(product.stock or 0, 0) for product in products)
    follower_count = UserFollowShop.query.filter(
        UserFollowShop.shop_id.in_(shop_ids)
    ).count() if shop_ids else 0
    wishlist_saves = UserFavoriteProduct.query.filter(
        UserFavoriteProduct.product_id.in_(product_ids)
    ).count() if product_ids else 0
    unread_notifications = Notification.query.filter_by(
        recipient_user_id=current_user.id,
        is_read=False,
    ).count()
    product_view_count = UserBrowsingHistory.query.filter(
        UserBrowsingHistory.product_id.in_(product_ids)
    ).count() if product_ids else 0
    shop_view_count = UserBrowsingHistory.query.filter(
        UserBrowsingHistory.shop_id.in_(shop_ids)
    ).count() if shop_ids else 0

    favorite_counts = {}
    if product_ids:
        favorite_counts = dict(
            db.session.query(
                UserFavoriteProduct.product_id,
                func.count(UserFavoriteProduct.id),
            ).filter(
                UserFavoriteProduct.product_id.in_(product_ids)
            ).group_by(UserFavoriteProduct.product_id).all()
        )

    popular_products = sorted(
        products,
        key=lambda product: (
            favorite_counts.get(product.id, 0),
            _timestamp_or_zero(product.updated_at or product.created_at),
        ),
        reverse=True,
    )[:5]

    recent_stock_updates = []
    if product_ids:
        recent_stock_updates = StockUpdate.query.filter(
            StockUpdate.product_id.in_(product_ids)
        ).order_by(StockUpdate.updated_at.desc()).limit(4).all()

    recent_notifications = Notification.query.filter_by(
        recipient_user_id=current_user.id,
    ).order_by(Notification.created_at.desc()).limit(4).all()

    recent_activity = []
    for item in recent_notifications:
        recent_activity.append({
            'title': item.title,
            'description': item.message,
            'time_ago': _time_ago(item.created_at),
            'icon': _bootstrap_icon_name(_notification_icon(item)),
            'color': 'info' if not item.is_read else 'secondary',
            'url': _notification_action_url(item),
            'sort_at': _timestamp_or_zero(item.created_at),
        })

    for update in recent_stock_updates:
        direction = "increased" if update.stock_change > 0 else "reduced"
        recent_activity.append({
            'title': update.product.name if update.product else 'Stock updated',
            'description': f"Stock {direction} from {update.old_stock} to {update.new_stock}",
            'time_ago': _time_ago(update.updated_at),
            'icon': 'boxes',
            'color': 'warning',
            'url': url_for('manage_bp.products'),
            'sort_at': _timestamp_or_zero(update.updated_at),
        })

    for product in products[:4]:
        recent_activity.append({
            'title': product.name,
            'description': 'Product updated' if product.updated_at else 'Product added',
            'time_ago': _time_ago(product.updated_at or product.created_at),
            'icon': 'box-seam',
            'color': 'primary',
            'url': url_for('manage_bp.products'),
            'sort_at': _timestamp_or_zero(product.updated_at or product.created_at),
        })

    recent_activity = sorted(
        recent_activity,
        key=lambda item: item.get('sort_at', 0),
        reverse=True,
    )[:6]

    dashboard = {
        'shops': shops,
        'primary_shop': shops[0] if shops else None,
        'metrics': {
            'shops_count': len(shops),
            'products_count': len(products),
            'active_products_count': len(active_products),
            'low_stock_count': len(low_stock_products),
            'out_of_stock_count': len(out_of_stock_products),
            'total_stock': total_stock,
            'followers_count': follower_count,
            'wishlist_saves': wishlist_saves,
            'unread_notifications': unread_notifications,
            'product_views': product_view_count,
            'shop_views': shop_view_count,
        },
        'low_stock_products': low_stock_products[:5],
        'out_of_stock_products': out_of_stock_products[:5],
        'popular_products': popular_products,
        'favorite_counts': favorite_counts,
        'recent_activity': recent_activity,
    }

    return render_template('seller/seller_dashboard.html', dashboard=dashboard)

@seller_bp.route('/shop')
@seller_bp.route('/shop/edit')
@login_required
def seller_shop():
    """Shop management page"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response

    shop = _resolve_owned_shop(current_user, request.args.get('shop_id', type=int), allow_default=True)
    map_embed_url = _build_shop_map_embed_url(shop) if shop else None
    shop_payload = _build_shop_payload(shop)
    setup_state = _build_shop_setup_state(shop)

    return render_template(
        'seller/shop.html',
        seller_id=current_user.id,
        shop=shop,
        shop_payload=shop_payload,
        map_embed_url=map_embed_url,
        setup_state=setup_state,
        onboarding_mode=False,
    )


@seller_bp.route('/shop/setup/basic', methods=['POST'])
@login_required
def save_shop_basic_step():
    """Save the basic shop info step."""
    try:
        shop = _resolve_owned_shop(current_user, _requested_shop_id())
        name = str(request.form.get('name') or '').strip()
        gps_value = str(request.form.get('gps') or '').strip()
        address = str(request.form.get('address') or '').strip()
        normalized_gps = _normalize_gps(gps_value)

        if not name:
            return _build_shop_feedback_response('Add your shop name to continue.', tone='danger')
        if not normalized_gps:
            return _build_shop_feedback_response('Choose your shop location on the map to continue.', tone='danger')
        if not address:
            return _build_shop_feedback_response('Add a quick direction note so people can find your shop easily.', tone='danger')

        if not shop:
            shop = Shop(
                name=name,
                gps=normalized_gps,
                address=address,
                is_active=True,
                owner_id=current_user.id,
            )
            shop.replace_image_urls([DEFAULT_SHOP_PLACEHOLDER_IMAGE])
            db.session.add(shop)
        else:
            shop.name = name
            shop.gps = normalized_gps
            shop.address = address

        if current_user.role != USER_ROLE_SELLER:
            current_user.role = USER_ROLE_SELLER

        db.session.commit()
        return _build_shop_setup_success('basic', 'Basic info saved. Nice start.', shop)

    except ValueError as exc:
        db.session.rollback()
        return _build_shop_feedback_response(str(exc), tone='danger')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(exc)
        return _build_shop_feedback_response('We could not save this step yet. Please try again.', tone='danger')


@seller_bp.route('/shop/setup/image', methods=['POST'])
@login_required
def save_shop_image_step():
    """Save the front image step."""
    try:
        shop = _resolve_owned_shop(current_user, _requested_shop_id())
        if not shop:
            return _build_shop_feedback_response('Save your basic shop details first.', tone='danger')

        if request.content_length and request.content_length > 6 * 1024 * 1024:
            return _build_shop_feedback_response('Image is too large. Use a file under 6MB.', tone='danger')

        uploaded_file = request.files.get('front_image')
        if not uploaded_file or not uploaded_file.filename:
            return _build_shop_feedback_response('Choose a front image to continue.', tone='danger')

        image_url = _store_shop_front_image(uploaded_file, shop.id)
        remaining_images = [
            image_key for image_key in shop.image_urls
            if image_key and image_key not in {DEFAULT_SHOP_PLACEHOLDER_IMAGE, image_url}
        ]
        shop.replace_image_urls([image_url, *remaining_images][:3])
        db.session.commit()

        return _build_shop_setup_success('image', 'Front image saved.', shop)

    except ValueError as exc:
        db.session.rollback()
        return _build_shop_feedback_response(str(exc), tone='danger')
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(exc)
        return _build_shop_feedback_response('We could not save the image yet. Please try again.', tone='danger')


@seller_bp.route('/shop/setup/contact', methods=['POST'])
@login_required
def save_shop_contact_step():
    """Save the business contact step."""
    try:
        shop = _resolve_owned_shop(current_user, _requested_shop_id())
        if not shop:
            return _build_shop_feedback_response('Save your basic shop details first.', tone='danger')

        email = str(request.form.get('email') or '').strip()
        phone = str(request.form.get('phone') or '').strip()
        if not (email or phone):
            return _build_shop_feedback_response('Add at least an email or phone number to continue.', tone='danger')

        shop.email = email or None
        shop.phone = phone or None
        db.session.commit()

        return _build_shop_setup_success('contact', 'Contact details saved.', shop)

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(exc)
        return _build_shop_feedback_response('We could not save the contact details yet. Please try again.', tone='danger')


@seller_bp.route('/shop/setup/description', methods=['POST'])
@login_required
def save_shop_description_step():
    """Save the shop description step."""
    try:
        shop = _resolve_owned_shop(current_user, _requested_shop_id())
        if not shop:
            return _build_shop_feedback_response('Save your basic shop details first.', tone='danger')

        description = str(request.form.get('description') or '').strip()
        if not description:
            return _build_shop_feedback_response('Add a short description before finishing setup.', tone='danger')

        shop.description = description
        db.session.commit()

        return _build_shop_setup_success('description', 'Setup finished. Your shop profile is saved.', shop)

    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception(exc)
        return _build_shop_feedback_response('We could not save the description yet. Please try again.', tone='danger')

@seller_bp.route('/products')
@seller_bp.route('/products/new')
@login_required
def seller_products():
    """Products management page"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response

    shop = _resolve_user_shop(current_user)
    categories = Category.query.filter(
        Category.is_active.is_(True),
        Category.level == CATEGORY_LEVEL_LEAF,
    ).order_by(Category.name.asc()).all()

    products = []
    if shop:
        products = Product.query.filter_by(shop_id=shop.id).order_by(Product.updated_at.desc()).all()

    category_payload = [
        {'id': category.id, 'name': category.name}
        for category in categories
    ]
    product_payload = [_serialize_template_product(product) for product in products]

    return render_template(
        'seller/products.html',
        seller_id=current_user.id,
        shop=shop,
        category_payload=category_payload,
        product_payload=product_payload,
        open_create=request.path.endswith('/new'),
    )

@seller_bp.route('/analytics')
@login_required
def seller_analytics_page():
    """Analytics dashboard page"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response
    return render_template('seller/analytics.html')

@seller_bp.route('/verification')
@login_required
def seller_verification():
    """Shop verification page"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response
    return render_template('seller/verification.html')

# Buyer template routes
@buyer_bp.route('/dashboard')
def buyer_dashboard():
    """Buyer dashboard"""
    return render_template('buyer/dashboard.html')

@buyer_bp.route('/shops')
def buyer_shops():
    """Browse shops page"""
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()
    return render_template('buyer/shops.html', categories=categories)

@buyer_bp.route('/products')
def buyer_products():
    """Browse products page"""
    categories = Category.query.filter_by(is_active=True).order_by(Category.name.asc()).all()
    return render_template('buyer/products.html', categories=categories)

@buyer_bp.route('/shop/<int:shop_id>')
def buyer_shop_detail(shop_id):
    """Shop detail page"""
    return redirect(url_for('main_bp.shop_detail', shop_id=shop_id))

@buyer_bp.route('/wishlist')
@login_required
def wishlist():
    """User wishlist page with shops and products tabs"""
    # Fetch followed shops
    follows = UserFollowShop.query.filter_by(user_id=current_user.id).order_by(
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
                'primary_image_url': shop.primary_image_url,
                'phone': shop.phone,
                'town': shop.town,
                'region': shop.region,
                'verification_status': shop.verification_status,
                'followed_at': follow.followed_at.isoformat() if follow.followed_at else None
            }
            shops.append(shop_dict)
    
    # Fetch favorited products
    favorites = UserFavoriteProduct.query.filter_by(user_id=current_user.id).order_by(
        UserFavoriteProduct.favorited_at.desc()
    ).all()
    
    products = []
    for favorite in favorites:
        product = Product.query.get(favorite.product_id)
        if product and product.is_active:
            shop = Shop.query.get(product.shop_id)
            if shop and shop.is_active:
                product_dict = {
                    'id': product.id,
                    'name': product.name,
                    'description': product.description,
                    'price': float(product.price or 0),
                    'primary_image_url': product.primary_image_url,
                    'shop_id': product.shop_id,
                    'shop_name': shop.name if shop else 'Unknown Shop',
                    'favorited_at': favorite.favorited_at.isoformat() if favorite.favorited_at else None
                }
                products.append(product_dict)
    
    return render_template('buyer/wishlist.html', shops=shops, products=products)

@buyer_bp.route('/followed-shops')
@login_required
def followed_shops():
    """Redirect followed shops to unified wishlist page"""
    return redirect(url_for('buyer_bp.wishlist'))

# Old admin routes removed in favor of mw_admin_bp
