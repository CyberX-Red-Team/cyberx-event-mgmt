"""Add user identity snapshot fields to vpn_credentials, vpn_requests, and instances.

Preserves user identity on assignment records even if the user is later
deleted (FK uses ondelete=SET NULL).  Backfills existing rows from
the users table.

Revision ID: 20260310_000000
Revises: 20260309_000004
Create Date: 2026-03-10
"""
from alembic import op
import sqlalchemy as sa

revision = '20260310_000000'
down_revision = '20260309_000004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # VPN credentials: snapshot of assigned user
    op.add_column('vpn_credentials', sa.Column('assigned_to_email', sa.String(255), nullable=True))
    op.add_column('vpn_credentials', sa.Column('assigned_to_name', sa.String(500), nullable=True))

    # VPN requests: snapshot of requesting user
    op.add_column('vpn_requests', sa.Column('user_email', sa.String(255), nullable=True))
    op.add_column('vpn_requests', sa.Column('user_name', sa.String(500), nullable=True))

    # Instances: snapshot of assigned user
    op.add_column('instances', sa.Column('assigned_to_email', sa.String(255), nullable=True))
    op.add_column('instances', sa.Column('assigned_to_name', sa.String(500), nullable=True))

    # Backfill vpn_credentials from users table
    op.execute(sa.text("""
        UPDATE vpn_credentials vc
        SET assigned_to_email = u.email,
            assigned_to_name = TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
        FROM users u
        WHERE vc.assigned_to_user_id = u.id
          AND vc.assigned_to_email IS NULL
    """))

    # Backfill vpn_requests from users table
    op.execute(sa.text("""
        UPDATE vpn_requests vr
        SET user_email = u.email,
            user_name = TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
        FROM users u
        WHERE vr.user_id = u.id
          AND vr.user_email IS NULL
    """))

    # Backfill instances from users table
    op.execute(sa.text("""
        UPDATE instances i
        SET assigned_to_email = u.email,
            assigned_to_name = TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
        FROM users u
        WHERE i.assigned_to_user_id = u.id
          AND i.assigned_to_email IS NULL
    """))


def downgrade() -> None:
    op.drop_column('instances', 'assigned_to_name')
    op.drop_column('instances', 'assigned_to_email')
    op.drop_column('vpn_requests', 'user_name')
    op.drop_column('vpn_requests', 'user_email')
    op.drop_column('vpn_credentials', 'assigned_to_name')
    op.drop_column('vpn_credentials', 'assigned_to_email')
