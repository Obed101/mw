"""Add gps column to shop

Revision ID: 9f3d2c1b4a67
Revises: f6360740b787
Create Date: 2026-02-18 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9f3d2c1b4a67'
down_revision = 'f6360740b787'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('shop', schema=None) as batch_op:
        batch_op.add_column(sa.Column('gps', sa.String(length=64), nullable=True))


def downgrade():
    with op.batch_alter_table('shop', schema=None) as batch_op:
        batch_op.drop_column('gps')
