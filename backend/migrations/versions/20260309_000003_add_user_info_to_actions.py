"""Add user_email and user_name to participant_actions for audit trail.

Preserves user identity on action records even if the user is later
deleted (FK uses ondelete=SET NULL).  Backfills existing rows from
the users table.

Revision ID: 20260309_000003
Revises: 20260309_000002
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa

revision = '20260309_000003'
down_revision = '20260309_000002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('participant_actions', sa.Column('user_email', sa.String(255), nullable=True))
    op.add_column('participant_actions', sa.Column('user_name', sa.String(510), nullable=True))

    # Backfill from users table
    op.execute(sa.text("""
        UPDATE participant_actions pa
        SET user_email = u.email,
            user_name = u.first_name || ' ' || u.last_name
        FROM users u
        WHERE pa.user_id = u.id
          AND pa.user_email IS NULL
    """))


def downgrade() -> None:
    op.drop_column('participant_actions', 'user_name')
    op.drop_column('participant_actions', 'user_email')
