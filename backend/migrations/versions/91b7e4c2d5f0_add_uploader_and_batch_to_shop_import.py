"""add uploader and batch identity to shop import staging records"""

from alembic import op
import sqlalchemy as sa


revision = "91b7e4c2d5f0"
down_revision = "8c4f2a1b6d90"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("shop_import", schema=None) as batch_op:
        batch_op.add_column(sa.Column("uploader_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("import_batch", sa.String(length=100), nullable=True))
        batch_op.create_index("ix_shop_import_uploader_user_id", ["uploader_user_id"], unique=False)
        batch_op.create_index("ix_shop_import_import_batch", ["import_batch"], unique=False)
        batch_op.create_foreign_key(
            "fk_shop_import_uploader_user_id_user",
            "user",
            ["uploader_user_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("shop_import", schema=None) as batch_op:
        batch_op.drop_constraint("fk_shop_import_uploader_user_id_user", type_="foreignkey")
        batch_op.drop_index("ix_shop_import_import_batch")
        batch_op.drop_index("ix_shop_import_uploader_user_id")
        batch_op.drop_column("import_batch")
        batch_op.drop_column("uploader_user_id")
