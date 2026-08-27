# Template routes for HTMX frontend
import csv
import io
from ..services import email_service
from datetime import datetime, timedelta, timezone
from ..services.analytics_service import track_event
from ..models.analytics_model import Event
import json
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, make_response, jsonify
from sqlalchemy import case, func, or_, nullslast
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from flask_login import login_user, current_user, logout_user
from urllib.parse import quote_plus
from werkzeug.utils import secure_filename
from ..forms import LoginForm, RegistrationForm
from ..services.geocoding_service import reverse_geocode
from ..utils.location import get_user_location, haversine_distance_expr, NEAR_YOU_KM
from ..utils.ids_parser import IDSParser
from ..utils.threading_utils import run_in_background
from ..utils.cloudinary_images import process_and_upload_image, delete_image
from ..models import (
    Category,
    Product,
    Shop,
    ShopImage,
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

# Notification types - defined here to avoid circular imports
NOTIFICATION_TYPE_LOCATION_SETUP = 'home_location_setup'
NOTIFICATION_TYPE_PHONE_SETUP = 'phone_number_setup'

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

IRREGULAR_PLURALS = {
    'pharmacy': 'pharmacies',
    'grocery': 'groceries',
    'bakery': 'bakeries',
    'category': 'categories',
}


def pluralize_category(category):
    """Convert a category name to a human-friendly plural label."""
    if not category:
        return ''

    category = category.strip().lower()
    words = category.split()
    last_word = words[-1]

    if last_word.endswith('s'):
        return category.title()

    if last_word in IRREGULAR_PLURALS:
        words[-1] = IRREGULAR_PLURALS[last_word]
    elif last_word.endswith(('s', 'x', 'z', 'ch', 'sh')):
        words[-1] = last_word + 'es'
    elif (
        last_word.endswith('y')
        and len(last_word) > 1
        and last_word[-2] not in 'aeiou'
    ):
        words[-1] = last_word[:-1] + 'ies'
    else:
        words[-1] = last_word + 's'

    return ' '.join(words).title()


def login_required(func):
    """Overwrites the flask_login's login_required"""
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated:
            session['prev'] = request.url
            flash('A quick login is required first.', 'info')
            return redirect(url_for('main_bp.login'))
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
    if 'phone' in notification_type or NOTIFICATION_TYPE_PHONE_SETUP in notification_type:
        return 'phone'
    if 'user' in notification_type:
        return 'user'
    if 'location' in notification_type or NOTIFICATION_TYPE_LOCATION_SETUP in notification_type:
        return 'location'
    return 'system'


def _bootstrap_icon_name(icon):
    return {
        'support': 'headset',
        'product': 'box-seam',
        'system': 'bell',
        'user': 'person',
        'phone': 'telephone-fill',
        'location': 'geo-alt',
    }.get(icon, icon)


def _notification_action_url(notification):
    payload = notification.get_payload() or {}
    if payload.get('action_url'):
        return payload['action_url']
    if notification.notification_type == NOTIFICATION_TYPE_LOCATION_SETUP:
        return url_for('main_bp.home_location_setup')
    if notification.notification_type == NOTIFICATION_TYPE_PHONE_SETUP:
        return url_for('main_bp.profile')
    if payload.get('conversation_id') and 'support' in (notification.notification_type or ''):
        if current_user.is_authenticated and current_user.role == USER_ROLE_ADMIN:
            return url_for('support_bp.admin_support_chat', id=payload['conversation_id'])
        return url_for('support_bp.my_support_chat', id=payload['conversation_id'])
    return None


def _check_and_create_location_notification(user):
    """Check if user needs location setup notification and create if needed"""
    if user.region and user.district and user.town:
        return
    existing = Notification.query.filter_by(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_LOCATION_SETUP,
        is_read=False
    ).first()
    if existing:
        return
    notification = Notification(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_LOCATION_SETUP,
        title='Set your home location',
        message='Set your home location so we can always show you shops and products around you.',
    )
    notification.set_payload({'action_url': url_for('main_bp.home_location_setup'), 'icon': 'location'})
    db.session.add(notification)
    db.session.commit()


def _check_and_create_phone_notification(user):
    """Check if user needs phone number setup notification and create if needed"""
    if user.phone:
        return
    existing = Notification.query.filter_by(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_PHONE_SETUP,
        is_read=False
    ).first()
    if existing:
        return
    notification = Notification(
        recipient_user_id=user.id,
        notification_type=NOTIFICATION_TYPE_PHONE_SETUP,
        title='Add your phone number',
        message='Please add your phone number so buyers and sellers can contact you easily when necessary.',
    )
    notification.set_payload({'action_url': url_for('main_bp.profile'), 'icon': 'phone'})
    db.session.add(notification)
    db.session.commit()


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


def _reverse_geocode_location(latitude, longitude):
    try:
        return reverse_geocode(latitude, longitude)
    except Exception:
        current_app.logger.exception(
            'Reverse geocoding failed for latitude=%s longitude=%s',
            latitude,
            longitude,
        )
        return None


@run_in_background()
def _geocode_shop_location(shop_id):
    shop = db.session.get(Shop, shop_id)
    if not shop or not shop.gps or (shop.town and shop.district and shop.region):
        return

    normalized_gps = _normalize_gps(shop.gps)
    if not normalized_gps:
        return
    latitude, longitude = (float(value) for value in normalized_gps.split(','))
    location_data = _reverse_geocode_location(latitude, longitude)
    if not location_data:
        return
    shop.town = location_data.get('town')
    shop.district = location_data.get('district')
    shop.region = location_data.get('region')
    db.session.commit()


@seller_bp.route('/shop/reverse-geocode', methods=['GET'])
@login_required
def reverse_geocode_shop_location():
    """Return town/region details for a selected shop location."""
    lat = request.args.get('lat', type=float)
    lng = request.args.get('lng', type=float)

    if lat is None or lng is None:
        return jsonify({
            'success': False,
            'message': 'Latitude and longitude are required.',
        }), 400

    normalized_gps = _normalize_gps(f'{lat},{lng}')
    if not normalized_gps:
        return jsonify({
            'success': False,
            'message': 'Invalid coordinates supplied.',
        }), 400

    location_data = _reverse_geocode_location(lat, lng)
    if not location_data:
        return jsonify({
            'success': False,
            'message': 'Could not detect a location for this pin.',
        }), 200

    return jsonify({
        'success': True,
        'location': location_data,
    }), 200


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
    try:
        return process_and_upload_image(
            file_storage,
            'market_window/shops/storefronts',
            max_dimensions=(1600, 1200),
            entity_type='shop',
            entity_id=shop_id,
        )
    except Exception:
        current_app.logger.exception('Shop image upload failed for shop %s', shop_id)
        raise


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
            value = item.last_updated or item.created_at
            if value is None:
                value = datetime(1970, 1, 1, tzinfo=timezone.utc)
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
    setup_shop = Shop.query.filter_by(
        id=session.get('managed_shop_id'),
        owner_id=None,
    ).first() if session.get('managed_shop_id') else None
    if not _resolve_user_shop(current_user) and not setup_shop and (not current_user.is_admin):
        flash('It appears you do not own a shop.', 'warning')
        return redirect(url_for('main_bp.index'))
    return None


def _build_shop_payload(shop):
    if not shop:
        return None

    return {
        'id': shop.id,
        'name': shop.name,
        'category': shop.google_category,
        'is_owned_by_current_user': bool(current_user.is_authenticated and shop.owner_id == current_user.id),
        'description': shop.description,
        'business_type': shop.business_type,
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
        'basic_complete': bool(shop and shop.name and shop.google_category and _normalize_gps(shop.gps) and (shop.address or '').strip()),
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


def _sequential_shop_setup_step(step):
    step_order = ['basic', 'image', 'contact', 'description']
    try:
        current_idx = step_order.index(step)
    except ValueError:
        return _next_shop_setup_step({})
    if current_idx >= len(step_order) - 1:
        return 'complete'
    return step_order[current_idx + 1]


def _build_more_shop_page(shop, page=1, per_page=8):
    """Return active shops with same-category shops first, then all others."""
    user_lat, user_lng = get_user_location(current_user)
    if user_lat is None and shop.gps:
        from ..services.personalization_service import parse_gps
        user_lat, user_lng = parse_gps(shop.gps)

    query = Shop.query.filter(
        Shop.is_active.is_(True),
        Shop.id != shop.id,
    )
    category_rank = case(
        (func.lower(Shop.google_category) == func.lower(shop.google_category), 0),
        else_=1,
    ) if shop.google_category else case((Shop.id == shop.id, 1), else_=1)
    dist_expr = haversine_distance_expr(user_lat, user_lng) if user_lat is not None and user_lng is not None else None

    if dist_expr is not None:
        query = query.add_columns(dist_expr.label('distance_km')).order_by(
            category_rank.asc(),
            nullslast(dist_expr.asc()),
            Shop.name.asc(),
            Shop.id.asc(),
        )
    else:
        query = query.order_by(category_rank.asc(), Shop.name.asc(), Shop.id.asc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    shops = []
    for row in pagination.items:
        recommended, distance = row if dist_expr is not None else (row, None)
        recommended._distance_km = distance
        recommended._near_you = distance is not None and distance <= NEAR_YOU_KM
        shops.append(recommended)
    return shops, pagination


def _build_shop_feedback_response(message, tone='success', trigger_payload=None):
    response = make_response(
        render_template(
            'seller/partials/shop_setup_feedback.html',
            message=message,
            tone=tone,
            trigger_payload=trigger_payload,
        )
    )
    if trigger_payload:
        response.headers['HX-Trigger'] = json.dumps(trigger_payload)
    return response


def _build_shop_setup_success(step, message, shop, next_step=None):
    setup_state = _build_shop_setup_state(shop)
    next_step = next_step or _sequential_shop_setup_step(step)
    setup_state['active_step'] = next_step
    return _build_shop_feedback_response(
        message=message,
        tone='success',
        trigger_payload={
            'shop-step-saved': {
                'step': step,
                'nextStep': next_step,
                'setupState': setup_state,
                'shop_id': shop.id if shop else None,
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


def _resolve_setup_shop(user):
    active_shop_id = session.get('active_shop_id')
    if active_shop_id:
        shop = _resolve_owned_shop(user, active_shop_id, allow_default=False)
        if shop:
            return shop
        shop = Shop.query.filter_by(id=active_shop_id, owner_id=None).first()
        if shop and session.get('managed_shop_id') == shop.id:
            return shop

    requested_shop_id = _requested_shop_id()
    if requested_shop_id:
        shop = _resolve_owned_shop(user, requested_shop_id, allow_default=False)
        if shop:
            return shop
        shop = Shop.query.filter_by(id=requested_shop_id, owner_id=None).first()
        if shop and session.get('managed_shop_id') == shop.id:
            return shop

    managed_shop_id = session.get('managed_shop_id')
    if managed_shop_id:
        return Shop.query.filter_by(id=managed_shop_id, owner_id=None).first()

    return None


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
        func.min(Shop.google_category).label('name'),
        func.count(Event.id).label('visit_count'),
    ).join(
        Event,
        (Event.entity_id == Shop.id)
        & (Event.entity_type == 'shop')
        & (Event.event_type == 'shop_view'),
    ).filter(
        Shop.is_active.is_(True),
        Shop.google_category.isnot(None),
        func.trim(Shop.google_category) != '',
    ).group_by(
        func.lower(Shop.google_category),
    ).order_by(
        func.count(Event.id).desc(), func.min(Shop.google_category).asc()
    ).limit(12).all()

    category_rows = [
        {
            'name': pluralize_category(row.name),
            'visit_count': row.visit_count,
        }
        for row in category_rows
    ]

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
    form = LoginForm()

    if request.referrer and '/login' not in request.referrer:
        session['prev'] = request.referrer

    return render_template('auth/login.html', form=form)

@main_bp.route('/register')
def register():
    """Registration page"""
    form = RegistrationForm()
    return render_template('auth/register.html', form=form)

def _clean_invalid_shop_addresses():
    """Remove scraper placeholders that are not real shop addresses."""
    invalid_values = {'·', 'open'}
    shops_to_clean = [
        shop for shop in Shop.query.filter(Shop.address.isnot(None)).all()
        if (shop.address or '').strip().casefold() in invalid_values
    ]
    if not shops_to_clean:
        return
    for shop in shops_to_clean:
        shop.address = None
    db.session.commit()


@main_bp.route('/shops')
def shops():
    """Browse shops page"""
    _clean_invalid_shop_addresses()
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

    from ..utils.tracking import track_event_async
    track_event_async(
        'shop_view',
        user=current_user._get_current_object() if current_user.is_authenticated else None,
        entity_type='shop',
        entity_id=shop.id,
        payload={'source': 'shop_detail'},
    )

    map_embed_url = _build_shop_map_embed_url(shop)
    directions_url = _build_shop_directions_url(shop)
    child_categories = _load_shop_categories(shop.id)
    shop_is_favorited = False
    shop_is_owner = current_user.is_authenticated and shop.owner_id == current_user.id
    if current_user.is_authenticated:
        shop_is_favorited = UserFollowShop.query.filter_by(
            user_id=current_user.id,
            shop_id=shop.id,
        ).first() is not None

    more_shops, more_shops_page = _build_more_shop_page(shop)

    return render_template(
        'buyer/shop_detail.html',
        shop=shop,
        map_embed_url=map_embed_url,
        directions_url=directions_url,
        shop_categories=child_categories,
        shop_is_favorited=shop_is_favorited,
        shop_is_owner=shop_is_owner,
        more_shops=more_shops,
        more_shops_has_next=more_shops_page.has_next,
        more_shops_next_page=more_shops_page.next_num if more_shops_page.has_next else None,
        more_shops_url=url_for('main_bp.shop_detail_recommendations', shop_id=shop.id),
        location_check_url=url_for('main_bp.check_shop_location', shop_id=shop.id),
    )


@main_bp.route('/shops/<int:shop_id>/more')
def shop_detail_recommendations(shop_id):
    """Return the next page of category-first shop recommendations."""
    shop = Shop.query.filter(
        Shop.id == shop_id,
        Shop.is_active.is_(True),
    ).first_or_404()
    page = max(request.args.get('page', 1, type=int), 1)
    shops, pagination = _build_more_shop_page(shop, page=page)
    return render_template(
        'buyer/shop_cards.html',
        shops=shops,
        has_next=pagination.has_next,
        next_page=pagination.next_num if pagination.has_next else None,
        next_url=(url_for('main_bp.shop_detail_recommendations', shop_id=shop.id,
                          page=pagination.next_num) if pagination.has_next else None),
        search_term='',
        sort_by='nearest',
        category_id=None,
        user_id=None,
        user_has_location=True,
    )


@main_bp.route('/shops/<int:shop_id>/check-location', methods=['GET', 'POST'])
def check_shop_location(shop_id):
    shop = Shop.query.filter(Shop.id == shop_id, Shop.is_active.is_(True)).first_or_404()
    location = {'town': shop.town, 'district': shop.district, 'region': shop.region}
    ready = bool(shop.town)
    poll_attempt = request.args.get('poll_attempt', 0, type=int)
    if request.method == 'POST' and not ready and shop.gps:
        _geocode_shop_location(shop.id)
        if request.headers.get('HX-Request') == 'true':
            return render_template(
                'buyer/partials/shop_location.html',
                shop=shop,
                compact=request.args.get('compact') == '1',
                auto_load=False,
                pending=True,
                poll_attempt=0,
            )
        return jsonify(success=True, started=True, location=location), 202
    if request.headers.get('HX-Request') == 'true':
        return render_template(
            'buyer/partials/shop_location.html',
            shop=shop,
            compact=request.args.get('compact') == '1',
            auto_load=False,
            pending=not ready and bool(shop.gps) and poll_attempt < 5,
            poll_attempt=poll_attempt,
        )
    return jsonify(success=True, ready=ready, location=location)


@main_bp.route('/shops/<int:shop_id>/claim')
def claim_shop_page(shop_id):
    """Dedicated Claim Shop & Contact Verification page."""
    shop = Shop.query.filter(Shop.id == shop_id).first_or_404()

    if not current_user.is_authenticated:
        flash('Please log in to claim this shop.', 'info')
        return redirect(url_for('main_bp.login', next=url_for('main_bp.claim_shop_page', shop_id=shop.id)))

    from ..utils.phone_utils import normalize_ghana_phone, mask_phone_number

    user = current_user
    shop_is_owner = (shop.owner_id == user.id)

    # Normalized phone comparisons
    norm_user_phone = normalize_ghana_phone(user.phone) if user.phone else None
    norm_shop_phone = normalize_ghana_phone(shop.phone) if shop.phone else None

    # Normalized email comparisons
    norm_user_email = user.email.strip().lower() if user.email else None
    norm_shop_email = shop.email.strip().lower() if shop.email else None

    phone_match = bool(user.is_phone_verified and norm_user_phone and norm_shop_phone and norm_user_phone == norm_shop_phone)
    email_match = bool(user.is_email_verified and norm_user_email and norm_shop_email and norm_user_email == norm_shop_email)
    is_eligible = bool(phone_match or email_match)

    masked_shop_phone = mask_phone_number(shop.phone) if shop.phone else None
    masked_user_phone = mask_phone_number(user.phone) if user.phone else None

    masked_shop_email = None
    if shop.email and '@' in shop.email:
        parts = shop.email.split('@')
        name = parts[0]
        masked_shop_email = (name[0] + '***' + name[-1] if len(name) > 2 else name[0] + '***') + '@' + parts[1]

    masked_user_email = None
    if user.email and '@' in user.email:
        parts = user.email.split('@')
        name = parts[0]
        masked_user_email = (name[0] + '***' + name[-1] if len(name) > 2 else name[0] + '***') + '@' + parts[1]

    return render_template(
        'buyer/claim_shop.html',
        shop=shop,
        user=user,
        shop_is_owner=shop_is_owner,
        phone_match=phone_match,
        email_match=email_match,
        is_eligible=is_eligible,
        norm_user_phone=norm_user_phone,
        norm_shop_phone=norm_shop_phone,
        masked_shop_phone=masked_shop_phone,
        masked_user_phone=masked_user_phone,
        masked_shop_email=masked_shop_email,
        masked_user_email=masked_user_email,
    )


@main_bp.route('/shops/<int:shop_id>/search')

def shop_detail_search(shop_id):
    """Search products within a specific shop and return a product-card fragment."""
    shop = Shop.query.filter(
        Shop.id == shop_id,
        Shop.is_active.is_(True),
    ).first_or_404()

    query = request.args.get('q', '').strip()
    from ..search import search_service as search_backend

    if search_backend is not None:
        products = search_backend.search_in_shop(shop.id, query)
    else:
        products_query = Product.query.filter(
            Product.shop_id == shop.id,
            Product.is_active.is_(True),
        )
        if query:
            products_query = products_query.filter(
                or_(
                    Product.name.ilike(f'%{query}%'),
                    Product.description.ilike(f'%{query}%'),
                    Product.tags.ilike(f'%{query}%'),
                )
            )
        products = products_query.order_by(Product.updated_at.desc()).limit(20).all()

    from ..utils.tracking import track_event_async

    if query:
        track_event_async(
            'search_in_shop',
            user=current_user._get_current_object() if current_user.is_authenticated else None,
            entity_type='shop',
            entity_id=shop.id,
            payload={
                'query': query,
                'result_count': len(products),
                'source': 'shop_detail',
            },
        )

    return render_template(
        'buyer/product_cards.html',
        products=products,
        hide_load_more=True,
        next_page=None,
        has_next=False,
        search_term=query,
        shop_id=shop.id,
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
        location_check_url=url_for('main_bp.check_shop_location', shop_id=shop.id),
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

    # Prevent marking location setup notification as read before setup is complete
    if notification.notification_type == NOTIFICATION_TYPE_LOCATION_SETUP:
        # Check if user has completed location setup
        if not (current_user.region and current_user.district and current_user.town):
            return jsonify({
                'success': False,
                'message': 'Please complete your location setup first',
                'notification': _notification_to_dict(notification),
            }), 400

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
    explore_query = request.args.get('q', '').strip()
    search_term = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', 'product_count_desc')
    with_products_value = request.args.get('with_products')
    with_products = (
        True if with_products_value is None
        else with_products_value.lower() in ('1', 'true', 'yes', 'on')
    )
    selected_category_id = request.args.get('category_id', type=int)
    shop_id = request.args.get('shop_id', type=int)

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
    if shop_id:
        categories_data = categories_data.filter(Shop.id == shop_id)

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
            shop_id=shop_id,
            shop=Shop.query.get(shop_id),
        )

    return render_template(
        'public/categories.html',
        categories=categories_data.all(),
        search_term=search_term,
        sort_by=sort_by,
        shop_id=shop_id,
        with_products=with_products,
        selected_category=selected_category,
        selected_children=selected_children,
        shop=Shop.query.get(shop_id),
        explore_query=explore_query,
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
            current_user.updated_at = datetime.now(timezone.utc)
            
            # Commit changes to database
            db.session.commit()

            # Mark phone setup notification as read if phone is set
            if current_user.phone:
                phone_notification = Notification.query.filter_by(
                    recipient_user_id=current_user.id,
                    notification_type=NOTIFICATION_TYPE_PHONE_SETUP,
                    is_read=False
                ).first()
                if phone_notification:
                    phone_notification.mark_read()
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
            return redirect(url_for('main_bp.profile'))
    
    # Calculate membership duration
    if current_user.created_at:
        days_since_creation = (datetime.now(timezone.utc) - current_user.created_at).days
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


@main_bp.route('/home-location-setup')
@login_required
def home_location_setup():
    """Home location setup page"""
    return render_template('public/home_location_setup.html')


@main_bp.route('/save-home-location', methods=['POST'])
@login_required
def save_home_location():
    """Save user's home location"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'message': 'No data provided'}), 400
        
        region = data.get('region', '').strip()
        district = data.get('district', '').strip()
        town = data.get('town', '').strip()
        gps = data.get('gps', '').strip()
        
        if not all([region, district, town]):
            return jsonify({'success': False, 'message': 'All location fields are required'}), 400
        
        # Update user location
        current_user.region = region
        current_user.district = district
        current_user.town = town
        current_user.updated_at = datetime.now(timezone.utc)
        
        # Note: We don't store GPS for user in the current model, but we could add it if needed
        # For now, we're just updating the location fields
        
        db.session.commit()
        
        # Mark location setup notification as read
        location_notification = Notification.query.filter_by(
            recipient_user_id=current_user.id,
            notification_type=NOTIFICATION_TYPE_LOCATION_SETUP,
            is_read=False
        ).first()
        
        if location_notification:
            location_notification.mark_read()
            db.session.commit()
        
        return jsonify({'success': True, 'message': 'Location saved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Error saving location: {str(e)}'}), 500


# Dropbox routes (main)
def _parse_ids_upload(file_storage):
    """Parse one uploaded CSV file and return a preview report."""

    filename = secure_filename(file_storage.filename or '').strip()
    if not filename:
        raise ValueError('Please choose a CSV file before uploading.')
    if Path(filename).suffix.lower() != '.csv':
        raise ValueError(f"'{filename}' is not a CSV file.")

    raw_bytes = file_storage.read()
    if not raw_bytes:
        raise ValueError(f"'{filename}' is empty.")

    try:
        text = raw_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw_bytes.decode('latin-1')

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
    except csv.Error:
        dialect = csv.get_dialect('excel')

    parser = IDSParser()
    import_batch = uuid4().hex
    parsed_rows = []
    non_empty_rows = 0

    reader = csv.reader(io.StringIO(text), dialect)
    headers = next(reader, None)
    if headers is None:
        raise ValueError(f"'{filename}' does not contain any rows.")

    resolved_headers = parser.resolve_headers(headers)
    header_indexes = {
        field: [index for index, header in enumerate(headers)
                if str(header).strip().casefold() == field.casefold()]
        for field in resolved_headers
    }

    for row_number, row in enumerate(reader, start=2):
        if not any(str(cell or '').strip() for cell in row):
            continue

        non_empty_rows += 1
        parsed = parser.parse_row(row, header_indexes)
        parsed_rows.append({
            'row_number': row_number,
            'raw_cells': len(row),
            'data': parsed,
        })

    staging = parser.persist_imports(
        [row['data'] for row in parsed_rows],
        uploader_user_id=current_user.id,
        import_batch=import_batch,
    )

    upload_dir = Path(current_app.static_folder) / 'uploads' / 'imports'
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"ids-{uuid4().hex}-{filename}"
    upload_path = upload_dir / stored_name
    upload_path.write_bytes(raw_bytes)

    return {
        'filename': filename,
        'stored_name': stored_name,
        'stored_url': url_for('static', filename=f'uploads/imports/{stored_name}'),
        'headers': headers,
        'total_rows': non_empty_rows,
        'preview_rows': parsed_rows[:20],
        'parsed_rows': parsed_rows,
        'warning_count': sum(len(row['data'].get('warnings') or []) for row in parsed_rows),
        'staging': staging,
        'import_batch': import_batch,
    }


@main_bp.route('/dropbox', methods=['GET', 'POST'])
@login_required
def dropbox():
    """CSV upload page for IDS exports."""

    upload_reports = []
    errors = []

    if request.method == 'POST':
        files = [file for file in request.files.getlist('files') if file and file.filename]
        if not files:
            errors.append('Choose at least one CSV file to upload.')
        else:
            for file_storage in files:
                try:
                    upload_reports.append(_parse_ids_upload(file_storage))
                except ValueError as exc:
                    errors.append(str(exc))
                except Exception as exc:
                    current_app.logger.exception('Failed to parse IDS upload')
                    errors.append(f"Could not process '{secure_filename(file_storage.filename or 'upload.csv')}' ({exc}).")

    return render_template(
        'manage/dropbox.html',
        upload_reports=upload_reports,
        upload_errors=errors,
    )

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
    if current_user and (not current_user.is_anonymous):
        track_event('logout', current_user)

    logout_user()
    flash('You have been logged out successfully.', 'success')

    next_page = request.referrer
    return redirect(next_page or url_for('main_bp.index'))

###################################
####################################
@main_bp.route('/oauth/login')
def oauth_login():
    redirect_uri = url_for('main_bp.oauth_authorize', _external=True)
    return oauth.google.authorize_redirect(redirect_uri)

@main_bp.route('/oauth/authorize')
def oauth_authorize():
    """Logs in a user using Google OAuth. Redirect to the previous page or dashboard if not found"""
    from ..utils.username_utils import generate_username

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
            # Build a full_name string for the username generator
            full_name = f"{first_name} {last_name}".strip() or email.split('@')[0]
            username, parsed_first, parsed_last = generate_username(full_name)

            # Use Google's names if available, else fall back to parsed
            resolved_first = first_name or parsed_first
            resolved_last = last_name or parsed_last

            user = User(
                username=username,
                email=email,
                first_name=resolved_first,
                last_name=resolved_last,
                role=USER_ROLE_BUYER,
                status='active'
            )
            user.set_password(secrets.token_urlsafe(16))

            db.session.add(user)
            db.session.commit()

            login_user(user)
            from ..services.analytics_service import track_event
            track_event('signup', user)

            flash(
                f"Welcome to Market Window, {resolved_first or username}! "
                f"Your username is <strong>{username}</strong>. "
                f"Use it with your password if you ever sign in without Google.",
                "success"
            )

        # Prompt user if phone number or home location is missing
        _check_and_create_phone_notification(user)
        _check_and_create_location_notification(user)

        # 4. Redirect to the previous page or dashboard if not found
        next_page = session.pop('prev', None)
        if next_page:
            return redirect(next_page)
        if user.role == 'admin':
            return redirect(url_for('admin_template_bp.admin_dashboard'))
        elif user.role == 'seller':
            return redirect(url_for('seller_template_bp.seller_products_dashboard'))
        return redirect(url_for('main_bp.index'))

    except Exception as e:
        flash('Authentication failed', 'error')
        current_app.logger.exception(e)
        return redirect(url_for('main_bp.login'))

@seller_bp.route('/dashboard/products')
@login_required
def seller_products_dashboard():
    """Render the unified shop dashboard for sellers."""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response

    from ..models.analytics_model import Event
    from ..utils.helpers import get_managed_shop
    from ..utils.progress import get_shop_progress

    shop, error = get_managed_shop(current_user, request.args.get('shop_id', type=int))
    if error or not shop:
        flash(error or 'Please create a shop first to access the dashboard.', 'warning')
        return redirect(url_for('seller_template_bp.seller_shop'))

    managed_shops = list(current_user.owned_shops) if current_user.role != USER_ROLE_ADMIN else Shop.query.order_by(Shop.name.asc()).all()

    products = Product.query.filter_by(shop_id=shop.id).order_by(Product.updated_at.desc()).all()
    product_ids = [product.id for product in products]
    follower_count = UserFollowShop.query.filter_by(shop_id=shop.id).count()
    product_count = len(products)
    active_product_count = sum(1 for product in products if product.is_active)
    categories = Category.query.filter(
        Category.is_active.is_(True),
        Category.level == CATEGORY_LEVEL_LEAF,
    ).order_by(Category.name.asc()).all()
    recent_stock_updates = (
        StockUpdate.query.filter(StockUpdate.product_id.in_(product_ids))
        .order_by(StockUpdate.updated_at.desc())
        .limit(6)
        .all()
        if product_ids else []
    )
    recent_events = (
        Event.query.filter(
            db.or_(
                db.and_(Event.entity_type == 'shop', Event.entity_id == shop.id),
                db.and_(Event.entity_type == 'product', Event.entity_id.in_(product_ids))
            ) if product_ids else db.and_(Event.entity_type == 'shop', Event.entity_id == shop.id)
        ).order_by(Event.created_at.desc()).limit(8).all()
    )

    def describe_activity(event):
        payload = event.payload or {}
        event_label = (event.event_type or '').replace('_', ' ').title()
        query = payload.get('query')
        item_name = payload.get('product_name') or payload.get('name') or payload.get('shop_name')

        if event.event_type in {'search', 'search_in_shop', 'failed_search'} and query:
            return event_label, f'No results for "{query}"' if event.event_type == 'failed_search' else f'Searched for "{query}"'
        if event.event_type in {'product_view', 'product_click'}:
            return event_label, f'Viewed {item_name}' if item_name else 'Viewed a product'
        if event.event_type in {'product_add', 'product_created'}:
            return event_label, f'Added {item_name}' if item_name else 'Added a product'
        if event.event_type in {'product_update', 'product_updated'}:
            return event_label, f'Updated {item_name}' if item_name else 'Updated a product'
        if event.event_type in {'shop_update', 'shop_updated'}:
            return event_label, f'Updated {shop.name}'
        if event.event_type in {'shop_follow', 'follow_shop'}:
            return 'New follower', f'{shop.name} gained a follower'
        return event_label, payload.get('message') or 'Activity recorded'

    recent_activity = []
    for event in recent_events:
        title, message = describe_activity(event)
        recent_activity.append({
            'title': title,
            'message': message,
            'time_ago': _time_ago(event.created_at),
            'icon': 'clock',
            'color': 'info',
            'url': None,
            'sort_at': _timestamp_or_zero(event.created_at),
        })
    top_searches = db.session.query(
        Event.payload['query'].astext.label('query'),
        func.count(Event.id).label('count')
    ).filter(
        Event.event_type == 'search_in_shop',
        Event.entity_type == 'shop',
        Event.entity_id == shop.id,
    ).group_by(
        Event.payload['query'].astext
    ).order_by(
        func.count(Event.id).desc()
    ).limit(5).all()
    no_result_searches = db.session.query(
        Event.payload['query'].astext.label('query'),
        func.count(Event.id).label('count')
    ).filter(
        Event.event_type == 'search_in_shop',
        Event.entity_type == 'shop',
        Event.entity_id == shop.id,
        Event.payload['result_count'].astext == '0',
    ).group_by(
        Event.payload['query'].astext
    ).order_by(
        func.count(Event.id).desc()
    ).limit(5).all()

    shop_progress = get_shop_progress(shop)
    logo_image_url = shop.image_urls[1] if len(shop.image_urls) > 1 else None

    if not shop:
        flash("Please create a shop first to access the product dashboard.", "warning")
        return redirect(url_for('seller_template_bp.seller_shop'))

    return render_template(
        'seller/products_dashboard.html',
        shop=shop,
        products=products,
        product_count=product_count,
        active_product_count=active_product_count,
        follower_count=follower_count,
        recent_activity=recent_activity,
        recent_stock_updates=recent_stock_updates,
        top_searches=top_searches,
        no_result_searches=no_result_searches,
        shop_progress=shop_progress,
        logo_image_url=logo_image_url,
        managed_shops=managed_shops,
        categories=categories,
        is_active=lambda path: 'active' if request.path == path or request.path.startswith(path + '/') else '',
    )

# Seller template routes
@seller_bp.route('/dashboard')
@login_required
def seller_dashboard():
    """Seller dashboard - main overview"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect(url_for('seller_template_bp.seller_products_dashboard'))

    return redirect(url_for('seller_template_bp.seller_products_dashboard'))

@seller_bp.route('/shop')
@seller_bp.route('/shop/edit')
@login_required
def seller_shop():
    """Shop management page"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response

    requested_shop_id = request.args.get('shop_id', type=int)
    shop = _resolve_owned_shop(current_user, requested_shop_id) if requested_shop_id else None
    if shop and requested_shop_id:
        session['managed_shop_id'] = shop.id
        session['active_shop_id'] = shop.id
    shop = shop or _resolve_setup_shop(current_user) or _resolve_owned_shop(
        current_user,
        requested_shop_id,
        allow_default=True,
    )
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
        shop = _resolve_setup_shop(current_user)
        name = str(request.form.get('name') or '').strip()
        category = str(request.form.get('category') or '').strip()
        gps_value = str(request.form.get('gps') or '').strip()
        address = str(request.form.get('address') or '').strip()
        normalized_gps = _normalize_gps(gps_value)

        if not name:
            return _build_shop_feedback_response('Add your shop name to continue.', tone='danger')
        if not category:
            return _build_shop_feedback_response('Add your shop category to continue.', tone='warning')
        if not normalized_gps:
            return _build_shop_feedback_response('Choose your shop location on the map to continue.', tone='danger')
        if not address:
            return _build_shop_feedback_response('Add a quick direction note so people can find your shop easily.', tone='danger')

        business_type = str(request.form.get('business_type') or '').strip()
        if not business_type or business_type not in ('sales', 'service', 'both'):
            from ..utils.business_detection import is_service_name
            if is_service_name(name):
                business_type = 'service'
            else:
                business_type = 'sales'

        submitted_region = str(request.form.get('region') or '').strip()
        submitted_district = str(request.form.get('district') or '').strip()
        submitted_town = str(request.form.get('town') or '').strip()
        is_own_shop = request.form.get('is_own_shop') == 'on'

        should_geocode = bool(normalized_gps) and (
            not shop
            or shop.gps != normalized_gps
            or not (shop.region and shop.district and shop.town)
        )
        location_data = None
        if should_geocode:
            lat_text, lng_text = normalized_gps.split(',')
            location_data = _reverse_geocode_location(float(lat_text), float(lng_text))

        if not shop:
            region = submitted_region or (location_data['region'] if location_data else None)
            district = submitted_district or (location_data['district'] if location_data else None)
            town = submitted_town or (location_data['town'] if location_data else None)
            shop = Shop(
                name=name,
                google_category=category,
                gps=normalized_gps,
                address=address,
                business_type=business_type,
                region=region,
                district=district,
                town=town,
                is_active=True,
                owner_id=current_user.id if is_own_shop else None,
                is_claimed=is_own_shop,
            )
            shop.replace_image_urls([DEFAULT_SHOP_PLACEHOLDER_IMAGE])
            db.session.add(shop)
        else:
            shop.name = name
            shop.google_category = category
            shop.gps = normalized_gps
            shop.address = address
            shop.business_type = business_type
            shop.owner_id = current_user.id if is_own_shop else None
            shop.is_claimed = is_own_shop
            if should_geocode:
                shop.region = submitted_region or (location_data['region'] if location_data else None)
                shop.district = submitted_district or (location_data['district'] if location_data else None)
                shop.town = submitted_town or (location_data['town'] if location_data else None)
            else:
                shop.region = submitted_region or None
                shop.district = submitted_district or None
                shop.town = submitted_town or None

        db.session.commit()
        session['managed_shop_id'] = shop.id if shop else None
        session['active_shop_id'] = shop.id if shop else None
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
        shop = _resolve_setup_shop(current_user)
        if not shop:
            return _build_shop_feedback_response('Save your basic shop details first.', tone='danger')

        if request.form.get('remove_image') == '1':
            records = list(shop.image_records)
            old_primary = records[0] if records else None
            if not old_primary or old_primary.storage_key == DEFAULT_SHOP_PLACEHOLDER_IMAGE:
                return _build_shop_feedback_response('There is no custom front image to remove.', tone='info')

            shop.image_records.remove(old_primary)
            for index, record in enumerate(shop.image_records):
                record.sort_order = index
                record.is_primary = index == 0
            db.session.commit()
            if old_primary.cloudinary_public_id:
                delete_image(old_primary.cloudinary_public_id)
            return _build_shop_setup_success('image', 'Front image removed.', shop, next_step='image')

        if request.content_length and request.content_length > 6 * 1024 * 1024:
            return _build_shop_feedback_response('Image is too large. Use a file under 6MB.', tone='danger')

        uploaded_file = request.files.get('front_image')
        if not uploaded_file or not uploaded_file.filename:
            return _build_shop_feedback_response('Choose a front image to continue.', tone='danger')

        upload = _store_shop_front_image(uploaded_file, shop.id)
        existing_records = list(shop.image_records)
        old_primary = existing_records[0] if existing_records else None
        for record in existing_records[1:]:
            record.sort_order -= 1
            record.is_primary = False
        if old_primary:
            shop.image_records.remove(old_primary)
        shop.image_records.append(ShopImage(
            storage_key=upload['secure_url'],
            cloudinary_public_id=upload['public_id'],
            sort_order=0,
            is_primary=True,
        ))
        db.session.commit()
        if old_primary and old_primary.cloudinary_public_id:
            delete_image(old_primary.cloudinary_public_id)

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
        shop = _resolve_setup_shop(current_user)
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
        shop = _resolve_setup_shop(current_user)
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
    _clean_invalid_shop_addresses()
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
                    'shop_phone': shop.phone if shop else None,
                    'favorited_at': favorite.favorited_at.isoformat() if favorite.favorited_at else None
                }
                products.append(product_dict)
    
    return render_template('buyer/wishlist.html', shops=shops, products=products)

@buyer_bp.route('/followed-shops')
@login_required
def followed_shops():
    """Redirect followed shops to unified wishlist page"""
    return redirect(url_for('buyer_bp.wishlist'))

# Email Routes (Admin Test Utilities)

@admin_bp.route("/test/email", methods=["POST"])
@admin_required
def admin_test_email():
    """Admin test endpoint: trigger any available test email to the current admin."""
    email_type = request.form.get("email_type", "").strip()
    user = current_user

    if email_type == "verification":
        verification_code = str(secrets.randbelow(900000) + 100000)
        # Temporarily store on user object for the template (not persisted to DB for test)
        user.email_verification_code = verification_code
        user.email_verification_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
        db.session.commit()
        success, message = email_service.send_email_verification(user, verification_code)

    elif email_type == "welcome":
        success, message = email_service.send_welcome_email(user)

    else:
        return jsonify({"success": False, "message": f"Unknown email type: '{email_type}'"}), 400

    status_code = 200 if success else 500
    return jsonify({"success": success, "message": message}), status_code


# Legacy routes (kept for backward compatibility, now properly guarded)
@main_bp.route("/verify/email", methods=["GET", "POST"])
@login_required
def verify_email():
    """Verify user email address"""
    user = current_user

    verification_code = str(secrets.randbelow(900000) + 100000)
    user.email_verification_code = verification_code
    user.email_verification_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
    db.session.commit()

    success, message = email_service.send_email_verification(user, verification_code)
    if success:
        flash("Verification email sent! Please check your inbox.", "success")
    else:
        flash(f"Failed to send verification email: {message}", "error")
    return redirect(url_for("main_bp.index"))


@main_bp.route("/welcome", methods=["GET"])
@login_required
def welcome_email():
    """Send welcome email"""
    user = current_user
    success, message = email_service.send_welcome_email(user)
    if success:
        flash("Welcome email sent!", "success")
    else:
        flash(f"Failed to send welcome email: {message}", "error")
    return redirect(url_for("main_bp.index"))

