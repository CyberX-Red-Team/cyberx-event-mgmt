"""Redact secrets already stored in audit log details and finished emails.

New writes are redacted by the AuditLog model and the email queue service;
this scrubs rows written before that. Processes rows in Python (no
database-specific JSON operators) and only updates rows that change, so it is
safe to re-run.

The key list is frozen here on purpose: a migration must keep doing exactly
what it did when it shipped, even if app.utils.redaction changes later.

Data-only and irreversible: downgrade is a no-op.

Revision ID: 20261119_000000
Revises: 20260420_000000
Create Date: 2026-11-19 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "20261119_000000"
down_revision = "20260420_000000"
branch_labels = None
depends_on = None

REDACTED = "[REDACTED]"
SECRET_KEYS = frozenset({
    "password", "pandas_password", "password_phonetic", "new_password",
    "old_password", "current_password", "confirm_password",
    "ssh_private_key", "private_key", "api_key", "secret", "client_secret",
    "totp_secret", "reset_token", "reset_url", "session_token",
})
FINISHED_EMAIL_STATUSES = ("sent", "failed", "cancelled")
BATCH = 500


def _mask(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return {k: _mask(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return REDACTED


def _redact(value):
    if isinstance(value, dict):
        return {
            k: _mask(v) if isinstance(k, str) and k.lower() in SECRET_KEYS else _redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _scrub(conn, table, column, where=None):
    """Redact `column` on every row of `table`; returns rows changed."""
    last_id = 0
    changed = 0
    while True:
        query = (
            sa.select(table.c.id, column)
            .where(table.c.id > last_id, column.is_not(None))
            .order_by(table.c.id)
            .limit(BATCH)
        )
        if where is not None:
            query = query.where(where)
        rows = conn.execute(query).fetchall()
        if not rows:
            return changed
        for row_id, value in rows:
            redacted = _redact(value)
            if redacted != value:
                conn.execute(
                    sa.update(table).where(table.c.id == row_id).values({column.name: redacted})
                )
                changed += 1
        last_id = rows[-1][0]


def upgrade():
    conn = op.get_bind()

    audit_logs = sa.table(
        "audit_logs", sa.column("id", sa.Integer), sa.column("details", sa.JSON),
    )
    email_queue = sa.table(
        "email_queue",
        sa.column("id", sa.Integer),
        sa.column("status", sa.String),
        sa.column("custom_vars", sa.JSON),
    )

    audit_changed = _scrub(conn, audit_logs, audit_logs.c.details)
    email_changed = _scrub(
        conn, email_queue, email_queue.c.custom_vars,
        where=email_queue.c.status.in_(FINISHED_EMAIL_STATUSES),
    )
    print(
        f"redact_secrets_at_rest: audit_logs rows redacted={audit_changed}, "
        f"email_queue rows redacted={email_changed}"
    )


def downgrade():
    # Redacted values cannot be restored.
    pass
