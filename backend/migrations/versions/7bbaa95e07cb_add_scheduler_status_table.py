"""add scheduler status table

Revision ID: 7bbaa95e07cb
Revises: 9f7eb369cee0
Create Date: 2026-02-05 00:37:57.529330

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7bbaa95e07cb'
down_revision: Union[str, Sequence[str], None] = '9f7eb369cee0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'scheduler_status',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('service_name', sa.String(100), nullable=False, unique=True),
        sa.Column('is_running', sa.Boolean(), nullable=False, default=False),
        sa.Column('jobs', sa.JSON(), nullable=False, default=list),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('scheduler_status')
