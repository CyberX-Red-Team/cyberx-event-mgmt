"""Split certs.request/certs.download into tls.* and cpe.download.

Replaces the shared 'certs.request' and 'certs.download' permission strings
with domain-specific 'tls.request', 'tls.download', and 'cpe.download'.

Revision ID: 20260307_000004
Revises: 20260307_000003
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

revision = '20260307_000004'
down_revision = '20260307_000003'
branch_labels = None
depends_on = None

# Mapping of old permission strings to their replacements
REPLACEMENTS = [
    ("certs.request", "tls.request"),
    ("certs.download", ["tls.download", "cpe.download"]),
]


def upgrade() -> None:
    conn = op.get_bind()

    # Update roles table
    roles = conn.execute(sa.text("SELECT id, permissions FROM roles")).fetchall()
    for role_id, perms in roles:
        if perms is None:
            continue
        updated = list(perms)
        changed = False

        if "certs.request" in updated:
            updated.remove("certs.request")
            updated.append("tls.request")
            changed = True

        if "certs.download" in updated:
            updated.remove("certs.download")
            updated.append("tls.download")
            updated.append("cpe.download")
            changed = True

        if changed:
            import json
            conn.execute(
                sa.text("UPDATE roles SET permissions = CAST(:perms AS json) WHERE id = :id"),
                {"perms": json.dumps(sorted(set(updated))), "id": role_id},
            )

    # Update users permission_overrides (add/remove sets may reference old strings)
    users = conn.execute(
        sa.text("SELECT id, permission_overrides FROM users WHERE permission_overrides IS NOT NULL")
    ).fetchall()
    for user_id, overrides in users:
        if not overrides:
            continue
        changed = False
        for key in ("add", "remove"):
            if key in overrides and overrides[key]:
                lst = list(overrides[key])
                if "certs.request" in lst:
                    lst.remove("certs.request")
                    lst.append("tls.request")
                    changed = True
                if "certs.download" in lst:
                    lst.remove("certs.download")
                    lst.append("tls.download")
                    lst.append("cpe.download")
                    changed = True
                overrides[key] = sorted(set(lst))
        if changed:
            import json
            conn.execute(
                sa.text("UPDATE users SET permission_overrides = CAST(:overrides AS json) WHERE id = :id"),
                {"overrides": json.dumps(overrides), "id": user_id},
            )


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse: tls.request -> certs.request, tls.download + cpe.download -> certs.download
    roles = conn.execute(sa.text("SELECT id, permissions FROM roles")).fetchall()
    for role_id, perms in roles:
        if perms is None:
            continue
        updated = list(perms)
        changed = False

        if "tls.request" in updated:
            updated.remove("tls.request")
            updated.append("certs.request")
            changed = True

        if "tls.download" in updated:
            updated.remove("tls.download")
            changed = True
        if "cpe.download" in updated:
            updated.remove("cpe.download")
            changed = True
        if "tls.download" in perms or "cpe.download" in perms:
            updated.append("certs.download")
            changed = True

        if changed:
            import json
            conn.execute(
                sa.text("UPDATE roles SET permissions = CAST(:perms AS json) WHERE id = :id"),
                {"perms": json.dumps(sorted(set(updated))), "id": role_id},
            )

    users = conn.execute(
        sa.text("SELECT id, permission_overrides FROM users WHERE permission_overrides IS NOT NULL")
    ).fetchall()
    for user_id, overrides in users:
        if not overrides:
            continue
        changed = False
        for key in ("add", "remove"):
            if key in overrides and overrides[key]:
                lst = list(overrides[key])
                if "tls.request" in lst:
                    lst.remove("tls.request")
                    lst.append("certs.request")
                    changed = True
                had_tls_dl = "tls.download" in lst
                had_cpe_dl = "cpe.download" in lst
                if had_tls_dl:
                    lst.remove("tls.download")
                if had_cpe_dl:
                    lst.remove("cpe.download")
                if had_tls_dl or had_cpe_dl:
                    lst.append("certs.download")
                    changed = True
                overrides[key] = sorted(set(lst))
        if changed:
            import json
            conn.execute(
                sa.text("UPDATE users SET permission_overrides = CAST(:overrides AS json) WHERE id = :id"),
                {"overrides": json.dumps(overrides), "id": user_id},
            )
