"""Add batch_id to participant_actions

Revision ID: 20260226_000000
Revises: 20260225_010000
Create Date: 2026-02-26 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260226_000000'
down_revision = '20260225_010000'
branch_labels = None
depends_on = None


def upgrade():
    """Add batch_id column to participant_actions table."""
    op.add_column('participant_actions',
        sa.Column('batch_id', sa.String(100), nullable=True)
    )
    op.create_index('ix_participant_actions_batch_id', 'participant_actions', ['batch_id'])


def downgrade():
    """Remove batch_id column from participant_actions table."""
    op.drop_index('ix_participant_actions_batch_id', table_name='participant_actions')
    op.drop_column('participant_actions', 'batch_id')
