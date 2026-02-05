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

    # Drop the unique constraint on year column if it exists
    # The constraint name may vary depending on how the table was created
    conn = op.get_bind()
    result = conn.execute(sa.text("""
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'events'
        AND constraint_type = 'UNIQUE'
        AND constraint_name LIKE '%year%'
    """))
    constraint_name = result.scalar()

    if constraint_name:
        op.drop_constraint(constraint_name, 'events', type_='unique')

        # Also drop the associated index if it exists with the same name
        index_result = conn.execute(sa.text("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'events'
            AND indexname = :index_name
        """), {"index_name": constraint_name})

        if index_result.scalar():
            op.drop_index(constraint_name, table_name='events')

    # Ensure we have a non-unique index on year for performance
    # Check if idx_events_year already exists
    index_check = conn.execute(sa.text("""
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'events'
        AND indexname = 'idx_events_year'
    """))

    if not index_check.scalar():
        op.create_index('idx_events_year', 'events', ['year'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    # Drop non-unique year index if it exists
    index_check = conn.execute(sa.text("""
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'events'
        AND indexname = 'idx_events_year'
    """))

    if index_check.scalar():
        op.drop_index('idx_events_year', table_name='events')

    # Restore unique constraint on year
    op.create_unique_constraint('events_year_key', 'events', ['year'])

    # Remove slug column and index
    op.drop_index('idx_events_slug', table_name='events')
    op.drop_column('events', 'slug')
