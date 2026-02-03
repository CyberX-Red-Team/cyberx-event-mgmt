"""clean vpn interface_ip spaces

Revision ID: 20260201_070000
Revises: 20260201_060000
Create Date: 2026-02-01 07:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '20260201_070000'
down_revision = '20260201_060000'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Remove spaces after commas in interface_ip column
    # This fixes data that was imported with spaces (e.g., "10.0.0.1, fd00::1" -> "10.0.0.1,fd00::1")
    op.execute("""
        UPDATE vpn_credentials
        SET interface_ip = REPLACE(interface_ip, ', ', ',')
        WHERE interface_ip LIKE '%, %'
    """)


def downgrade() -> None:
    # Re-add spaces after commas (reverse the change)
    op.execute("""
        UPDATE vpn_credentials
        SET interface_ip = REPLACE(interface_ip, ',', ', ')
        WHERE interface_ip LIKE '%,%'
        AND interface_ip NOT LIKE '%, %'
    """)
