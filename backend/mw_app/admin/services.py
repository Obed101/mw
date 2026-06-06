"""
Admin business logic / service layer.
Keeps routes thin and logic testable.
"""
from datetime import datetime, timezone
from ..extensions import db
from ..models import User, Role, UserRole, Shop, Product
from ..models.role_model import ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_USER


# ---------------------------------------------------------------------------
# Role seeding
# ---------------------------------------------------------------------------

def ensure_super_admin_exists():
    """
    Called on startup: if no super_admin exists at all, make user id=1 one.
    Safe to call repeatedly — idempotent.
    """
    super_admin_role = Role.query.filter_by(name=ROLE_SUPER_ADMIN).first()
    if super_admin_role and UserRole.query.filter_by(role_id=super_admin_role.id).count() > 0:
        return  # Already have at least one super_admin

    user_one = User.query.filter_by(username="Obed101").first()
    if not user_one:
        return  # No users yet — will be assigned when first user is created

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
    role = Role.get_or_create(role_name)
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
    db.session.flush()
    return True


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
