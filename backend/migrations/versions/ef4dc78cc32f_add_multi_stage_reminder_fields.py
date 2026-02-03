"""add_multi_stage_reminder_fields

Revision ID: ef4dc78cc32f
Revises: 20260201_070000
Create Date: 2026-02-01 23:18:41.849521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef4dc78cc32f'
down_revision: Union[str, Sequence[str], None] = '20260201_070000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add multi-stage reminder tracking fields
    op.add_column('users', sa.Column('reminder_1_sent_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('reminder_2_sent_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('reminder_3_sent_at', sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove multi-stage reminder tracking fields
    op.drop_column('users', 'reminder_3_sent_at')
    op.drop_column('users', 'reminder_2_sent_at')
    op.drop_column('users', 'reminder_1_sent_at')
