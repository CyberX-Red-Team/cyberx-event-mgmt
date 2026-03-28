"""Add infrastructure key fields to redirectors table.

Adds ssh_backup_key (user's original key) and use_infrastructure_key flag.

Revision ID: 20260328_000000
Revises: 20260326_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260328_000000"
down_revision = "20260326_000000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "redirectors",
        sa.Column("ssh_backup_key", sa.Text(), nullable=True),
    )
    op.add_column(
        "redirectors",
        sa.Column("use_infrastructure_key", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    op.drop_column("redirectors", "use_infrastructure_key")
    op.drop_column("redirectors", "ssh_backup_key")
