"""Authorization models and their relational assignments."""
from datetime import datetime, timezone
from ..extensions import db

ROLE_SUPER_ADMIN = 'super_admin'
ROLE_ADMIN = 'admin'
ROLE_USER = 'user'
VALID_ROLES = {ROLE_SUPER_ADMIN, ROLE_ADMIN, ROLE_USER, 'seller'}
ADMIN_ROLES = {ROLE_SUPER_ADMIN, ROLE_ADMIN}

role_privileges = db.Table(
    'role_privilege',
    db.Column('role_id', db.Integer, db.ForeignKey('role.id', ondelete='CASCADE'), primary_key=True),
    db.Column('privilege_id', db.Integer, db.ForeignKey('privilege.id', ondelete='CASCADE'), primary_key=True),
    db.Index('ix_role_privilege_privilege_id', 'privilege_id'),
)

user_privileges = db.Table(
    'user_privilege',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
    db.Column('privilege_id', db.Integer, db.ForeignKey('privilege.id', ondelete='CASCADE'), primary_key=True),
    db.Index('ix_user_privilege_privilege_id', 'privilege_id'),
)


class Privilege(db.Model):
    __tablename__ = 'privilege'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=True)
    description = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    roles = db.relationship('Role', secondary=role_privileges, back_populates='privileges')
    users = db.relationship('User', secondary=user_privileges, back_populates='privileges')

    def __repr__(self):
        return f'<Privilege {self.key}>'


class Role(db.Model):
    __tablename__ = 'role'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.Text, nullable=True)
    privileges = db.relationship('Privilege', secondary=role_privileges, back_populates='roles')
    users = db.relationship('User', back_populates='authorization_role', foreign_keys='User.role_id')
    user_roles = db.relationship('UserRole', back_populates='role', cascade='all, delete-orphan')

    @classmethod
    def get_or_create(cls, name):
        role = cls.query.filter_by(name=name).first()
        if not role:
            role = cls(name=name)
            db.session.add(role)
            db.session.flush()
        return role

    def __repr__(self):
        return f'<Role {self.name}>'

    def set_privileges(self, privileges):
        """Replace membership and synchronize assigned users immediately."""
        from ..admin.services import set_role_privileges
        set_role_privileges(self, privileges)

    def add_privilege(self, privilege):
        if privilege not in self.privileges:
            from ..admin.services import set_role_privileges
            set_role_privileges(self, list(self.privileges) + [privilege])

    def remove_privilege(self, privilege):
        if privilege in self.privileges:
            from ..admin.services import set_role_privileges
            set_role_privileges(self, [p for p in self.privileges if p != privilege])


class UserRole(db.Model):
    """Legacy assignment history/compatibility table; new assignments are one role_id."""
    __tablename__ = 'user_role'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id', ondelete='CASCADE'), nullable=False)
    assigned_by = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    assigned_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'role_id', name='uq_user_role'),)
    user = db.relationship('User', foreign_keys=[user_id], back_populates='user_roles')
    role = db.relationship('Role', back_populates='user_roles')
    assigner = db.relationship('User', foreign_keys=[assigned_by])


class AuthorizationAuditLog(db.Model):
    __tablename__ = 'authorization_audit_log'
    id = db.Column(db.Integer, primary_key=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    action = db.Column(db.String(80), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True, index=True)
    role_id = db.Column(db.Integer, db.ForeignKey('role.id', ondelete='SET NULL'), nullable=True)
    privilege_id = db.Column(db.Integer, db.ForeignKey('privilege.id', ondelete='SET NULL'), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    details = db.Column(db.JSON, nullable=True)
