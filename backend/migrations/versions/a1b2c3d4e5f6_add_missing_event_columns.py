"""Add missing event columns

Revision ID: a1b2c3d4e5f6
Revises: f55078a74d6a
Create Date: 2026-01-12 22:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f55078a74d6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add missing columns to events table only
    op.add_column('events', sa.Column('registration_opens', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('events', sa.Column('registration_closes', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('events', sa.Column('terms_updated_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('events', sa.Column('is_archived', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove columns from events
    op.drop_column('events', 'is_archived')
    op.drop_column('events', 'terms_updated_at')
    op.drop_column('events', 'registration_closes')
    op.drop_column('events', 'registration_opens')
