"""add vpn original config fields

Revision ID: 20260222_000002
Revises: 20260222_000001
Create Date: 2026-02-22 00:00:02.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260222_000002'
down_revision: Union[str, Sequence[str], None] = '20260222_000001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add fields to preserve original VPN config structure."""

    # Add optional config fields to vpn_credentials table
    # These preserve the exact structure of uploaded configs for hash verification
    op.add_column(
        'vpn_credentials',
        sa.Column('mtu', sa.String(length=10), nullable=True, comment='MTU from original config')
    )
    op.add_column(
        'vpn_credentials',
        sa.Column('dns', sa.Text(), nullable=True, comment='DNS servers from original config')
    )
    op.add_column(
        'vpn_credentials',
        sa.Column('public_key', sa.Text(), nullable=True, comment='Server public key from original config')
    )
    op.add_column(
        'vpn_credentials',
        sa.Column('allowed_ips', sa.Text(), nullable=True, comment='AllowedIPs from original config')
    )
    op.add_column(
        'vpn_credentials',
        sa.Column('persistent_keepalive', sa.String(length=10), nullable=True, comment='PersistentKeepalive from original config')
    )


def downgrade() -> None:
    """Downgrade schema - remove original config fields."""

    # Remove the optional config fields
    op.drop_column('vpn_credentials', 'persistent_keepalive')
    op.drop_column('vpn_credentials', 'allowed_ips')
    op.drop_column('vpn_credentials', 'public_key')
    op.drop_column('vpn_credentials', 'dns')
    op.drop_column('vpn_credentials', 'mtu')
