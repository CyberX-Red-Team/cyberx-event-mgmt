"""add_event_time_and_location_fields

Revision ID: 6088bc3a22f2
Revises: ef4dc78cc32f
Create Date: 2026-02-02 14:48:26.370318

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6088bc3a22f2'
down_revision: Union[str, Sequence[str], None] = 'ef4dc78cc32f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add event_time and event_location fields to events table
    op.add_column('events', sa.Column('event_time', sa.String(length=255), nullable=True))
    op.add_column('events', sa.Column('event_location', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove event_time and event_location fields from events table
    op.drop_column('events', 'event_location')
    op.drop_column('events', 'event_time')
