"""Add send_immediately to email_workflows

Adds a boolean column to control whether a workflow sends emails
immediately (bypassing the queue) or queues them for batch processing.

Revision ID: 20260306_000000
Revises: 20260304_000000
Create Date: 2026-03-06 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260306_000000'
down_revision = '20260304_000000'
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column exists in the given table."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    return result.fetchone() is not None


def upgrade() -> None:
    if not _column_exists('email_workflows', 'send_immediately'):
        op.add_column('email_workflows', sa.Column(
            'send_immediately', sa.Boolean(), nullable=False, server_default=sa.text('false')
        ))


def downgrade() -> None:
    if _column_exists('email_workflows', 'send_immediately'):
        op.drop_column('email_workflows', 'send_immediately')
