"""add vpn instance assignment

Revision ID: 20260222_000001
Revises: 20260221_000002
Create Date: 2026-02-22 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260222_000001'
down_revision: Union[str, Sequence[str], None] = '20260221_000002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add VPN instance assignment support."""

    # Add assignment_type to vpn_credentials table
    op.add_column(
        'vpn_credentials',
        sa.Column(
            'assignment_type',
            sa.String(30),
            nullable=False,
            server_default='USER_REQUESTABLE'
        )
    )

    # Add assigned_to_instance_id to vpn_credentials table
    op.add_column(
        'vpn_credentials',
        sa.Column('assigned_to_instance_id', sa.Integer(), nullable=True)
    )

    # Add assigned_instance_at timestamp to vpn_credentials table
    op.add_column(
        'vpn_credentials',
        sa.Column('assigned_instance_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )

    # Create foreign key constraint for instance assignment
    op.create_foreign_key(
        'fk_vpn_assigned_instance',
        'vpn_credentials',
        'instances',
        ['assigned_to_instance_id'],
        ['id'],
        ondelete='SET NULL'
    )

    # Create index on assigned_to_instance_id for fast lookups
    op.create_index(
        'idx_vpn_assigned_to_instance_id',
        'vpn_credentials',
        ['assigned_to_instance_id']
    )

    # Create index on assignment_type for filtering
    op.create_index(
        'idx_vpn_assignment_type',
        'vpn_credentials',
        ['assignment_type']
    )

    # Add vpn_config_token to instances table (stores SHA-256 hash)
    op.add_column(
        'instances',
        sa.Column('vpn_config_token', sa.String(255), nullable=True)
    )

    # Add vpn_config_token_expires_at to instances table
    op.add_column(
        'instances',
        sa.Column('vpn_config_token_expires_at', sa.TIMESTAMP(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema - remove VPN instance assignment support."""

    # Drop instances table columns
    op.drop_column('instances', 'vpn_config_token_expires_at')
    op.drop_column('instances', 'vpn_config_token')

    # Drop vpn_credentials table indexes
    op.drop_index('idx_vpn_assignment_type', 'vpn_credentials')
    op.drop_index('idx_vpn_assigned_to_instance_id', 'vpn_credentials')

    # Drop foreign key constraint
    op.drop_constraint('fk_vpn_assigned_instance', 'vpn_credentials', type_='foreignkey')

    # Drop vpn_credentials table columns
    op.drop_column('vpn_credentials', 'assigned_instance_at')
    op.drop_column('vpn_credentials', 'assigned_to_instance_id')
    op.drop_column('vpn_credentials', 'assignment_type')
