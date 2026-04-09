"""Add owner_id column to redirectors table.

Allows participants to own redirectors they create. Admins see all redirectors
via the redirectors.view_all permission.

Revision ID: 20260325_000000
Revises: 20260323_000001
"""
from alembic import op
import sqlalchemy as sa

revision = "20260325_000000"
down_revision = "20260323_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "redirectors",
        sa.Column(
            "owner_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_redirectors_owner_id", "redirectors", ["owner_id"])


def downgrade():
    op.drop_index("ix_redirectors_owner_id", table_name="redirectors")
    op.drop_column("redirectors", "owner_id")
