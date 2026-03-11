"""Add discord.view to sponsor and invitee system roles.

Participants need discord.view to see the Discord invite card on the
participant portal.

Revision ID: 20260309_000002
Revises: 20260309_000001
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa
import json

revision = '20260309_000002'
down_revision = '20260309_000001'
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

    sponsor_old = sorted(set(ROLE_PERMISSIONS["sponsor"]) - {"discord.view"})
    invitee_old = sorted(set(ROLE_PERMISSIONS["invitee"]) - {"discord.view"})

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'sponsor' AND is_system = true"
    ).bindparams(perms=json.dumps(sponsor_old)))

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'invitee' AND is_system = true"
    ).bindparams(perms=json.dumps(invitee_old)))
