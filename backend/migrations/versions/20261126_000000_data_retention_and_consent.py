"""Data retention, future-contact consent, age attestation, do-not-invite list.

Adds nullable columns to users:
  future_contact_consent (+ _at), age_attestation, age_attested_at,
  last_login_at, retention_hold_until, deletion_warning_sent_at
and a new invite_suppressions table (keyed hash of the email only).

last_login_at is backfilled from LOGIN_SUCCESS audit entries so the
inactive-account rule doesn't treat recent sign-ins as inactivity once
year-old audit entries start being purged.

Purely additive; no existing data is changed apart from the backfill.

Revision ID: 20261126_000000
Revises: 20261119_010000
Create Date: 2026-11-26 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20261126_000000"
down_revision = "20261119_010000"
branch_labels = None
depends_on = None


_USER_COLUMNS = [
    sa.Column("future_contact_consent", sa.Boolean(), nullable=True),
    sa.Column("future_contact_consent_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("age_attestation", sa.String(50), nullable=True),
    sa.Column("age_attested_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("retention_hold_until", sa.TIMESTAMP(timezone=True), nullable=True),
    sa.Column("deletion_warning_sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
]


def upgrade():
    with op.batch_alter_table("users") as batch:
        for col in _USER_COLUMNS:
            batch.add_column(col)

    op.create_table(
        "invite_suppressions",
        sa.Column("email_hmac", sa.String(64), primary_key=True),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )

    op.execute(
        """
        UPDATE users SET last_login_at = (
            SELECT MAX(a.created_at) FROM audit_logs a
            WHERE a.user_id = users.id AND a.action = 'LOGIN_SUCCESS'
        )
        WHERE last_login_at IS NULL
        """
    )


def downgrade():
    op.drop_table("invite_suppressions")
    with op.batch_alter_table("users") as batch:
        for col in reversed(_USER_COLUMNS):
            batch.drop_column(col.name)
