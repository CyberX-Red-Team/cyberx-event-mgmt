"""Add dns_commented flag to vpn_credentials

Tracks whether the DNS line in the original WireGuard config was
commented out (e.g. '# DNS = 10.0.0.1'), so downloads preserve
the commented line instead of silently dropping it.

Revision ID: 20260320_000000
Revises: 20260316_000000
Create Date: 2026-03-20 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260320_000000'
down_revision = '20260316_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'vpn_credentials',
        sa.Column('dns_commented', sa.Boolean(), nullable=True, server_default=sa.text('false')),
    )


def downgrade() -> None:
    op.drop_column('vpn_credentials', 'dns_commented')
