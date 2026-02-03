"""make preshared_key optional in vpn_credentials

Revision ID: 20260201_040000
Revises: ec4255795274
Create Date: 2026-02-01 04:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '20260201_040000'
down_revision = 'ec4255795274'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Make preshared_key nullable in vpn_credentials table
    # PresharedKey is optional in WireGuard configs (provides post-quantum security)
    op.alter_column('vpn_credentials', 'preshared_key',
                    existing_type=sa.Text(),
                    nullable=True)


def downgrade() -> None:
    # Revert to NOT NULL (will fail if there are NULL values)
    op.alter_column('vpn_credentials', 'preshared_key',
                    existing_type=sa.Text(),
                    nullable=False)
