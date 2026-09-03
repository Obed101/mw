"""add Cloudinary public ids to image records"""

from alembic import op
import sqlalchemy as sa


revision = 'ab12cd34ef56'
down_revision = ('91b7e4c2d5f0', 'c9e5fa2b7d11')
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('shop_image', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cloudinary_public_id', sa.String(length=255), nullable=True))
    with op.batch_alter_table('product_image', schema=None) as batch_op:
        batch_op.add_column(sa.Column('cloudinary_public_id', sa.String(length=255), nullable=True))


def downgrade():
    with op.batch_alter_table('product_image', schema=None) as batch_op:
        batch_op.drop_column('cloudinary_public_id')
    with op.batch_alter_table('shop_image', schema=None) as batch_op:
        batch_op.drop_column('cloudinary_public_id')
