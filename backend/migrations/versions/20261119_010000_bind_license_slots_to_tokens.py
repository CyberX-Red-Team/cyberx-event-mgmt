"""Bind license queue slots to the license token that acquired them.

Adds nullable license_slots.token_id (FK license_tokens.id, ON DELETE SET
NULL). Existing slots keep NULL.

Revision ID: 20261119_010000
Revises: 20261119_000000
Create Date: 2026-11-19 01:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20261119_010000"
down_revision = "20261119_000000"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("license_slots") as batch:
        batch.add_column(sa.Column("token_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_license_slots_token_id", "license_tokens",
            ["token_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_license_slots_token_id", ["token_id"])


def downgrade():
    with op.batch_alter_table("license_slots") as batch:
        batch.drop_index("ix_license_slots_token_id")
        batch.drop_constraint("fk_license_slots_token_id", type_="foreignkey")
        batch.drop_column("token_id")
