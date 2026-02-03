"""add vpn_available to events

Revision ID: 20260201_000000
Revises: 20260131_235000
Create Date: 2026-02-01 00:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '20260201_000000'
down_revision = '20260131_235000'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add vpn_available field to events table
    op.add_column('events', sa.Column('vpn_available', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('events', 'vpn_available')
