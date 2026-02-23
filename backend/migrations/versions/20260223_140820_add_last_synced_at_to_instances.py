"""Add last_synced_at to instances

Revision ID: 20260223_140820
Revises: 20260223_135934
Create Date: 2026-02-23 14:08:20

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260223_140820'
down_revision = '20260223_135934'
branch_labels = None
depends_on = None


def upgrade():
    """Add last_synced_at column to instances table for background sync tracking."""
    op.add_column('instances',
        sa.Column('last_synced_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )


def downgrade():
    """Remove last_synced_at column from instances table."""
    op.drop_column('instances', 'last_synced_at')
