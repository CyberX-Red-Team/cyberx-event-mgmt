"""Add vpn_import_jobs table for async VPN credential imports

Revision ID: 20260409_000000
Revises: 20260330_000000
Create Date: 2026-04-09 00:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260409_000000"
down_revision = "20260330_000000"
branch_labels = None
depends_on = None


def upgrade():
    """Create vpn_import_jobs table."""
    op.create_table(
        "vpn_import_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("assignment_type", sa.String(length=50), nullable=False),
        sa.Column("endpoint_override", sa.String(length=255), nullable=True),
        sa.Column("r2_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("total_files", sa.Integer(), nullable=True),
        sa.Column(
            "processed_files",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "imported_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "skipped_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "error_count",
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
        "idx_vpn_import_jobs_status", "vpn_import_jobs", ["status"]
    )
    op.create_index(
        "idx_vpn_import_jobs_created_at", "vpn_import_jobs", ["created_at"]
    )


def downgrade():
    """Drop vpn_import_jobs table."""
    op.drop_index("idx_vpn_import_jobs_created_at", table_name="vpn_import_jobs")
    op.drop_index("idx_vpn_import_jobs_status", table_name="vpn_import_jobs")
    op.drop_table("vpn_import_jobs")
