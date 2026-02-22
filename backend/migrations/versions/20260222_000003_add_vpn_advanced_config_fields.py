"""add vpn advanced config fields

Revision ID: 20260222_000003
Revises: 20260222_000002
Create Date: 2026-02-22 00:00:03.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260222_000003'
down_revision: Union[str, Sequence[str], None] = '20260222_000002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add advanced WireGuard config fields for complete hash matching."""

    # Add advanced optional config fields to vpn_credentials table
    # These preserve additional WireGuard options from original configs
    op.add_column(
        'vpn_credentials',
        sa.Column('table', sa.String(length=20), nullable=True, comment='Table (routing table) from original config')
    )
    op.add_column(
        'vpn_credentials',
        sa.Column('save_config', sa.String(length=10), nullable=True, comment='SaveConfig from original config')
    )
    op.add_column(
        'vpn_credentials',
        sa.Column('fwmark', sa.String(length=20), nullable=True, comment='FwMark (firewall mark) from original config')
    )


def downgrade() -> None:
    """Downgrade schema - remove advanced config fields."""

    # Remove the advanced optional config fields
    op.drop_column('vpn_credentials', 'fwmark')
    op.drop_column('vpn_credentials', 'save_config')
    op.drop_column('vpn_credentials', 'table')
