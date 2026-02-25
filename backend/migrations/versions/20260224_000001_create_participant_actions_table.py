"""Create participant_actions table

Revision ID: 20260224_000001
Revises: 20260223_140820
Create Date: 2026-02-24 00:00:01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260224_000001'
down_revision = '20260223_140820'
branch_labels = None
depends_on = None


def upgrade():
    """Create participant_actions table for flexible task assignment system."""
    op.create_table(
        'participant_actions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(50), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('responded_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('response_note', sa.Text(), nullable=True),
        sa.Column('deadline', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('notification_sent', sa.Boolean(), default=False),
        sa.Column('notification_sent_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('metadata', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL')
    )

    # Create indexes for efficient querying
    op.create_index('ix_participant_actions_user_id', 'participant_actions', ['user_id'])
    op.create_index('ix_participant_actions_event_id', 'participant_actions', ['event_id'])
    op.create_index('ix_participant_actions_action_type', 'participant_actions', ['action_type'])
    op.create_index('ix_participant_actions_status', 'participant_actions', ['status'])


def downgrade():
    """Drop participant_actions table and indexes."""
    op.drop_table('participant_actions')
