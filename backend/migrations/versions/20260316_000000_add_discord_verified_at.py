"""Add discord_verified_at to event_participations

Per-event tracking of when a user completed Discord bot verification,
separate from discord_invite_used_at (which tracks Discord join link usage).

Revision ID: 20260316_000000
Revises: 20260314_000000
Create Date: 2026-03-16 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260316_000000'
down_revision = '20260314_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'event_participations',
        sa.Column('discord_verified_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('event_participations', 'discord_verified_at')
