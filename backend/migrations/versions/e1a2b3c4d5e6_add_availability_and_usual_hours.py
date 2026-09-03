"""Add product availability freshness and shop usual hours."""
from alembic import op
import sqlalchemy as sa

revision = 'e1a2b3c4d5e6'
down_revision = 'd7f0a1b2c3d4'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('product', sa.Column('available', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('product', sa.Column('availability_updated_at', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_product_available', 'product', ['available'])
    op.create_index('ix_product_availability_updated_at', 'product', ['availability_updated_at'])
    op.add_column('shop', sa.Column('usual_opening_time', sa.Time(), nullable=True))
    op.add_column('shop', sa.Column('usual_closing_time', sa.Time(), nullable=True))

def downgrade():
    op.drop_column('shop', 'usual_closing_time')
    op.drop_column('shop', 'usual_opening_time')
    op.drop_index('ix_product_availability_updated_at', table_name='product')
    op.drop_index('ix_product_available', table_name='product')
    op.drop_column('product', 'availability_updated_at')
    op.drop_column('product', 'available')
