"""
Admin blueprint — all routes under /admin.
Every route is protected by strong backend permission checks.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from ..extensions import db
from ..models import (
    User, Shop, Product,
    Role, UserRole,
    VERIFICATION_STATUS_VERIFIED, VERIFICATION_STATUS_SUSPENDED,
    VERIFICATION_STATUS_PENDING,
)
from ..models.role_model import ROLE_SUPER_ADMIN, ROLE_ADMIN
from .decorators import login_required, admin_required, super_admin_required
from .services import (
    assign_role, remove_role, toggle_admin_mode,
    get_dashboard_stats, paginate_query, ensure_super_admin_exists,
)
from .forms import UserEditForm, ShopAdminEditForm, ProductAdminEditForm

mw_admin_bp = Blueprint('mw_admin_bp', __name__, url_prefix='/admin')

PER_PAGE = 20


# ---------------------------------------------------------------------------
# Context processor — inject helpers into all admin templates
# ---------------------------------------------------------------------------

@mw_admin_bp.context_processor
def admin_context():
    return {
        'ROLE_SUPER_ADMIN': ROLE_SUPER_ADMIN,
        'ROLE_ADMIN': ROLE_ADMIN,
    }


# ---------------------------------------------------------------------------
# Admin mode toggle (accessible from profile page)
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/toggle-admin-mode', methods=['POST'])
@login_required
def toggle_admin_mode_route():
    """Toggle the current user's admin_mode. Only works if they are an admin."""
    if not current_user.is_any_admin():
        flash('You do not have admin privileges.', 'error')
        return redirect(url_for('main_bp.profile'))

    new_mode = toggle_admin_mode(current_user)
    state = 'enabled' if new_mode else 'disabled'
    flash(f'Admin Mode {state}.', 'success')
    return redirect(request.referrer or url_for('main_bp.profile'))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/')
@mw_admin_bp.route('/dashboard')
@admin_required
def dashboard():
    stats = get_dashboard_stats()
    return render_template('admin/dashboard.html', **stats)


# ---------------------------------------------------------------------------
# Admin Management (super_admin only)
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/admins')
@super_admin_required
def admins():
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)

    # Find all users who have admin or super_admin role
    admin_role_ids = [
        r.id for r in Role.query.filter(Role.name.in_([ROLE_ADMIN, ROLE_SUPER_ADMIN])).all()
    ]
    admin_user_ids = (
        db.session.query(UserRole.user_id)
        .filter(UserRole.role_id.in_(admin_role_ids))
        .distinct()
        .subquery()
    ) if admin_role_ids else None

    if admin_user_ids is not None:
        query = User.query.filter(User.id.in_(admin_user_ids))
    else:
        query = User.query.filter(False)  # empty result

    if search:
        query = query.filter(
            or_(
                User.username.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
            )
        )

    pagination = paginate_query(query.order_by(User.created_at.desc()), page, PER_PAGE)
    return render_template(
        'admin/admins.html',
        pagination=pagination,
        admins=pagination.items,
        search=search,
    )


@mw_admin_bp.route('/admins/<int:user_id>/assign', methods=['POST'])
@super_admin_required
def assign_admin(user_id):
    """Assign admin role to a user."""
    user = User.query.get_or_404(user_id)
    if user.is_super_admin():
        flash('Cannot modify a super admin\'s role this way.', 'error')
        return redirect(url_for('mw_admin_bp.admins'))
    assign_role(user, ROLE_ADMIN, assigned_by_id=current_user.id)
    db.session.commit()
    flash(f'{user.username} has been assigned Admin role.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.admins'))


@mw_admin_bp.route('/admins/<int:user_id>/revoke', methods=['POST'])
@super_admin_required
def revoke_admin(user_id):
    """Remove all admin roles from a user."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot revoke your own admin privileges.', 'error')
        return redirect(request.referrer or url_for('mw_admin_bp.admins'))
        
    remove_role(user, ROLE_ADMIN)
    remove_role(user, ROLE_SUPER_ADMIN)
    # Disable admin_mode when role is removed
    user.admin_mode = False
    db.session.commit()
    flash(f'Admin role removed from {user.username}.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.admins'))


@mw_admin_bp.route('/admins/<int:user_id>/promote', methods=['POST'])
@super_admin_required
def promote_to_super_admin(user_id):
    """Promote an admin to super_admin."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You already are a super admin.', 'info')
        return redirect(url_for('mw_admin_bp.admins'))
    assign_role(user, ROLE_SUPER_ADMIN, assigned_by_id=current_user.id)
    # Ensure they also have the admin role
    assign_role(user, ROLE_ADMIN, assigned_by_id=current_user.id)
    db.session.commit()
    flash(f'{user.username} promoted to Super Admin.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.admins'))


@mw_admin_bp.route('/admins/<int:user_id>/demote', methods=['POST'])
@super_admin_required
def demote_super_admin(user_id):
    """Demote a super_admin to regular admin."""
    user = User.query.get_or_404(user_id)
    # Prevent self-demotion
    if user.id == current_user.id:
        flash('You cannot demote yourself.', 'error')
        return redirect(url_for('mw_admin_bp.admins'))
    remove_role(user, ROLE_SUPER_ADMIN)
    db.session.commit()
    flash(f'{user.username} demoted to Admin.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.admins'))


@mw_admin_bp.route('/admins/<int:user_id>/disable', methods=['POST'])
@super_admin_required
def disable_admin(user_id):
    """Disable an admin account (set is_active=False)."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot disable your own account.', 'error')
        return redirect(url_for('mw_admin_bp.admins'))
    if user.is_super_admin() and not current_user.is_super_admin():
        flash('Only super admins can disable other super admins.', 'error')
        return redirect(url_for('mw_admin_bp.admins'))
    user.is_active = False
    user.admin_mode = False
    db.session.commit()
    flash(f'{user.username}\'s account has been disabled.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.admins'))


@mw_admin_bp.route('/admins/<int:user_id>/enable', methods=['POST'])
@super_admin_required
def enable_admin(user_id):
    """Re-enable a disabled admin account."""
    user = User.query.get_or_404(user_id)
    user.is_active = True
    db.session.commit()
    flash(f'{user.username}\'s account has been enabled.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.admins'))


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/users')
@admin_required
def users():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)

    query = User.query

    if search:
        query = query.filter(
            or_(
                User.username.ilike(f'%{search}%'),
                User.email.ilike(f'%{search}%'),
                User.phone.ilike(f'%{search}%'),
            )
        )

    if status_filter == 'active':
        query = query.filter(User.is_active.is_(True))
    elif status_filter == 'suspended':
        query = query.filter(User.is_active.is_(False))

    pagination = paginate_query(query.order_by(User.created_at.desc()), page, PER_PAGE)
    return render_template(
        'admin/users.html',
        pagination=pagination,
        users=pagination.items,
        search=search,
        status_filter=status_filter,
    )


@mw_admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    # Admins cannot edit super admins (only super admins can)
    if user.is_super_admin() and not current_user.is_super_admin():
        flash('You do not have permission to edit a super admin.', 'error')
        return redirect(url_for('mw_admin_bp.users'))

    form = UserEditForm(obj=user)

    if form.validate_on_submit():
        try:
            # Check username uniqueness
            existing = User.query.filter(
                User.username == form.username.data,
                User.id != user.id,
            ).first()
            if existing:
                flash('That username is already taken.', 'error')
                return render_template('admin/user_edit.html', form=form, user=user)

            # Check email uniqueness
            existing_email = User.query.filter(
                User.email == form.email.data,
                User.id != user.id,
            ).first()
            if existing_email:
                flash('That email is already in use.', 'error')
                return render_template('admin/user_edit.html', form=form, user=user)

            user.username = form.username.data.strip()
            user.email = form.email.data.strip()
            user.phone = form.phone.data.strip() if form.phone.data else None
            user.first_name = form.first_name.data.strip() if form.first_name.data else None
            user.last_name = form.last_name.data.strip() if form.last_name.data else None
            user.is_active = form.is_active.data
            db.session.commit()
            flash(f'{user.username} updated successfully.', 'success')
            return redirect(url_for('mw_admin_bp.users'))
        except IntegrityError:
            db.session.rollback()
            flash('A database integrity error occurred. Please check the values.', 'error')

    return render_template('admin/user_edit.html', form=form, user=user)


@mw_admin_bp.route('/users/<int:user_id>/suspend', methods=['POST'])
@admin_required
def suspend_user(user_id):
    """Toggle user is_active (suspend / activate)."""
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash('You cannot suspend your own account.', 'error')
        return redirect(url_for('mw_admin_bp.users'))
    if user.is_super_admin() and not current_user.is_super_admin():
        flash('Only super admins can suspend super admin accounts.', 'error')
        return redirect(url_for('mw_admin_bp.users'))

    user.is_active = not user.is_active
    if not user.is_active:
        user.admin_mode = False  # disable admin mode on suspension
    db.session.commit()
    state = 'activated' if user.is_active else 'suspended'
    flash(f'{user.username} has been {state}.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.users'))


@mw_admin_bp.route('/users/<int:user_id>/assign-role', methods=['POST'])
@super_admin_required
def assign_user_role(user_id):
    """Assign admin or super_admin role to a user (super_admin only)."""
    user = User.query.get_or_404(user_id)
    role_name = request.form.get('role_name')
    if role_name not in [ROLE_ADMIN, ROLE_SUPER_ADMIN]:
        flash('No role was selected. Assigned role: Admin by default', 'info')
        role_name = ROLE_ADMIN

    # Prevent privilege escalation: only super_admin can grant super_admin
    if role_name == ROLE_SUPER_ADMIN and not current_user.is_super_admin():
        flash('Only super admins can grant super admin status.', 'error')
        return redirect(url_for('mw_admin_bp.users'))

    assign_role(user, role_name, assigned_by_id=current_user.id)
    db.session.commit()
    flash(f'{user.username} assigned role: {role_name}.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.users'))


# ---------------------------------------------------------------------------
# Shop Management
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/shops')
@admin_required
def shops():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)

    query = Shop.query

    if search:
        query = query.filter(
            or_(
                Shop.name.ilike(f'%{search}%'),
                Shop.email.ilike(f'%{search}%'),
                Shop.phone.ilike(f'%{search}%'),
                Shop.town.ilike(f'%{search}%'),
            )
        )

    if status_filter == 'active':
        query = query.filter(Shop.is_active.is_(True))
    elif status_filter == 'inactive':
        query = query.filter(Shop.is_active.is_(False))
    elif status_filter == 'verified':
        query = query.filter(Shop.verification_status == VERIFICATION_STATUS_VERIFIED)
    elif status_filter == 'pending':
        query = query.filter(Shop.verification_status == VERIFICATION_STATUS_PENDING)

    pagination = paginate_query(query.order_by(Shop.created_at.desc()), page, PER_PAGE)
    return render_template(
        'admin/shops.html',
        pagination=pagination,
        shops=pagination.items,
        search=search,
        status_filter=status_filter,
    )


@mw_admin_bp.route('/shops/<int:shop_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_shop(shop_id):
    shop = Shop.query.get_or_404(shop_id)
    form = ShopAdminEditForm(obj=shop)

    if form.validate_on_submit():
        shop.name = form.name.data.strip()
        shop.description = form.description.data
        shop.phone = form.phone.data.strip() if form.phone.data else None
        shop.email = form.email.data.strip() if form.email.data else None
        shop.address = form.address.data.strip() if form.address.data else None
        shop.is_active = form.is_active.data
        shop.verification_status = form.verification_status.data

        # Set verified_at timestamp when status becomes verified
        if form.verification_status.data == VERIFICATION_STATUS_VERIFIED and not shop.verified_at:
            from datetime import datetime, timezone
            shop.verified_at = datetime.now(timezone.utc)
            shop.verified_by = current_user.id

        db.session.commit()
        flash(f'Shop "{shop.name}" updated.', 'success')
        return redirect(url_for('mw_admin_bp.shops'))

    return render_template('admin/shop_edit.html', form=form, shop=shop)


@mw_admin_bp.route('/shops/<int:shop_id>/verify', methods=['POST'])
@admin_required
def verify_shop(shop_id):
    """Toggle shop verification between 'verified' and 'pending'."""
    shop = Shop.query.get_or_404(shop_id)
    from datetime import datetime, timezone

    if shop.verification_status == VERIFICATION_STATUS_VERIFIED:
        shop.verification_status = VERIFICATION_STATUS_PENDING
        shop.verified_at = None
        shop.verified_by = None
        flash(f'Verification removed from "{shop.name}".', 'info')
    else:
        shop.verification_status = VERIFICATION_STATUS_VERIFIED
        shop.verified_at = datetime.now(timezone.utc)
        shop.verified_by = current_user.id
        flash(f'"{shop.name}" has been verified.', 'success')

    db.session.commit()
    return redirect(request.referrer or url_for('mw_admin_bp.shops'))


@mw_admin_bp.route('/shops/<int:shop_id>/suspend', methods=['POST'])
@admin_required
def suspend_shop(shop_id):
    """Toggle shop active status."""
    shop = Shop.query.get_or_404(shop_id)
    shop.is_active = not shop.is_active
    db.session.commit()
    state = 'activated' if shop.is_active else 'suspended'
    flash(f'Shop "{shop.name}" {state}.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.shops'))


# ---------------------------------------------------------------------------
# Product Management
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/products')
@admin_required
def products():
    search = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)

    query = Product.query.join(Shop)

    if search:
        query = query.filter(
            or_(
                Product.name.ilike(f'%{search}%'),
                Product.code.ilike(f'%{search}%'),
                Shop.name.ilike(f'%{search}%'),
            )
        )

    if status_filter == 'active':
        query = query.filter(Product.is_active.is_(True), Product.is_hidden.is_(False))
    elif status_filter == 'hidden':
        query = query.filter(Product.is_hidden.is_(True))
    elif status_filter == 'inactive':
        query = query.filter(Product.is_active.is_(False))

    pagination = paginate_query(query.order_by(Product.created_at.desc()), page, PER_PAGE)
    return render_template(
        'admin/products.html',
        pagination=pagination,
        products=pagination.items,
        search=search,
        status_filter=status_filter,
    )


@mw_admin_bp.route('/products/<int:product_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    product = Product.query.get_or_404(product_id)
    form = ProductAdminEditForm(obj=product)

    if form.validate_on_submit():
        product.name = form.name.data.strip()
        product.description = form.description.data
        product.price = form.price.data
        product.stock = form.stock.data if form.stock.data is not None else product.stock
        product.is_active = form.is_active.data
        product.is_hidden = form.is_hidden.data
        db.session.commit()
        flash(f'Product "{product.name}" updated.', 'success')
        return redirect(url_for('mw_admin_bp.products'))

    return render_template('admin/product_edit.html', form=form, product=product)


@mw_admin_bp.route('/products/<int:product_id>/hide', methods=['POST'])
@admin_required
def toggle_hide_product(product_id):
    """Toggle product visibility."""
    product = Product.query.get_or_404(product_id)
    product.is_hidden = not product.is_hidden
    db.session.commit()
    state = 'hidden' if product.is_hidden else 'visible'
    flash(f'"{product.name}" is now {state}.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.products'))


@mw_admin_bp.route('/products/<int:product_id>/delete', methods=['POST'])
@admin_required
def delete_product(product_id):
    """Permanently delete a product."""
    product = Product.query.get_or_404(product_id)
    name = product.name
    db.session.delete(product)
    db.session.commit()
    flash(f'Product "{name}" has been permanently deleted.', 'success')
    return redirect(url_for('mw_admin_bp.products'))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/settings')
@admin_required
def settings():
    return render_template('admin/settings.html')


@mw_admin_bp.route('/analytics')
@admin_required
def analytics():
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import func, case
    from ..models.analytics_model import Event, SearchHistory, SavedSearch
    from ..models.product_model import Product
    from ..models.shop_model import Shop
    from ..models.user_model import User

    # 1. Total events over time (last 30 days)
    since_30d = datetime.now(timezone.utc) - timedelta(days=30)
    events_over_time = db.session.query(
        func.date_trunc('day', Event.created_at).label('day'),
        func.count(Event.id).label('count')
    ).filter(
        Event.created_at >= since_30d
    ).group_by('day').order_by('day').all()
    
    events_chart_data = {
        'labels': [e.day.strftime('%Y-%m-%d') for e in events_over_time],
        'data': [e.count for e in events_over_time]
    }

    # 2. Event type breakdown
    event_breakdown = db.session.query(
        Event.event_type,
        func.count(Event.id).label('count')
    ).filter(
        Event.created_at >= since_30d
    ).group_by(Event.event_type).order_by(func.count(Event.id).desc()).all()
    
    breakdown_chart_data = {
        'labels': [eb.event_type for eb in event_breakdown],
        'data': [eb.count for eb in event_breakdown]
    }

    # 3. Conversion Funnel (Homepage -> Product View -> Wishlist -> Contact)
    funnel_homepage = db.session.query(func.count(Event.id)).filter(Event.event_type == 'homepage_visit', Event.created_at >= since_30d).scalar() or 0
    funnel_views = db.session.query(func.count(Event.id)).filter(Event.event_type.in_(['product_view', 'product_click']), Event.created_at >= since_30d).scalar() or 0
    funnel_wishlist = db.session.query(func.count(Event.id)).filter(Event.event_type == 'wishlist_add', Event.created_at >= since_30d).scalar() or 0
    funnel_contact = db.session.query(func.count(Event.id)).filter(Event.event_type == 'product_contact', Event.created_at >= since_30d).scalar() or 0
    
    funnel_data = {
        'labels': ['Homepage Visits', 'Product Views', 'Wishlist Adds', 'Contact Seller'],
        'data': [funnel_homepage, funnel_views, funnel_wishlist, funnel_contact]
    }

    # 4. Top 10 Viewed Products
    top_viewed_products = db.session.query(
        Product.id,
        Product.name,
        func.count(Event.id).label('views')
    ).join(Event, Event.entity_id == Product.id).filter(
        Event.event_type == 'product_view',
        Event.entity_type == 'product',
        Event.created_at >= since_30d
    ).group_by(Product.id, Product.name).order_by(func.count(Event.id).desc()).limit(10).all()

    # 5. Top 10 Viewed Shops
    top_viewed_shops = db.session.query(
        Shop.id,
        Shop.name,
        func.count(Event.id).label('views')
    ).join(Event, Event.entity_id == Shop.id).filter(
        Event.event_type == 'shop_view',
        Event.entity_type == 'shop',
        Event.created_at >= since_30d
    ).group_by(Shop.id, Shop.name).order_by(func.count(Event.id).desc()).limit(10).all()

    # 6. Top Search Queries (from Event tracking payload)
    top_searches = db.session.query(
        Event.payload['query'].astext.label('query_text'),
        func.count(Event.id).label('count'),
        func.sum(case((Event.event_type == 'search', 1), else_=0)).label('success_count'),
        func.sum(case((Event.event_type == 'failed_search', 1), else_=0)).label('failed_count')
    ).filter(
        Event.event_type.in_(['search', 'failed_search']),
        Event.created_at >= since_30d
    ).group_by(Event.payload['query'].astext).order_by(func.count(Event.id).desc()).limit(10).all()

    # 7. Failed Searches (from Event tracking payload)
    failed_searches = db.session.query(
        Event.payload['query'].astext.label('query_text'),
        func.count(Event.id).label('count'),
        func.max(Event.created_at).label('last_searched')
    ).filter(
        Event.event_type == 'failed_search',
        Event.created_at >= since_30d
    ).group_by(Event.payload['query'].astext).order_by(func.count(Event.id).desc()).limit(10).all()

    # 8. Top Active Users
    top_users = db.session.query(
        User.id,
        User.username,
        func.count(Event.id).label('events')
    ).join(Event, Event.user_id == User.id).filter(
        Event.created_at >= since_30d
    ).group_by(User.id, User.username).order_by(func.count(Event.id).desc()).limit(10).all()

    # General summaries
    total_events = db.session.query(func.count(Event.id)).scalar() or 0
    total_searches = db.session.query(func.count(SearchHistory.id)).scalar() or 0
    total_saved_searches = db.session.query(func.count(SavedSearch.id)).scalar() or 0

    return render_template(
        'admin/analytics.html',
        events_chart_data=events_chart_data,
        breakdown_chart_data=breakdown_chart_data,
        funnel_data=funnel_data,
        top_viewed_products=top_viewed_products,
        top_viewed_shops=top_viewed_shops,
        top_searches=top_searches,
        failed_searches=failed_searches,
        top_users=top_users,
        total_events=total_events,
        total_searches=total_searches,
        total_saved_searches=total_saved_searches
    )
