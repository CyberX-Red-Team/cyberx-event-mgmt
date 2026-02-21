"""Add SSH keys to events

Revision ID: 20260221_000000
Revises: 20260220_000000
Create Date: 2026-02-21 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260221_000000'
down_revision = '20260220_000000'
branch_labels = None
depends_on = None


def upgrade():
    # Add SSH key columns to events table
    op.add_column('events', sa.Column('ssh_public_key', sa.Text(), nullable=True))
    op.add_column('events', sa.Column('ssh_private_key', sa.Text(), nullable=True))


def downgrade():
    # Remove SSH key columns from events table
    op.drop_column('events', 'ssh_private_key')
    op.drop_column('events', 'ssh_public_key')
