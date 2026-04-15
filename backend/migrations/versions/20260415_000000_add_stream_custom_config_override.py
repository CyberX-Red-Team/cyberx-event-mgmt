"""Add custom_config_override column to stream_configs.

Nullable TEXT column. When set, the nginx config generator emits this
verbatim instead of rendering from structured fields. Used by the
"View/Edit Config" modal to let operators hand-edit the deployed config.

Revision ID: 20260415_000000
Revises: 20260413_000000
Create Date: 2026-04-15 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260415_000000"
down_revision = "20260413_000000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stream_configs",
        sa.Column("custom_config_override", sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_column("stream_configs", "custom_config_override")
