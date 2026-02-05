"""add_event_slug_and_remove_year_unique_constraint

Revision ID: 4b6039cd8b1a
Revises: 55f0e5dcb726
Create Date: 2026-02-05 12:27:38.860080

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4b6039cd8b1a'
down_revision: Union[str, Sequence[str], None] = '55f0e5dcb726'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add slug column (nullable initially to allow data population)
    op.add_column('events', sa.Column('slug', sa.String(255), nullable=True))

    # Generate slug for existing events based on their names
    # Convert to lowercase, replace spaces with hyphens, remove special chars
    op.execute("""
        UPDATE events
        SET slug = LOWER(
            REGEXP_REPLACE(
                REGEXP_REPLACE(name, '[^a-zA-Z0-9\\s-]', '', 'g'),
                '\\s+', '-', 'g'
            )
        )
    """)

    # Now make slug NOT NULL and add unique constraint
    op.alter_column('events', 'slug', nullable=False)
    op.create_index('idx_events_slug', 'events', ['slug'], unique=True)

    # Drop the unique constraint on year column
    # Note: PostgreSQL automatically creates an index for unique constraints
    # We need to find and drop both the constraint and index
    op.drop_constraint('events_year_key', 'events', type_='unique')

    # Keep the year index for filtering, but make it non-unique
    # The unique constraint automatically created an index, so we need to recreate it as non-unique
    op.drop_index('events_year_key', table_name='events')
    op.create_index('idx_events_year', 'events', ['year'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Restore unique constraint on year
    op.drop_index('idx_events_year', table_name='events')
    op.create_unique_constraint('events_year_key', 'events', ['year'])

    # Remove slug column and index
    op.drop_index('idx_events_slug', table_name='events')
    op.drop_column('events', 'slug')
