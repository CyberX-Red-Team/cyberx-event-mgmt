"""Add events.archived_at and relax instance_templates.event_id to nullable.

Two schema changes landed together because both support the event-archive
cascade work: archived_at records when the cascade ran, and making
instance_templates.event_id nullable lets archive detach (rather than
delete) templates so they can be re-assigned to a future event.

Revision ID: 20260420_000000
Revises: 20260415_010000
Create Date: 2026-04-20 00:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = "20260420_000000"
down_revision = "20260415_010000"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "events",
        sa.Column("archived_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.alter_column(
        "instance_templates",
        "event_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "instance_templates",
        "event_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_column("events", "archived_at")
