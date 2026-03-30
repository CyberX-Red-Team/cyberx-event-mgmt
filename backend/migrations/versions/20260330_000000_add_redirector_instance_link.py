"""Link redirectors to cloud instances and mark redirector templates.

Adds:
- redirectors.instance_id: FK to instances.id for CyberX-provisioned redirectors
- instance_templates.is_redirector: marks templates that create redirector VMs
- instance_templates.ssh_username: default SSH user for instances from template

Revision ID: 20260330_000000
Revises: 20260329_000000
"""
from alembic import op
import sqlalchemy as sa

revision = "20260330_000000"
down_revision = "20260329_000000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "redirectors",
        sa.Column(
            "instance_id",
            sa.Integer(),
            sa.ForeignKey("instances.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
    )
    op.create_index("ix_redirectors_instance_id", "redirectors", ["instance_id"])

    op.add_column(
        "instance_templates",
        sa.Column("is_redirector", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "instance_templates",
        sa.Column("ssh_username", sa.String(50), nullable=False, server_default=sa.text("'root'")),
    )


def downgrade() -> None:
    op.drop_column("instance_templates", "ssh_username")
    op.drop_column("instance_templates", "is_redirector")
    op.drop_index("ix_redirectors_instance_id", table_name="redirectors")
    op.drop_column("redirectors", "instance_id")
