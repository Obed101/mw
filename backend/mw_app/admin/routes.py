"""
Admin blueprint — all routes under /admin.
Every route is protected by strong backend permission checks.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import current_user
from sqlalchemy import or_, func
from sqlalchemy.exc import IntegrityError
import re

from ..extensions import db
from ..models import (
    User, Shop, ShopImport, Product, Notification,
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
from ..utils.threading_utils import run_in_background

mw_admin_bp = Blueprint('mw_admin_bp', __name__, url_prefix='/admin')

PER_PAGE = 20
SHOP_IMPORT_BATCHES_PER_PAGE = 1
SHOP_IMPORT_ITEMS_PER_PAGE = 50
DEFAULT_SHOP_PLACEHOLDER_IMAGE = '/static/images/mw_logo_trans.png'


@run_in_background()
def _geocode_shop_import_location(import_id):
    """Enrich one staged import in the background after an explicit request."""
    from ..utils.ids_parser import IDSParser

    imported = db.session.get(ShopImport, import_id)
    if not imported or imported.latitude is None or imported.longitude is None:
        return

    parser = IDSParser()
    try:
        location = parser._reverse_geocode(imported.latitude, imported.longitude)
        imported.town = location.get('town')
        imported.district = location.get('district')
        imported.region = location.get('region')
        db.session.commit()
    except Exception:
        db.session.rollback()



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

def _import_phone_key(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if digits.startswith("233") and len(digits) == 12:
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return "233" + digits[1:]
    if len(digits) == 9:
        return "233" + digits
    return None


def _import_identity_key(value):
    cleaned = re.sub(r"[^\w]+", " ", str(value or "").casefold(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip() or None


def _import_duplicate_keys(name, phone, address, category, plus_code, latitude=None, longitude=None):
    name_key = _import_identity_key(name)
    phone_key = _import_phone_key(phone)
    phone_name_key = (phone_key, name_key) if phone_key and name_key else None
    attributes = {
        _import_identity_key(value)
        for value in (address, category, plus_code)
    }
    if latitude is not None and longitude is not None:
        attributes.add(f'{float(latitude):.5f},{float(longitude):.5f}')
    return phone_name_key, {
        (name_key, attribute)
        for attribute in attributes
        if name_key and attribute
    }


def _shop_gps_parts(shop):
    if not shop.gps or ',' not in shop.gps:
        return None, None
    try:
        latitude, longitude = (float(part.strip()) for part in shop.gps.split(',', 1))
        return latitude, longitude
    except (TypeError, ValueError):
        return None, None


def _shop_import_batch_filter(batch_key):
    if batch_key is None:
        return ShopImport.import_batch.is_(None)
    return ShopImport.import_batch == batch_key


@mw_admin_bp.route('/shop-imports')
@admin_required
def shop_imports():
    selected_user_id = request.args.get('user_id', type=int)
    include_completed = request.args.get('include_completed', type=int, default=0) == 1
    batch_page = max(request.args.get('batch_page', 1, type=int), 1)
    item_page = max(request.args.get('item_page', 1, type=int), 1)

    import_users = (
        User.query
        .join(ShopImport, ShopImport.uploader_user_id == User.id)
        .distinct()
        .order_by(User.username.asc())
        .all()
    )
    batches = []
    items = []
    batch = None
    item_pagination = None

    if selected_user_id:
        batch_query = (
            db.session.query(
                ShopImport.import_batch,
                func.max(ShopImport.created_at).label('batch_date'),
            )
            .filter(ShopImport.uploader_user_id == selected_user_id)
        )
        if not include_completed:
            batch_query = batch_query.filter(ShopImport.import_status == 'pending')
        batch_query = (
            batch_query
            .group_by(ShopImport.import_batch)
            .order_by(func.max(ShopImport.created_at).desc())
        )
        batches = batch_query.paginate(
            page=batch_page,
            per_page=SHOP_IMPORT_BATCHES_PER_PAGE,
            error_out=False,
        )
        if batches.items:
            batch = batches.items[0]
            item_query = ShopImport.query.filter(
                ShopImport.uploader_user_id == selected_user_id,
                _shop_import_batch_filter(batch.import_batch),
            ).order_by(ShopImport.created_at.desc(), ShopImport.id.desc())
            item_pagination = item_query.paginate(
                page=item_page,
                per_page=SHOP_IMPORT_ITEMS_PER_PAGE,
                error_out=False,
            )
            items = item_pagination.items

    template = 'admin/partials/shop_import_batch.html' if request.args.get('fragment') else 'admin/shop_imports.html'
    return render_template(
        template,
        import_users=import_users,
        selected_user_id=selected_user_id,
        batches=batches,
        batch=batch,
        items=items,
        item_pagination=item_pagination,
        batch_page=batch_page,
        include_completed=include_completed,
    )


@mw_admin_bp.route('/shop-imports/<int:import_id>/check-location', methods=['GET', 'POST'])
@admin_required
def check_import_location(import_id):
    imported = ShopImport.query.get_or_404(import_id)
    location = {
        'town': imported.town,
        'district': imported.district,
        'region': imported.region,
    }
    ready = any(location.values())

    if request.method == 'POST' and not ready:
        if imported.latitude is None or imported.longitude is None:
            return jsonify(success=False, message='This import has no valid GPS coordinates.'), 400
        _geocode_shop_import_location(imported.id)
        return jsonify(success=True, started=True, location=location), 202

    return jsonify(success=True, ready=ready, location=location)


@mw_admin_bp.route('/shop-imports/action', methods=['POST'])
@admin_required
def shop_import_action():
    action = request.form.get('action', '').strip().lower()
    import_ids = [value for value in request.form.getlist('import_ids') if value.isdigit()]
    if action not in {'commit', 'reject', 'delete'} or not import_ids:
        flash('Select at least one imported shop and choose an action.', 'warning')
        return redirect(request.referrer or url_for('mw_admin_bp.shop_imports'))

    imports = ShopImport.query.filter(
        ShopImport.id.in_([int(value) for value in import_ids])
    ).all()
    existing_phone_name_keys = set()
    existing_no_phone_keys = set()
    for shop in Shop.query.all():
        latitude, longitude = _shop_gps_parts(shop)
        phone_name_key, no_phone_keys = _import_duplicate_keys(
            shop.name,
            shop.phone,
            shop.address,
            shop.google_category,
            shop.plus_code,
            latitude,
            longitude,
        )
        if phone_name_key:
            existing_phone_name_keys.add(phone_name_key)
        if not _import_phone_key(shop.phone):
            existing_no_phone_keys.update(no_phone_keys)
    processed = 0
    duplicate_count = 0
    uploader_messages = {}

    for imported in imports:
        if action == 'delete':
            uploader_messages.setdefault(imported.uploader_user_id, []).append(
                f'Import "{imported.name}" was deleted by an administrator.'
            )
            db.session.delete(imported)
            processed += 1
            continue

        if imported.import_status != 'pending':
            continue

        if action == 'reject':
            imported.import_status = 'rejected'
            imported.rejection_reason = 'Rejected by an administrator.'
            uploader_messages.setdefault(imported.uploader_user_id, []).append(
                f'Import "{imported.name}" was rejected by an administrator.'
            )
            processed += 1
            continue

        phone_name_key, no_phone_keys = _import_duplicate_keys(
            imported.name,
            imported.phone_number,
            imported.address,
            imported.category,
            imported.plus_code,
            imported.latitude,
            imported.longitude,
        )
        is_duplicate = (
            phone_name_key in existing_phone_name_keys
            if phone_name_key
            else bool(existing_no_phone_keys.intersection(no_phone_keys))
        )
        if is_duplicate:
            imported.import_status = 'rejected'
            imported.rejection_reason = 'A matching shop identity already exists in the shop database.'
            uploader_messages.setdefault(imported.uploader_user_id, []).append(
                f'Import "{imported.name}" was rejected because it duplicates an existing shop.'
            )
            duplicate_count += 1
            continue

        shop = Shop(
            name=imported.name,
            google_category=imported.category,
            address=imported.address,
            region=imported.region,
            district=imported.district,
            town=imported.town,
            gps=(f'{imported.latitude},{imported.longitude}'
                 if imported.latitude is not None and imported.longitude is not None else None),
            phone=imported.phone_number,
            # Imported Google listings remain unowned until somebody completes
            # the normal claim/verification flow.
            owner_id=None,
            creator_id=current_user.id,
            source='google',
            source_reference=f'shop_import:{imported.id}',
            import_batch=imported.import_batch,
            google_image_url=imported.image_url,
        )
        shop.replace_image_urls([DEFAULT_SHOP_PLACEHOLDER_IMAGE])
        db.session.add(shop)
        imported.import_status = 'approved'
        imported.rejection_reason = None
        if phone_name_key:
            existing_phone_name_keys.add(phone_name_key)
        else:
            existing_no_phone_keys.update(no_phone_keys)
        uploader_messages.setdefault(imported.uploader_user_id, []).append(
            f'Import "{imported.name}" was approved and added to the shop database.'
        )
        processed += 1

    db.session.flush()
    for uploader_id, messages in uploader_messages.items():
        if not uploader_id:
            continue
        Notification.create_for_users(
            [uploader_id],
            notification_type='shop_import_reviewed',
            title='Shop import reviewed',
            message=' '.join(messages[:3]) + (f' (+{len(messages) - 3} more)' if len(messages) > 3 else ''),
            actor_user_id=current_user.id,
            payload={'action': action, 'count': len(messages)},
        )
    db.session.commit()

    if duplicate_count:
        flash(f'{duplicate_count} duplicate import(s) were rejected automatically.', 'warning')
    flash(f'{processed} imported shop(s) processed.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.shop_imports'))


@mw_admin_bp.route('/shop-imports/<int:import_id>/edit')
@admin_required
def edit_imported_shop(import_id):
    imported = ShopImport.query.get_or_404(import_id)
    shop = Shop.query.filter_by(source_reference=f'shop_import:{imported.id}').first()
    if not shop:
        flash('Approve this import before opening the full shop editor.', 'info')
        return redirect(request.referrer or url_for('mw_admin_bp.shop_imports'))
    return redirect(url_for('mw_admin_bp.edit_shop', shop_id=shop.id))

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
        shop.google_category = form.google_category.data.strip() if form.google_category.data else None
        shop.description = form.description.data
        shop.business_type = form.business_type.data
        shop.phone = form.phone.data.strip() if form.phone.data else None
        shop.email = form.email.data.strip() if form.email.data else None
        shop.address = form.address.data.strip() if form.address.data else None
        shop.region = form.region.data.strip() if form.region.data else None
        shop.district = form.district.data.strip() if form.district.data else None
        shop.town = form.town.data.strip() if form.town.data else None
        shop.gps = form.gps.data.strip() if form.gps.data else None
        shop.plus_code = form.plus_code.data.strip() if form.plus_code.data else None
        shop.landmark = form.landmark.data.strip() if form.landmark.data else None
        shop.source = form.source.data.strip() if form.source.data else 'user'
        shop.source_reference = form.source_reference.data.strip() if form.source_reference.data else None
        shop.google_image_url = form.google_image_url.data.strip() if form.google_image_url.data else None
        shop.data_quality_score = form.data_quality_score.data
        shop.verification_notes = form.verification_notes.data
        shop.promoted = bool(form.promoted.data)
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



@mw_admin_bp.route('/service-keywords', methods=['GET'])
@admin_required
def service_keywords():
    from ..models.service_keyword_model import ServiceKeyword
    search = request.args.get('q', '').strip()
    page = request.args.get('page', 1, type=int)
    
    query = ServiceKeyword.query
    if search:
        query = query.filter(ServiceKeyword.keyword.ilike(f'%{search}%'))
        
    pagination = paginate_query(query.order_by(ServiceKeyword.keyword.asc()), page, PER_PAGE)
    
    return render_template(
        'admin/service_keywords.html',
        pagination=pagination,
        keywords=pagination.items,
        search=search
    )


@mw_admin_bp.route('/service-keywords/add', methods=['POST'])
@admin_required
def add_service_keyword():
    from ..models.service_keyword_model import ServiceKeyword
    keyword = request.form.get('keyword', '').strip().lower()
    if not keyword:
        flash('Keyword cannot be empty.', 'error')
        return redirect(url_for('mw_admin_bp.service_keywords'))
        
    existing = ServiceKeyword.query.filter_by(keyword=keyword).first()
    if existing:
        flash(f'Keyword "{keyword}" already exists.', 'error')
        return redirect(url_for('mw_admin_bp.service_keywords'))
        
    try:
        new_kw = ServiceKeyword(keyword=keyword, is_active=True)
        db.session.add(new_kw)
        db.session.commit()
        flash(f'Keyword "{keyword}" added successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding keyword: {str(e)}', 'error')
        
    return redirect(url_for('mw_admin_bp.service_keywords'))


@mw_admin_bp.route('/service-keywords/<int:kw_id>/toggle', methods=['POST'])
@admin_required
def toggle_service_keyword(kw_id):
    from ..models.service_keyword_model import ServiceKeyword
    kw = ServiceKeyword.query.get_or_404(kw_id)
    kw.is_active = not kw.is_active
    db.session.commit()
    state = 'activated' if kw.is_active else 'deactivated'
    flash(f'Keyword "{kw.keyword}" has been {state}.', 'success')
    return redirect(request.referrer or url_for('mw_admin_bp.service_keywords'))


@mw_admin_bp.route('/service-keywords/<int:kw_id>/delete', methods=['POST'])
@admin_required
def delete_service_keyword(kw_id):
    from ..models.service_keyword_model import ServiceKeyword
    kw = ServiceKeyword.query.get_or_404(kw_id)
    keyword = kw.keyword
    try:
        db.session.delete(kw)
        db.session.commit()
        flash(f'Keyword "{keyword}" has been deleted.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting keyword: {str(e)}', 'error')
        
    return redirect(url_for('mw_admin_bp.service_keywords'))


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


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@mw_admin_bp.route('/settings')
@admin_required
def settings():
    return render_template('admin/settings.html')


@mw_admin_bp.route('/settings/ai-chat', methods=['POST'])
@admin_required
def ai_chat():
    """Quick AI chat endpoint for testing the Groq model from the admin panel."""
    from ..services.ai_service import AIService, AIServiceError

    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify(success=False, error='Message is required.'), 400

    # Accept up to the last 2 prior exchanges for minimal context
    history = data.get('history', [])
    if not isinstance(history, list):
        history = []
    history = history[-4:]  # 2 exchanges = 4 messages (user+assistant each)

    try:
        ai = AIService()
        messages = history + [{"role": "user", "content": message}]
        reply = ai._call_groq(messages)
        return jsonify(success=True, reply=reply)
    except AIServiceError as e:
        return jsonify(success=False, error=str(e)), 502
    except Exception as e:
        return jsonify(success=False, error='An unexpected error occurred: ' + str(e)), 500

