"""Add user identity snapshot fields to audit_logs.

Preserves user identity on audit log entries even if the user is later
deleted (FK uses ondelete=SET NULL).  Backfills existing rows from
the users table.

Revision ID: 20260310_000001
Revises: 20260310_000000
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

revision = '20260310_000001'
down_revision = '20260310_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('audit_logs', sa.Column('user_email', sa.String(255), nullable=True))
    op.add_column('audit_logs', sa.Column('user_name', sa.String(500), nullable=True))

    # Backfill from users table
    op.execute(sa.text("""
        UPDATE audit_logs al
        SET user_email = u.email,
            user_name = TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
        FROM users u
        WHERE al.user_id = u.id
          AND al.user_email IS NULL
    """))


def downgrade() -> None:
    op.drop_column('audit_logs', 'user_name')
    op.drop_column('audit_logs', 'user_email')
