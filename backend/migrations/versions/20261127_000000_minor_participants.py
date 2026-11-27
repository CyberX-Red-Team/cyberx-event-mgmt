"""Participants under 18: guardian link on users, per-event guardian consent.

Adds nullable users columns birth_year_month, adult_on, guardian_user_id
(FK users, SET NULL), guardian_link_status, guardian_email_pending (+ _at);
event_participations.activated_at; and the guardian_consents table.

Purely additive. Existing confirmed participations are marked activated
(they were activated on accepting, as adults still are).

Revision ID: 20261127_000000
Revises: 20261126_000000
Create Date: 2026-11-27 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20261127_000000"
down_revision = "20261126_000000"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("birth_year_month", sa.Date(), nullable=True))
        batch.add_column(sa.Column("adult_on", sa.Date(), nullable=True))
        batch.add_column(sa.Column("guardian_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("guardian_link_status", sa.String(20), nullable=True))
        batch.add_column(sa.Column("guardian_email_pending", sa.String(255), nullable=True))
        batch.add_column(sa.Column("guardian_email_pending_at", sa.TIMESTAMP(timezone=True), nullable=True))
        batch.create_foreign_key(
            "fk_users_guardian_user_id", "users", ["guardian_user_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_index("ix_users_guardian_user_id", ["guardian_user_id"])

    with op.batch_alter_table("event_participations") as batch:
        batch.add_column(sa.Column("activated_at", sa.TIMESTAMP(timezone=True), nullable=True))

    op.execute(
        "UPDATE event_participations SET activated_at = COALESCE(confirmed_at, updated_at) "
        "WHERE status = 'confirmed'"
    )

    op.create_table(
        "guardian_consents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("minor_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("guardian_user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_id", sa.Integer(),
                  sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relationship", sa.String(20), nullable=False),
        sa.Column("guardian_name_typed", sa.String(255), nullable=False),
        sa.Column("consent_text_version", sa.String(50), nullable=False),
        sa.Column("terms_version", sa.String(50), nullable=True),
        sa.Column("optional_email_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("consented_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("withdrawn_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
    )
    op.create_index("ix_guardian_consents_id", "guardian_consents", ["id"])
    op.create_index("idx_guardian_consents_minor_event", "guardian_consents", ["minor_user_id", "event_id"])
    op.create_index("idx_guardian_consents_guardian", "guardian_consents", ["guardian_user_id"])


def downgrade():
    op.drop_table("guardian_consents")
    with op.batch_alter_table("event_participations") as batch:
        batch.drop_column("activated_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_guardian_user_id")
        batch.drop_constraint("fk_users_guardian_user_id", type_="foreignkey")
        for col in ("guardian_email_pending_at", "guardian_email_pending", "guardian_link_status",
                    "guardian_user_id", "adult_on", "birth_year_month"):
            batch.drop_column(col)
