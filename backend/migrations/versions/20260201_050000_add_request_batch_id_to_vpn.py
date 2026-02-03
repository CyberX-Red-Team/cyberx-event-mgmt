"""add request_batch_id to vpn_credentials

Revision ID: 20260201_050000
Revises: 20260201_040000
Create Date: 2026-02-01 05:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '20260201_050000'
down_revision = '20260201_040000'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add request_batch_id to track which request batch each VPN was assigned in
    # This enables users to download VPNs grouped by request
    op.add_column('vpn_credentials', sa.Column('request_batch_id', sa.String(50), nullable=True))

    # Add index for faster queries by batch
    op.create_index('idx_vpn_request_batch_id', 'vpn_credentials', ['request_batch_id'])


def downgrade() -> None:
    # Drop index first
    op.drop_index('idx_vpn_request_batch_id', 'vpn_credentials')

    # Drop column
    op.drop_column('vpn_credentials', 'request_batch_id')
