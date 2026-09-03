"""add location fields to shop import staging records"""

from alembic import op
import sqlalchemy as sa


revision = "8c4f2a1b6d90"
down_revision = "7f2a6c1d9b40"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("shop_import", schema=None) as batch_op:
        batch_op.add_column(sa.Column("latitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("longitude", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("town", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("district", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("region", sa.String(length=100), nullable=True))


def downgrade():
    with op.batch_alter_table("shop_import", schema=None) as batch_op:
        batch_op.drop_column("region")
        batch_op.drop_column("district")
        batch_op.drop_column("town")
        batch_op.drop_column("longitude")
        batch_op.drop_column("latitude")
