"""Add deployed boolean to stream_configs table.

Tracks whether each stream config has been deployed to the remote redirector.

Revision ID: 20260325_000001
Revises: 20260325_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260325_000001"
down_revision = "20260325_000000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stream_configs",
        sa.Column("deployed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade():
    op.drop_column("stream_configs", "deployed")
