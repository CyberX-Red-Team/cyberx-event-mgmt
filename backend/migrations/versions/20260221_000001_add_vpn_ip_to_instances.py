"""Add VPN IP to instances

Revision ID: 20260221_000001
Revises: 20260221_000000
Create Date: 2026-02-21 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260221_000001'
down_revision = '20260221_000000'
branch_labels = None
depends_on = None


def upgrade():
    # Add VPN IP column to instances table
    op.add_column('instances', sa.Column('vpn_ip', sa.String(50), nullable=True))


def downgrade():
    # Remove VPN IP column from instances table
    op.drop_column('instances', 'vpn_ip')
