"""Add use_infrastructure_key flag to redirectors, make ssh_private_key nullable.

When use_infrastructure_key=True, the redirector uses the active event's SSH
key pair instead of a per-redirector BYOD key, so ssh_private_key can be NULL.

Revision ID: 20260329_000000
Revises: 20260326_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260329_000000"
down_revision = "20260326_000000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "redirectors",
        sa.Column(
            "use_infrastructure_key",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.alter_column(
        "redirectors",
        "ssh_private_key",
        existing_type=sa.Text(),
        nullable=True,
    )


def downgrade():
    # Restore NOT NULL — any NULL rows must be cleaned up first
    op.alter_column(
        "redirectors",
        "ssh_private_key",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("redirectors", "use_infrastructure_key")
