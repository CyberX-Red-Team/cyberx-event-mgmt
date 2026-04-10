"""Add vpn_delete_jobs table for async bulk credential deletion

Revision ID: 20260409_000001
Revises: 20260409_000000
Create Date: 2026-04-09 00:00:01

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260409_000001"
down_revision = "20260409_000000"
branch_labels = None
depends_on = None


def upgrade():
    """Create vpn_delete_jobs table."""
    op.create_table(
        "vpn_delete_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "mode",
            sa.String(length=20),
            server_default="by_ids",
            nullable=False,
        ),
        sa.Column(
            "target_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("total_credentials", sa.Integer(), nullable=True),
        sa.Column(
            "processed_credentials",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "deleted_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "failed_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_vpn_delete_jobs_status", "vpn_delete_jobs", ["status"]
    )
    op.create_index(
        "idx_vpn_delete_jobs_created_at", "vpn_delete_jobs", ["created_at"]
    )


def downgrade():
    """Drop vpn_delete_jobs table."""
    op.drop_index("idx_vpn_delete_jobs_created_at", table_name="vpn_delete_jobs")
    op.drop_index("idx_vpn_delete_jobs_status", table_name="vpn_delete_jobs")
    op.drop_table("vpn_delete_jobs")
