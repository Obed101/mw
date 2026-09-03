"""Add specifications field to product

Revision ID: add_product_specifications
Revises: d381d2797417
Create Date: 2026-06-24 13:48:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_product_specifications'
down_revision = 'd381d2797417'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('product', sa.Column('specifications', sa.Text(), nullable=True))


def downgrade():
    op.drop_column('product', 'specifications')
