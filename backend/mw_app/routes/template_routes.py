# Template routes for HTMX frontend
import json
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app, make_response
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased
from flask_login import login_user, current_user, logout_user
from urllib.parse import quote_plus
from werkzeug.utils import secure_filename
from ..forms import LoginForm, RegistrationForm
from ..utils.helpers import admin_required
from ..models import (
    Category,
    Product,
    Shop,
    UserFollowShop,
    UserFavoriteProduct,
    User,
    USER_ROLE_BUYER,
    USER_ROLE_SELLER,
    CATEGORY_LEVEL_LEAF,
    VERIFICATION_STATUS_VERIFIED,
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


def _resolve_owned_shop(user, shop_id=None):
    shops = _resolve_user_shops(user)
    if not shops:
        return None

    if shop_id is None:
        return shops[0]

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
    verified_shops = Shop.query.filter(
        Shop.is_active.is_(True),
        Shop.verification_status == VERIFICATION_STATUS_VERIFIED,
    )

    featured_shops = verified_shops.order_by(
        Shop.promoted.desc(),
        Shop.last_updated.desc(),
    ).limit(6).all()

    featured_products = Product.query.join(Shop).filter(
        Product.is_active.is_(True),
        Shop.is_active.is_(True),
        Shop.verification_status == VERIFICATION_STATUS_VERIFIED,
    ).order_by(
        Product.created_at.desc(),
    ).limit(12).all()

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

    return render_template(
        'public/index.html',
        featured_shops=featured_shops,
        featured_products=featured_products,
        top_categories=category_rows,
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
    shop = None if create_new else _resolve_owned_shop(current_user, requested_shop_id)
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
        Shop.verification_status == VERIFICATION_STATUS_VERIFIED,
    ).first_or_404()

    map_embed_url = _build_shop_map_embed_url(shop)
    directions_url = _build_shop_directions_url(shop)
    child_categories = _load_shop_categories(shop.id)
    shop_is_favorited = False
    if current_user.is_authenticated and current_user.role == USER_ROLE_BUYER:
        shop_is_favorited = UserFollowShop.query.filter_by(
            user_id=current_user.id,
            shop_id=shop.id,
        ).first() is not None

    return render_template(
        'buyer/shop_detail.html',
        shop=shop,
        map_embed_url=map_embed_url,
        directions_url=directions_url,
        shop_categories=child_categories,
        shop_is_favorited=shop_is_favorited,
    )


@seller_bp.route('/shop/preview')
@login_required
def seller_shop_preview():
    """Preview the current seller shop using the buyer-facing layout."""
    shop = _resolve_owned_shop(current_user, request.args.get('shop_id', type=int))
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
    return render_template('public/notifications.html')

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
    
    # Get user stats (placeholder data for now)
    user_stats = {
        'orders_count': 127,  # TODO: Get from orders table
        'reviews_count': 89,  # TODO: Get from reviews table
        'rating': 4.8,        # TODO: Calculate from reviews
        'member_since': current_user.created_at
    }
    
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
    
    user_stats['member_duration'] = member_duration
    
    # Get recent activity (placeholder data for now)
    recent_activity = [
        {
            'type': 'order_completed',
            'title': 'Order Completed',
            'description': 'Electronics Store - $249.99',
            'time_ago': '2 hours ago',
            'icon': 'check-circle',
            'color': 'success'
        },
        {
            'type': 'review_posted',
            'title': 'Review Posted',
            'description': 'Fashion Boutique - 5 stars',
            'time_ago': 'Yesterday',
            'icon': 'star',
            'color': 'primary'
        },
        {
            'type': 'wishlist_added',
            'title': 'Added to Wishlist',
            'description': 'Smart Watch Pro',
            'time_ago': '3 days ago',
            'icon': 'heart',
            'color': 'warning'
        },
        {
            'type': 'shop_followed',
            'title': 'New Shop Followed',
            'description': 'Tech Gadgets Store',
            'time_ago': '1 week ago',
            'icon': 'shop',
            'color': 'info'
        }
    ]

    owned_shops = _resolve_user_shops(current_user)
    
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
def seller_dashboard():
    """Seller dashboard - main overview"""
    return render_template('seller/seller_dashboard.html')

@seller_bp.route('/shop')
@seller_bp.route('/shop/edit')
@login_required
def seller_shop():
    """Shop management page"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response

    shop = _resolve_owned_shop(current_user, request.args.get('shop_id', type=int))
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
        if shop and shop.is_active and shop.verification_status == VERIFICATION_STATUS_VERIFIED:
            shop_dict = {
                'id': shop.id,
                'name': shop.name,
                'description': shop.description,
                'primary_image_url': shop.primary_image_url,
                'phone': shop.phone,
                'town': shop.town,
                'region': shop.region,
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

# Admin template routes
@admin_bp.route('/dashboard')
@admin_required
def admin_dashboard():
    """Admin dashboard"""
    return render_template('admin/dashboard.html')

@admin_bp.route('/users')
@admin_required
def admin_users():
    """User management page"""
    return render_template('admin/users.html')

@admin_bp.route('/shops')
@admin_required
def admin_shops():
    """Shop management page"""
    return render_template('admin/shops.html')

@admin_bp.route('/categories')
@admin_required
def admin_categories():
    """Category management page"""
    return render_template('admin/categories.html')

@admin_bp.route('/products')
@admin_required
def admin_products():
    """Product management page"""
    return render_template('admin/products.html')

@admin_bp.route('/reports')
@admin_required
def admin_reports():
    """Reports and analytics page"""
    return render_template('admin/reports.html')

@admin_bp.route('/bulk-operations')
@admin_required
def admin_bulk_operations():
    """Bulk operations page"""
    return render_template('admin/bulk_operations.html')

# HTMX partial endpoints (for dynamic updates)
@seller_bp.route('/partials/products/list')
@login_required
def products_list_partial():
    """Partial template for products list (HTMX updates)"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response
    return render_template('seller/partials/products_list.html')

@seller_bp.route('/partials/analytics/data')
@login_required
def analytics_data_partial():
    """Partial template for analytics data (HTMX updates)"""
    redirect_response = _seller_guard_redirect()
    if redirect_response:
        return redirect_response
    return render_template('seller/partials/analytics_data.html')

@buyer_bp.route('/partials/shops/list')
def shops_list_partial():
    """Partial template for shops list (HTMX updates)"""
    return render_template('buyer/partials/shops_list.html')

@buyer_bp.route('/partials/products/list')
def products_list_partial():
    """Partial template for products list (HTMX updates)"""
    return render_template('buyer/partials/products_list.html')

@admin_bp.route('/partials/users/list')
@admin_required
def users_list_partial():
    """Partial template for users list (HTMX updates)"""
    return render_template('admin/partials/users_list.html')

@admin_bp.route('/partials/shops/list')
@admin_required
def shops_list_partial():
    """Partial template for shops list (HTMX updates)"""
    return render_template('admin/partials/shops_list.html')

@admin_bp.route('/partials/reports/data')
@admin_required
def reports_data_partial():
    """Partial template for reports data (HTMX updates)"""
    return render_template('admin/partials/reports_data.html')
