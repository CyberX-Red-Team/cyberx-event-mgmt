"""Add keycloak sync queue table and keycloak_synced column to users

Revision ID: 20260227_000000
Revises: 20260226_000000
Create Date: 2026-02-27 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260227_000000'
down_revision = '20260226_000000'
branch_labels = None
depends_on = None


def upgrade():
    """Create password_sync_queue table and add keycloak_synced to users."""
    # Create password_sync_queue table
    op.create_table(
        'password_sync_queue',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(255), nullable=False),
        sa.Column('encrypted_password', sa.Text(), nullable=True),
        sa.Column('operation', sa.String(50), nullable=False, server_default='create_user'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('synced', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('synced_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_password_sync_queue_synced', 'password_sync_queue', ['synced'])
    op.create_index('idx_password_sync_queue_user_id', 'password_sync_queue', ['user_id'])

    # Add keycloak_synced column to users table
    op.add_column('users',
        sa.Column('keycloak_synced', sa.Boolean(), nullable=False, server_default=sa.text('false'))
    )


def downgrade():
    """Remove password_sync_queue table and keycloak_synced column."""
    op.drop_column('users', 'keycloak_synced')
    op.drop_index('idx_password_sync_queue_user_id', table_name='password_sync_queue')
    op.drop_index('idx_password_sync_queue_synced', table_name='password_sync_queue')
    op.drop_table('password_sync_queue')
