"""Add SNI routing columns and constraint swap on stream_configs.

Adds sni_hostname and internal_bridge_port to stream_configs so a single
listen_port on a redirector can host multiple TLS streams differentiated
by Server Name Indication. Replaces the (redirector_id, listen_port)
unique constraint with (redirector_id, listen_port, sni_hostname) so
NULL sni_hostname continues to enforce single-stream exclusivity for
legacy rows while non-NULL entries share the port.

Revision ID: 20260415_010000
Revises: 20260415_000000
Create Date: 2026-04-15 01:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260415_010000"
down_revision = "20260415_000000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stream_configs",
        sa.Column("sni_hostname", sa.String(length=253), nullable=True),
    )
    op.add_column(
        "stream_configs",
        sa.Column("internal_bridge_port", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_stream_configs_sni_hostname",
        "stream_configs",
        ["sni_hostname"],
    )

    op.drop_constraint(
        "uq_stream_configs_redirector_port",
        "stream_configs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_stream_configs_redirector_port_sni",
        "stream_configs",
        ["redirector_id", "listen_port", "sni_hostname"],
    )
    op.create_unique_constraint(
        "uq_stream_configs_redirector_bridge_port",
        "stream_configs",
        ["redirector_id", "internal_bridge_port"],
    )


def downgrade():
    op.drop_constraint(
        "uq_stream_configs_redirector_bridge_port",
        "stream_configs",
        type_="unique",
    )
    op.drop_constraint(
        "uq_stream_configs_redirector_port_sni",
        "stream_configs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_stream_configs_redirector_port",
        "stream_configs",
        ["redirector_id", "listen_port"],
    )
    op.drop_index("ix_stream_configs_sni_hostname", table_name="stream_configs")
    op.drop_column("stream_configs", "internal_bridge_port")
    op.drop_column("stream_configs", "sni_hostname")
