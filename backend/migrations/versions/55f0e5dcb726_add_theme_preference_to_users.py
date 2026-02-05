"""add_theme_preference_to_users

Revision ID: 55f0e5dcb726
Revises: 7bbaa95e07cb
Create Date: 2026-02-05 02:06:02.263089

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '55f0e5dcb726'
down_revision: Union[str, Sequence[str], None] = '7bbaa95e07cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add theme_preference column with default value
    op.add_column('users', sa.Column('theme_preference', sa.String(length=10), server_default='light', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove theme_preference column
    op.drop_column('users', 'theme_preference')
