"""
Admin business logic / service layer.
Keeps routes thin and logic testable.
"""
from datetime import datetime, timezone
from ..extensions import db
from ..models import User, Role, UserRole, Privilege, AuthorizationAuditLog, Shop, Product
from ..models.role_model import ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_USER


# ---------------------------------------------------------------------------
# Role seeding
# ---------------------------------------------------------------------------

def ensure_super_admin_exists():
    """
    Called on startup: if no super_admin exists at all, make user id=1 one.
    Safe to call repeatedly — idempotent.
    """
    # User id=1 is the designated bootstrap administrator. Keep the username
    # fallback for databases created before the fixed identity was established.
    user_one = User.query.get(1) or User.query.filter_by(username="Obed101").first()
    if not user_one:
        return  # No users yet — will be assigned when first user is created

    if user_one.is_super_admin():
        if not user_one.admin_mode:
            user_one.admin_mode = True
            db.session.commit()
        return

    assign_role(user_one, ROLE_SUPER_ADMIN, assigned_by_id=user_one.id)
    # Also enable admin_mode so they can immediately access admin
    user_one.admin_mode = True
    db.session.commit()


# ---------------------------------------------------------------------------
# Role assignment
# ---------------------------------------------------------------------------

def assign_role(user, role_name, assigned_by_id=None):
    """
    Assign a named role to a user (idempotent).
    Returns the UserRole object.
    """
    previous_role = user.authorization_role
    role = Role.get_or_create(role_name)
    # The authorization model is intentionally one role per user.
    user.role_id = role.id
    if role_name == 'seller':
        user.role = 'seller'
    elif role_name in [ROLE_SUPER_ADMIN, ROLE_ADMIN]:
        user.role = 'admin'
    existing = UserRole.query.filter_by(user_id=user.id, role_id=role.id).first()
    if existing:
        return existing

    user_role = UserRole(
        user_id=user.id,
        role_id=role.id,
        assigned_by=assigned_by_id,
        assigned_at=datetime.now(timezone.utc),
    )
    db.session.add(user_role)
    db.session.flush()
    synchronize_user_privileges(user, removed_role=previous_role if previous_role and previous_role.id != role.id else None)
    _audit('role_assigned', actor_id=assigned_by_id, user_id=user.id, role_id=role.id)
    return user_role


def remove_role(user, role_name):
    """Remove a named role from a user. Returns True if removed, False if not found."""
    role = Role.query.filter_by(name=role_name).first()
    if not role:
        return False
    user_role = UserRole.query.filter_by(user_id=user.id, role_id=role.id).first()
    if not user_role:
        return False
    db.session.delete(user_role)
    if user.role_id == role.id:
        user.role_id = None
        if user.role in ('admin', 'seller'):
            user.role = 'buyer'
    synchronize_user_privileges(user, removed_role=role)
    db.session.flush()
    _audit('role_removed', user_id=user.id, role_id=role.id)
    return True


def _audit(action, actor_id=None, user_id=None, role_id=None, privilege_id=None, details=None):
    db.session.add(AuthorizationAuditLog(actor_id=actor_id, action=action,
        user_id=user_id, role_id=role_id, privilege_id=privilege_id, details=details))


def synchronize_user_privileges(user, removed_role=None):
    """Make effective privileges exactly match the user's current role plus direct grants."""
    target = set(user.authorization_role.privileges if user.authorization_role else [])
    # Direct privileges are retained when changing a role; removal of a role
    # removes that role's grants, while explicit grants remain explicit.
    current = set(user.privileges)
    if removed_role:
        current -= set(removed_role.privileges)
    user.privileges = list((current | target))
    db.session.flush()


def assign_privilege(user, privilege, actor_id=None):
    privilege = privilege if isinstance(privilege, Privilege) else Privilege.query.filter_by(key=privilege).first()
    if not privilege or privilege in user.privileges:
        return False
    user.privileges.append(privilege)
    _audit('privilege_assigned', actor_id=actor_id, user_id=user.id, privilege_id=privilege.id)
    db.session.flush()
    return True


def remove_privilege(user, privilege, actor_id=None):
    privilege = privilege if isinstance(privilege, Privilege) else Privilege.query.filter_by(key=privilege).first()
    if not privilege or privilege not in user.privileges:
        return False
    user.privileges.remove(privilege)
    _audit('privilege_removed', actor_id=actor_id, user_id=user.id, privilege_id=privilege.id)
    db.session.flush()
    return True


INITIAL_PRIVILEGES = {
    'manage_users': 'Manage users', 'manage_roles': 'Manage roles',
    'manage_privileges': 'Manage privileges', 'assign_roles': 'Assign roles',
    'assign_privileges': 'Assign individual privileges', 'manage_shops': 'Manage shops',
    'edit_unowned_shops': 'Edit shops not owned by the user', 'verify_shops': 'Verify shops',
    'moderate_content': 'Moderate content', 'view_reports': 'View reports',
    'manage_promotions': 'Manage promotions', 'edit_super_admin': 'Manage super admins',
    'reply_support_messages': 'Reply to support messages',
}

ROLE_SEEDS = {
    ROLE_SUPER_ADMIN: ('Unrestricted platform administrator', set(INITIAL_PRIVILEGES)),
    ROLE_ADMIN: ('Platform administrator', set(INITIAL_PRIVILEGES) - {'edit_super_admin'}),
    'seller': ('Shop owner dashboard access', set()),
    ROLE_USER: ('Standard Market Window user', set()),
}


def seed_privileges():
    """Idempotently create the catalogue and the standard role bundles."""
    privilege_map = {}
    for key, description in INITIAL_PRIVILEGES.items():
        privilege = Privilege.query.filter_by(key=key).first()
        if not privilege:
            privilege = Privilege(key=key, name=description, description=description)
            db.session.add(privilege)
        privilege_map[key] = privilege
    db.session.flush()
    for role_name, (description, keys) in ROLE_SEEDS.items():
        role = Role.get_or_create(role_name)
        role.description = role.description or description
        old_privileges = set(role.privileges)
        role.privileges = [privilege_map[key] for key in keys if key in privilege_map]
        added = set(role.privileges) - old_privileges
        removed = old_privileges - set(role.privileges)
        for user in list(role.users):
            for privilege in added:
                if privilege not in user.privileges:
                    user.privileges.append(privilege)
            for privilege in removed:
                if privilege in user.privileges:
                    user.privileges.remove(privilege)
    # Adopt legacy assignments created before role_id existed.
    for assignment in UserRole.query.order_by(UserRole.assigned_at.desc()).all():
        if assignment.user and assignment.user.role_id is None:
            assignment.user.role_id = assignment.role_id
            synchronize_user_privileges(assignment.user)
    db.session.commit()


def set_role_privileges(role, privileges, actor_id=None):
    """Replace role membership and immediately synchronize every assigned user."""
    old_privileges = set(role.privileges)
    new_privileges = set(privileges)
    role.privileges = list(dict.fromkeys(privileges))
    db.session.flush()
    added = new_privileges - old_privileges
    removed = old_privileges - new_privileges
    for user in list(role.users):
        for privilege in added:
            if privilege not in user.privileges:
                user.privileges.append(privilege)
        for privilege in removed:
            if privilege in user.privileges:
                user.privileges.remove(privilege)
    _audit('role_privileges_changed', actor_id=actor_id, role_id=role.id)
    db.session.flush()


def toggle_admin_mode(user):
    """Flip admin_mode for the given user. Returns new value."""
    user.admin_mode = not bool(user.admin_mode)
    db.session.commit()
    return user.admin_mode


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

def get_dashboard_stats():
    """Return aggregate counts and recent records for the admin dashboard."""
    total_users = User.query.count()

    # Count of users who have admin or super_admin UserRole
    admin_role_ids = [
        r.id for r in Role.query.filter(Role.name.in_([ROLE_ADMIN, ROLE_SUPER_ADMIN])).all()
    ]
    total_admins = (
        db.session.query(db.func.count(db.func.distinct(UserRole.user_id)))
        .filter(UserRole.role_id.in_(admin_role_ids))
        .scalar()
        if admin_role_ids else 0
    )

    total_shops = Shop.query.count()
    total_products = Product.query.count()

    recent_users = (
        User.query
        .order_by(User.created_at.desc())
        .limit(8)
        .all()
    )
    recent_products = (
        Product.query
        .order_by(Product.created_at.desc())
        .limit(8)
        .all()
    )

    return {
        'total_users': total_users,
        'total_admins': total_admins,
        'total_shops': total_shops,
        'total_products': total_products,
        'recent_users': recent_users,
        'recent_products': recent_products,
    }


# ---------------------------------------------------------------------------
# Pagination helper
# ---------------------------------------------------------------------------

def paginate_query(query, page, per_page=20):
    """Return a SQLAlchemy pagination object."""
    return query.paginate(page=page, per_page=per_page, error_out=False)


def ensure_service_keywords_seeded():
    """
    Called on startup: seeds the service keywords database if empty.
    """
    from ..models.service_keyword_model import ServiceKeyword
    if ServiceKeyword.query.first():
        return  # Already seeded

    keywords = [
        "school", "academy", "university", "college", "bank", "microfinance",
        "finance", "insurance", "repair", "mechanic", "barber", "salon",
        "spa", "washing bay", "filling station", "fuel station", "pharmacy",
        "clinic", "hospital", "dental", "hotel", "hostel", "restaurant",
        "cafe", "printing", "tailoring", "tailor", "sewing", "church",
        "mosque", "welding", "electrician", "plumbing", "laundry", "transport",
        "delivery", "internet cafe", "mobile money", "momo", "consultancy",
        "agency", "studio", "gym", "fitness", "coaching", "driving school",
        "computer training", "repair center", "service center", "forex",
        "forex bureau", "lodge", "event center", "decoration", "photography",
        "videography", "car wash", "vulcanizer", "tire service", "alignment",
        "diagnostics", "towing", "software", "cyber cafe"
    ]
    
    for kw in keywords:
        existing = ServiceKeyword.query.filter_by(keyword=kw).first()
        if not existing:
            db.session.add(ServiceKeyword(keyword=kw, is_active=True))
    db.session.commit()
