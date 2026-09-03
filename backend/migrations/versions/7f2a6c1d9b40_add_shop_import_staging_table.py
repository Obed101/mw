"""add shop import staging table"""

from alembic import op
import sqlalchemy as sa


revision = "7f2a6c1d9b40"
down_revision = "f0564dbdd960"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shop_import",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("phone_number", sa.String(length=20), nullable=True),
        sa.Column("closing_time", sa.String(length=100), nullable=True),
        sa.Column("plus_code", sa.String(length=30), nullable=True),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("delivery", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("import_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("shop_import")
