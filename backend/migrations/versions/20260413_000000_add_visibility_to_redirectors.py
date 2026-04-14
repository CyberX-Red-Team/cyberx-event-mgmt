"""Add visibility column to redirectors.

Mirrors the public/private visibility model already used by instances:
non-owners see a redirector only when visibility='public'; owners and
admins always see their own (and all) rows.

Revision ID: 20260413_000000
Revises: 20260409_000001
Create Date: 2026-04-13 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260413_000000"
down_revision = "20260409_000001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "redirectors",
        sa.Column(
            "visibility",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'private'"),
        ),
    )
    op.create_index(
        "ix_redirectors_visibility",
        "redirectors",
        ["visibility"],
    )


def downgrade():
    op.drop_index("ix_redirectors_visibility", table_name="redirectors")
    op.drop_column("redirectors", "visibility")
