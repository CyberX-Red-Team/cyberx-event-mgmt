"""Add os_info JSON column to redirectors table.

Stores OS, architecture, kernel, and uptime collected during test-connection.

Revision ID: 20260326_000000
Revises: 20260325_000001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260326_000000"
down_revision = "20260325_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "redirectors",
        sa.Column("os_info", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("redirectors", "os_info")
