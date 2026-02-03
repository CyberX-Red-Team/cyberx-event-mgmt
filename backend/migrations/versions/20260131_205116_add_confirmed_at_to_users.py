"""add confirmed_at to users

Revision ID: 20260131_205116
Revises:
Create Date: 2026-01-31 20:51:16

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '20260131_205116'
down_revision = 'd4e5f6g7h8i9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add confirmed_at column to users table
    op.add_column('users', sa.Column('confirmed_at', sa.TIMESTAMP(timezone=True), nullable=True))

    # Optional: Backfill confirmed_at for existing confirmed users from audit logs
    # This SQL will set confirmed_at from the earliest PARTICIPATION_CONFIRM audit log entry
    op.execute("""
        UPDATE users
        SET confirmed_at = (
            SELECT MIN(al.created_at)
            FROM audit_logs al
            WHERE al.user_id = users.id
            AND al.action = 'PARTICIPATION_CONFIRM'
        )
        WHERE confirmed = 'YES'
        AND confirmed_at IS NULL
    """)


def downgrade() -> None:
    # Remove confirmed_at column from users table
    op.drop_column('users', 'confirmed_at')
