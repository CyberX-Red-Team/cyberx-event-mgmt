"""Add instances.delete to sponsor and invitee system roles.

Sponsors and invitees who can provision instances should also be able to
delete their own instances.

Revision ID: 20260309_000001
Revises: 20260307_000004
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa
import json

revision = '20260309_000001'
down_revision = '20260307_000004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.utils.permissions import ROLE_PERMISSIONS

    sponsor_perms = json.dumps(sorted(ROLE_PERMISSIONS["sponsor"]))
    invitee_perms = json.dumps(sorted(ROLE_PERMISSIONS["invitee"]))

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'sponsor' AND is_system = true"
    ).bindparams(perms=sponsor_perms))

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'invitee' AND is_system = true"
    ).bindparams(perms=invitee_perms))


def downgrade() -> None:
    from app.utils.permissions import ROLE_PERMISSIONS

    sponsor_old = sorted(set(ROLE_PERMISSIONS["sponsor"]) - {"instances.delete"})
    invitee_old = sorted(set(ROLE_PERMISSIONS["invitee"]) - {"instances.delete"})

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'sponsor' AND is_system = true"
    ).bindparams(perms=json.dumps(sponsor_old)))

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'invitee' AND is_system = true"
    ).bindparams(perms=json.dumps(invitee_old)))
