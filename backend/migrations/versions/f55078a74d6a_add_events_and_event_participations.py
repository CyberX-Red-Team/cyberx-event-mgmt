"""Add events and event_participations tables

Revision ID: f55078a74d6a
Revises: f10e06f02deb
Create Date: 2026-01-12 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f55078a74d6a'
down_revision: Union[str, Sequence[str], None] = 'f10e06f02deb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create events table
    op.create_table(
        'events',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('year', sa.Integer(), nullable=False, unique=True, index=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=True),
        sa.Column('end_date', sa.Date(), nullable=True),
        sa.Column('terms_version', sa.String(length=50), nullable=True),
        sa.Column('terms_content', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), default=False, nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create event_participations table
    op.create_table(
        'event_participations',
        sa.Column('id', sa.Integer(), primary_key=True, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('status', sa.String(length=20), default='invited', nullable=False),
        sa.Column('invited_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('invited_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('terms_accepted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('terms_version_accepted', sa.String(length=50), nullable=True),
        sa.Column('confirmed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('declined_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('declined_reason', sa.Text(), nullable=True),
        sa.Column('responded_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    # Create unique constraint for user_id + event_id combination
    op.create_unique_constraint(
        'uq_event_participations_user_event',
        'event_participations',
        ['user_id', 'event_id']
    )

    # Create indexes
    op.create_index('idx_event_participations_status', 'event_participations', ['status'])

    # Update existing users role from 'participant' to 'invitee'
    op.execute("UPDATE users SET role = 'invitee' WHERE role = 'participant'")


def downgrade() -> None:
    """Downgrade schema."""
    # Revert role change
    op.execute("UPDATE users SET role = 'participant' WHERE role = 'invitee'")

    # Drop indexes and constraints
    op.drop_index('idx_event_participations_status', table_name='event_participations')
    op.drop_constraint('uq_event_participations_user_event', 'event_participations', type_='unique')

    # Drop tables
    op.drop_table('event_participations')
    op.drop_table('events')
