"""add max_participants to events

Revision ID: f988d0d58b40
Revises: 20260131_222002
Create Date: 2026-01-31 22:36:08.228571

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f988d0d58b40'
down_revision: Union[str, Sequence[str], None] = '20260131_222002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add max_participants column to events table
    op.add_column('events', sa.Column('max_participants', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove max_participants column from events table
    op.drop_column('events', 'max_participants')
