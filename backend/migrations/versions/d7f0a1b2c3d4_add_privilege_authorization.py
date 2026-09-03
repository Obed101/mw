"""Add relational roles, privileges, effective user grants and audit log."""
from alembic import op
import sqlalchemy as sa

revision = 'd7f0a1b2c3d4'
down_revision = 'ab12cd34ef56'
branch_labels = None
depends_on = None

PRIVILEGES = ('manage_users', 'manage_roles', 'manage_privileges', 'assign_roles',
              'assign_privileges', 'manage_shops', 'edit_unowned_shops', 'verify_shops',
              'moderate_content', 'view_reports', 'manage_promotions', 'edit_super_admin',
              'reply_support_messages')


def upgrade():
    op.add_column('user', sa.Column('role_id', sa.Integer(), nullable=True))
    op.create_index('ix_user_role_id', 'user', ['role_id'])
    op.create_foreign_key('fk_user_role_id', 'user', 'role', ['role_id'], ['id'], ondelete='SET NULL')
    op.add_column('role', sa.Column('description', sa.Text(), nullable=True))
    op.create_table('privilege',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('key', sa.String(100), nullable=False),
        sa.Column('name', sa.String(120), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('key'))
    op.create_index('ix_privilege_key', 'privilege', ['key'], unique=True)
    op.create_table('role_privilege',
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('role.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('privilege_id', sa.Integer(), sa.ForeignKey('privilege.id', ondelete='CASCADE'), primary_key=True))
    op.create_index('ix_role_privilege_privilege_id', 'role_privilege', ['privilege_id'])
    op.create_table('user_privilege',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('privilege_id', sa.Integer(), sa.ForeignKey('privilege.id', ondelete='CASCADE'), primary_key=True))
    op.create_index('ix_user_privilege_privilege_id', 'user_privilege', ['privilege_id'])
    op.create_table('authorization_audit_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
        sa.Column('action', sa.String(80), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='SET NULL')),
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('role.id', ondelete='SET NULL')),
        sa.Column('privilege_id', sa.Integer(), sa.ForeignKey('privilege.id', ondelete='SET NULL')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('details', sa.JSON()))
    op.create_index('ix_authorization_audit_log_created_at', 'authorization_audit_log', ['created_at'])
    op.create_index('ix_authorization_audit_log_actor_id', 'authorization_audit_log', ['actor_id'])
    op.create_index('ix_authorization_audit_log_user_id', 'authorization_audit_log', ['user_id'])
    op.create_index('ix_authorization_audit_log_action', 'authorization_audit_log', ['action'])
    privilege_table = sa.table('privilege', sa.column('key', sa.String), sa.column('name', sa.String),
                               sa.column('description', sa.Text), sa.column('created_at', sa.DateTime))
    from datetime import datetime, timezone
    op.bulk_insert(privilege_table, [dict(key=p, name=p.replace('_', ' ').title(), description=p.replace('_', ' ').title(),
                         created_at=datetime.now(timezone.utc)) for p in PRIVILEGES])


def downgrade():
    op.drop_table('authorization_audit_log')
    op.drop_table('user_privilege')
    op.drop_table('role_privilege')
    op.drop_index('ix_privilege_key', table_name='privilege')
    op.drop_table('privilege')
    op.drop_column('role', 'description')
    op.drop_constraint('fk_user_role_id', 'user', type_='foreignkey')
    op.drop_index('ix_user_role_id', table_name='user')
    op.drop_column('user', 'role_id')
