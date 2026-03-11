"""Add discord invite fields to events and event_participations

Revision ID: 20260227_000001
Revises: 20260227_000000
Create Date: 2026-02-27 00:00:01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260227_000001'
down_revision = '20260227_000000'
branch_labels = None
depends_on = None


def upgrade():
    """Add discord_channel_id to events and invite fields to event_participations."""
    # Add discord_channel_id to events table
    op.add_column('events',
        sa.Column('discord_channel_id', sa.String(100), nullable=True)
    )

    # Add discord invite fields to event_participations table
    op.add_column('event_participations',
        sa.Column('discord_invite_code', sa.String(50), nullable=True)
    )
    op.add_column('event_participations',
        sa.Column('discord_invite_generated_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )
    op.add_column('event_participations',
        sa.Column('discord_invite_used_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )


def downgrade():
    """Remove discord invite fields."""
    op.drop_column('event_participations', 'discord_invite_used_at')
    op.drop_column('event_participations', 'discord_invite_generated_at')
    op.drop_column('event_participations', 'discord_invite_code')
    op.drop_column('events', 'discord_channel_id')
