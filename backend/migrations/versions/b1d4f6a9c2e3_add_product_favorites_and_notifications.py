"""Add product favorites and notifications

Revision ID: b1d4f6a9c2e3
Revises: 9f3d2c1b4a67
Create Date: 2026-02-23 19:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b1d4f6a9c2e3'
down_revision = '9f3d2c1b4a67'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notification',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('recipient_user_id', sa.Integer(), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('notification_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=160), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('related_shop_id', sa.Integer(), nullable=True),
        sa.Column('related_product_id', sa.Integer(), nullable=True),
        sa.Column('payload', sa.Text(), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['actor_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['recipient_user_id'], ['user.id'], ),
        sa.ForeignKeyConstraint(['related_product_id'], ['product.id'], ),
        sa.ForeignKeyConstraint(['related_shop_id'], ['shop.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notification_actor_user_id'), ['actor_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_is_read'), ['is_read'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_notification_type'), ['notification_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_recipient_user_id'), ['recipient_user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_related_product_id'), ['related_product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_notification_related_shop_id'), ['related_shop_id'], unique=False)

    op.create_table(
        'user_favorite_product',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('product_id', sa.Integer(), nullable=False),
        sa.Column('favorited_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['product_id'], ['product.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'product_id', name='unique_user_product_favorite')
    )
    with op.batch_alter_table('user_favorite_product', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_favorite_product_product_id'), ['product_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_user_favorite_product_user_id'), ['user_id'], unique=False)


def downgrade():
    with op.batch_alter_table('user_favorite_product', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_favorite_product_user_id'))
        batch_op.drop_index(batch_op.f('ix_user_favorite_product_product_id'))
    op.drop_table('user_favorite_product')

    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notification_related_shop_id'))
        batch_op.drop_index(batch_op.f('ix_notification_related_product_id'))
        batch_op.drop_index(batch_op.f('ix_notification_recipient_user_id'))
        batch_op.drop_index(batch_op.f('ix_notification_notification_type'))
        batch_op.drop_index(batch_op.f('ix_notification_is_read'))
        batch_op.drop_index(batch_op.f('ix_notification_created_at'))
        batch_op.drop_index(batch_op.f('ix_notification_actor_user_id'))
    op.drop_table('notification')
