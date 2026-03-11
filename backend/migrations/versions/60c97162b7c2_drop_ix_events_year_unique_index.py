"""drop_ix_events_year_unique_index

The original migration created year with unique=True, index=True which
generates a unique index named ix_events_year. Migration 4b6039cd8b1a
only looked for named UNIQUE constraints in information_schema, missing
this auto-generated unique index. This migration drops it and ensures
a non-unique index exists.

Revision ID: 60c97162b7c2
Revises: 20260311_000001
Create Date: 2026-03-11 12:45:16.649796

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '60c97162b7c2'
down_revision: Union[str, Sequence[str], None] = '20260311_000001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unique index ix_events_year and replace with non-unique."""
    conn = op.get_bind()

    # Check if ix_events_year exists (the auto-generated unique index)
    result = conn.execute(sa.text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'events'
        AND indexname = 'ix_events_year'
    """))
    row = result.first()

    if row:
        op.drop_index('ix_events_year', table_name='events')

    # Ensure a non-unique index exists for performance
    idx_check = conn.execute(sa.text("""
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'events'
        AND indexname = 'idx_events_year'
    """))

    if not idx_check.scalar():
        op.create_index('idx_events_year', 'events', ['year'], unique=False)


def downgrade() -> None:
    """Restore unique index on year."""
    conn = op.get_bind()

    # Drop non-unique index
    idx_check = conn.execute(sa.text("""
        SELECT indexname
        FROM pg_indexes
        WHERE tablename = 'events'
        AND indexname = 'idx_events_year'
    """))
    if idx_check.scalar():
        op.drop_index('idx_events_year', table_name='events')

    # Restore unique index
    op.create_index('ix_events_year', 'events', ['year'], unique=True)
