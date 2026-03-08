"""Add allowed_role_ids to roles table.

Allows sponsor-type roles to restrict which invitee roles they can assign.

Revision ID: 20260307_000001
Revises: 20260307_000000
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

revision = '20260307_000001'
down_revision = '20260307_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('roles', sa.Column('allowed_role_ids', sa.JSON(), nullable=False, server_default='[]'))


def downgrade() -> None:
    op.drop_column('roles', 'allowed_role_ids')
