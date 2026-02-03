"""add app_settings table

Revision ID: 20260201_060000
Revises: 20260201_050000
Create Date: 2026-02-01 06:00:00

"""
from alembic import op
import sqlalchemy as sa

revision = '20260201_060000'
down_revision = '20260201_050000'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create app_settings table for dynamic configuration
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('description', sa.String(255), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )

    # Insert default VPN naming pattern
    op.execute("""
        INSERT INTO app_settings (key, value, description)
        VALUES (
            'vpn_naming_pattern',
            'simnet_{ipv4_address}.conf',
            'Default filename pattern for VPN config downloads'
        )
    """)


def downgrade() -> None:
    op.drop_table('app_settings')
