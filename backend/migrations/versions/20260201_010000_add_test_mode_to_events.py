"""add test_mode to events

Revision ID: 20260201_010000
Revises: 20260201_000000
Create Date: 2026-02-01 01:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '20260201_010000'
down_revision = '20260201_000000'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add test_mode field to events table
    op.add_column('events', sa.Column('test_mode', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('events', 'test_mode')
