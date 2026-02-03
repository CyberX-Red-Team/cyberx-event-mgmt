"""add email queue tables

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2024-01-31 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c3d4e5f6g7h8'
down_revision = 'b2c3d4e5f6g7'
branch_labels = None
depends_on = None


def upgrade():
    # Create email_queue table
    op.create_table(
        'email_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('template_name', sa.String(length=100), nullable=False),
        sa.Column('recipient_email', sa.String(length=255), nullable=False),
        sa.Column('recipient_name', sa.String(length=500), nullable=True),
        sa.Column('custom_vars', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('last_attempt_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('sendgrid_message_id', sa.String(length=255), nullable=True),
        sa.Column('batch_id', sa.String(length=100), nullable=True),
        sa.Column('processed_by', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('scheduled_for', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('processed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('sent_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes for email_queue
    op.create_index('idx_email_queue_user_id', 'email_queue', ['user_id'])
    op.create_index('idx_email_queue_recipient_email', 'email_queue', ['recipient_email'])
    op.create_index('idx_email_queue_status', 'email_queue', ['status'])
    op.create_index('idx_email_queue_priority', 'email_queue', ['priority'])
    op.create_index('idx_email_queue_batch_id', 'email_queue', ['batch_id'])
    op.create_index('idx_email_queue_created_at', 'email_queue', ['created_at'])
    op.create_index('idx_email_queue_scheduled', 'email_queue', ['status', 'scheduled_for'])
    op.create_index('idx_email_queue_status_priority', 'email_queue', ['status', 'priority', 'created_at'])
    op.create_index('idx_email_queue_processing', 'email_queue', ['status', 'attempts', 'max_attempts'])

    # Create email_batch_logs table
    op.create_table(
        'email_batch_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('batch_id', sa.String(length=100), nullable=False),
        sa.Column('batch_size', sa.Integer(), nullable=False),
        sa.Column('total_processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_sent', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('processed_by', sa.String(length=100), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('batch_id')
    )

    # Create indexes for email_batch_logs
    op.create_index('idx_email_batch_logs_batch_id', 'email_batch_logs', ['batch_id'])


def downgrade():
    # Drop indexes
    op.drop_index('idx_email_batch_logs_batch_id', table_name='email_batch_logs')
    op.drop_index('idx_email_queue_processing', table_name='email_queue')
    op.drop_index('idx_email_queue_status_priority', table_name='email_queue')
    op.drop_index('idx_email_queue_scheduled', table_name='email_queue')
    op.drop_index('idx_email_queue_created_at', table_name='email_queue')
    op.drop_index('idx_email_queue_batch_id', table_name='email_queue')
    op.drop_index('idx_email_queue_priority', table_name='email_queue')
    op.drop_index('idx_email_queue_status', table_name='email_queue')
    op.drop_index('idx_email_queue_recipient_email', table_name='email_queue')
    op.drop_index('idx_email_queue_user_id', table_name='email_queue')

    # Drop tables
    op.drop_table('email_batch_logs')
    op.drop_table('email_queue')
