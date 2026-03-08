"""Add roles and permissions system.

Creates roles table, adds role_id and permission_overrides to users,
seeds three built-in roles, and populates user.role_id from user.role string.

Revision ID: 20260307_000000
Revises: 20260306_000000
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON
import json

revision = '20260307_000000'
down_revision = '20260306_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create roles table
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('slug', sa.String(100), nullable=False),
        sa.Column('base_type', sa.String(20), nullable=False),
        sa.Column('permissions', JSON, nullable=False, server_default='[]'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_roles_id', 'roles', ['id'])
    op.create_index('ix_roles_slug', 'roles', ['slug'], unique=True)
    op.create_index('idx_roles_base_type', 'roles', ['base_type'])
    op.create_index('idx_roles_is_system', 'roles', ['is_system'])

    # 2. Seed built-in roles
    from app.utils.permissions import ALL_PERMISSIONS, ROLE_PERMISSIONS

    admin_perms = json.dumps(sorted(ALL_PERMISSIONS))
    sponsor_perms = json.dumps(sorted(ROLE_PERMISSIONS["sponsor"]))
    invitee_perms = json.dumps(sorted(ROLE_PERMISSIONS["invitee"]))

    op.execute(sa.text(
        "INSERT INTO roles (name, slug, base_type, permissions, is_system, description) VALUES "
        "('Admin', 'admin', 'admin', CAST(:admin_perms AS json), true, 'Full system access — all permissions enabled'), "
        "('Sponsor', 'sponsor', 'sponsor', CAST(:sponsor_perms AS json), true, 'Can manage sponsored participants and their resources'), "
        "('Invitee', 'invitee', 'invitee', CAST(:invitee_perms AS json), true, 'Standard participant access — can manage own resources')"
    ).bindparams(
        admin_perms=admin_perms,
        sponsor_perms=sponsor_perms,
        invitee_perms=invitee_perms,
    ))

    # 3. Add role_id and permission_overrides to users
    op.add_column('users',
        sa.Column('role_id', sa.Integer(), sa.ForeignKey('roles.id', ondelete='SET NULL'), nullable=True)
    )
    op.add_column('users',
        sa.Column('permission_overrides', JSON, nullable=False, server_default='{}')
    )
    op.create_index('idx_users_role_id', 'users', ['role_id'])

    # 4. Populate role_id from existing role string
    op.execute(sa.text(
        "UPDATE users SET role_id = (SELECT id FROM roles WHERE slug = users.role)"
    ))


def downgrade() -> None:
    op.drop_index('idx_users_role_id', table_name='users')
    op.drop_column('users', 'permission_overrides')
    op.drop_column('users', 'role_id')

    op.drop_index('idx_roles_is_system', table_name='roles')
    op.drop_index('idx_roles_base_type', table_name='roles')
    op.drop_index('ix_roles_slug', table_name='roles')
    op.drop_index('ix_roles_id', table_name='roles')
    op.drop_table('roles')
