"""Add r2_key to vpn_credentials, drop dns_commented

Store raw VPN config files in R2 for byte-perfect downloads.
The dns_commented flag is no longer needed since the raw file
preserves all formatting.

Revision ID: 20260321_000000
Revises: 20260320_000000
Create Date: 2026-03-21 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260321_000000'
down_revision = '20260320_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'vpn_credentials',
        sa.Column('r2_key', sa.String(500), nullable=True),
    )
    op.drop_column('vpn_credentials', 'dns_commented')


def downgrade() -> None:
    op.add_column(
        'vpn_credentials',
        sa.Column('dns_commented', sa.Boolean(), server_default=sa.text('false'), nullable=True),
    )
    op.drop_column('vpn_credentials', 'r2_key')
