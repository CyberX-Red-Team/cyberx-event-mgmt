"""Add service_api_keys table

Creates the service_api_keys table for storing hashed API keys
used by external integrations (Discord bot, etc.).

Revision ID: 20260314_000000
Revises: 60c97162b7c2
Create Date: 2026-03-14 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260314_000000'
down_revision = '60c97162b7c2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'service_api_keys',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('key_hash', sa.String(64), nullable=False, unique=True),
        sa.Column('key_prefix', sa.String(12), nullable=False),
        sa.Column('scopes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_used_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('last_used_ip', sa.String(45), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now()),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index('ix_service_api_keys_key_hash', 'service_api_keys', ['key_hash'])


def downgrade() -> None:
    op.drop_index('ix_service_api_keys_key_hash', table_name='service_api_keys')
    op.drop_table('service_api_keys')
