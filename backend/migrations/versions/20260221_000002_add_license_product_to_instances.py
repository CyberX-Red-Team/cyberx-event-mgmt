"""Add license_product_id to instances

Revision ID: 20260221_000002
Revises: 20260221_000001
Create Date: 2026-02-21 00:00:02.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260221_000002'
down_revision = '20260221_000001'
branch_labels = None
depends_on = None


def upgrade():
    # Add license_product_id column to instances table
    op.add_column('instances', sa.Column('license_product_id', sa.Integer(), nullable=True))
    op.create_index('ix_instances_license_product_id', 'instances', ['license_product_id'])
    op.create_foreign_key(
        'fk_instances_license_product_id',
        'instances', 'license_products',
        ['license_product_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    # Remove license_product_id column from instances table
    op.drop_constraint('fk_instances_license_product_id', 'instances', type_='foreignkey')
    op.drop_index('ix_instances_license_product_id', 'instances')
    op.drop_column('instances', 'license_product_id')
