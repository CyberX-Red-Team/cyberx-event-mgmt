"""Add instances.manage_agent to sponsor and invitee system roles.

VPN cycling is a self-service feature tied to the agent tasking system,
so participants need instances.manage_agent permission.

Revision ID: 20260307_000002
Revises: 20260307_000001
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa
import json

revision = '20260307_000002'
down_revision = '20260307_000001'
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
    # Remove instances.manage_agent from sponsor and invitee system roles
    from app.utils.permissions import ROLE_PERMISSIONS

    sponsor_old = sorted(set(ROLE_PERMISSIONS["sponsor"]) - {"instances.manage_agent"})
    invitee_old = sorted(set(ROLE_PERMISSIONS["invitee"]) - {"instances.manage_agent"})

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'sponsor' AND is_system = true"
    ).bindparams(perms=json.dumps(sponsor_old)))

    op.execute(sa.text(
        "UPDATE roles SET permissions = CAST(:perms AS json) WHERE slug = 'invitee' AND is_system = true"
    ).bindparams(perms=json.dumps(invitee_old)))
