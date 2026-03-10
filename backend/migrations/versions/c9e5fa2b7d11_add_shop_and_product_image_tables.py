"""Add shop and product image tables

Revision ID: c9e5fa2b7d11
Revises: b1d4f6a9c2e3
Create Date: 2026-02-24 20:05:00.000000

"""
from datetime import datetime
import json

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9e5fa2b7d11"
down_revision = "b1d4f6a9c2e3"
branch_labels = None
depends_on = None

MAX_PRODUCT_IMAGES = 10


def _parse_legacy_images(raw_value):
    if not raw_value:
        return []

    serialized = str(raw_value).strip()
    if not serialized:
        return []

    try:
        loaded = json.loads(serialized)
        if isinstance(loaded, list):
            candidates = loaded
        elif isinstance(loaded, str):
            candidates = [loaded]
        else:
            candidates = []
    except (json.JSONDecodeError, TypeError, ValueError):
        candidates = serialized.split(",")

    normalized = []
    seen = set()
    for candidate in candidates:
        cleaned = str(candidate).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def upgrade():
    op.create_table(
        "shop_image",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["shop_id"], ["shop.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("shop_id", "storage_key", name="uq_shop_image_shop_storage"),
    )
    with op.batch_alter_table("shop_image", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_shop_image_shop_id"), ["shop_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_shop_image_sort_order"), ["sort_order"], unique=False)
        batch_op.create_index(batch_op.f("ix_shop_image_is_primary"), ["is_primary"], unique=False)

    op.create_table(
        "product_image",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["product.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "storage_key", name="uq_product_image_product_storage"),
    )
    with op.batch_alter_table("product_image", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_product_image_product_id"), ["product_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_product_image_sort_order"), ["sort_order"], unique=False)
        batch_op.create_index(batch_op.f("ix_product_image_is_primary"), ["is_primary"], unique=False)

    bind = op.get_bind()
    product_table = sa.table(
        "product",
        sa.column("id", sa.Integer()),
        sa.column("images", sa.Text()),
    )
    product_image_table = sa.table(
        "product_image",
        sa.column("product_id", sa.Integer()),
        sa.column("storage_key", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_primary", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
    )

    rows = bind.execute(
        sa.select(product_table.c.id, product_table.c.images).where(
            product_table.c.images.isnot(None)
        )
    ).fetchall()

    now = datetime.utcnow()
    payload = []
    for product_id, raw_images in rows:
        image_keys = _parse_legacy_images(raw_images)[:MAX_PRODUCT_IMAGES]
        for idx, image_key in enumerate(image_keys):
            payload.append(
                {
                    "product_id": product_id,
                    "storage_key": image_key,
                    "sort_order": idx,
                    "is_primary": (idx == 0),
                    "created_at": now,
                }
            )

    if payload:
        bind.execute(product_image_table.insert(), payload)

    with op.batch_alter_table("shop_image", schema=None) as batch_op:
        batch_op.alter_column("sort_order", server_default=None)
        batch_op.alter_column("is_primary", server_default=None)
    with op.batch_alter_table("product_image", schema=None) as batch_op:
        batch_op.alter_column("sort_order", server_default=None)
        batch_op.alter_column("is_primary", server_default=None)


def downgrade():
    with op.batch_alter_table("product_image", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_product_image_is_primary"))
        batch_op.drop_index(batch_op.f("ix_product_image_sort_order"))
        batch_op.drop_index(batch_op.f("ix_product_image_product_id"))
    op.drop_table("product_image")

    with op.batch_alter_table("shop_image", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_shop_image_is_primary"))
        batch_op.drop_index(batch_op.f("ix_shop_image_sort_order"))
        batch_op.drop_index(batch_op.f("ix_shop_image_shop_id"))
    op.drop_table("shop_image")
