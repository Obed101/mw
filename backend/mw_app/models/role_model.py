from datetime import datetime, timezone
from ..extensions import db

# Role name constants
ROLE_SUPER_ADMIN = 'super_admin'
ROLE_ADMIN = 'admin'
ROLE_USER = 'user'

VALID_ROLES = {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_USER}
ADMIN_ROLES = {ROLE_SUPER_ADMIN, ROLE_ADMIN}


class Role(db.Model):
    """Named role — super_admin, admin, user."""
    __tablename__ = 'role'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)

    user_roles = db.relationship('UserRole', back_populates='role', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Role {self.name}>'

    @classmethod
    def get_or_create(cls, name):
        """Return existing role or create it."""
        if name not in VALID_ROLES:
            raise ValueError(f'Invalid role: {name}')
        role = cls.query.filter_by(name=name).first()
        if not role:
            role = cls(name=name)
            db.session.add(role)
            db.session.flush()
        return role


class UserRole(db.Model):
    """Many-to-many: a user can hold multiple named roles."""
    __tablename__ = 'user_role'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id', ondelete='CASCADE'), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    assigned_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    # Unique: one user, one role entry
    __table_args__ = (
        db.UniqueConstraint('user_id', 'role_id', name='uq_user_role'),
    )

    user = db.relationship('User', foreign_keys=[user_id], back_populates='user_roles')
    role = db.relationship('Role', back_populates='user_roles')
    assigner = db.relationship('User', foreign_keys=[assigned_by])

    def __repr__(self):
        return f'<UserRole user:{self.user_id} role:{self.role.name if self.role else self.role_id}>'
