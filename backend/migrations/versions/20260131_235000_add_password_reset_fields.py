"""add password reset fields

Revision ID: 20260131_235000
Revises: f988d0d58b40
Create Date: 2026-01-31 23:50:00

"""
from alembic import op
import sqlalchemy as sa

revision = '20260131_235000'
down_revision = 'f988d0d58b40'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add password reset fields to users table
    op.add_column('users', sa.Column('password_reset_token', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('password_reset_expires', sa.TIMESTAMP(timezone=True), nullable=True))

    # Create index for password reset token lookup
    op.create_index('idx_users_password_reset_token', 'users', ['password_reset_token'], unique=True)


def downgrade() -> None:
    op.drop_index('idx_users_password_reset_token', 'users')
    op.drop_column('users', 'password_reset_expires')
    op.drop_column('users', 'password_reset_token')
