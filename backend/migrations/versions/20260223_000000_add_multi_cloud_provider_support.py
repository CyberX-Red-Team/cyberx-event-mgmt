"""add multi-cloud provider support

Revision ID: 20260223_000000
Revises: 20260222_000003
Create Date: 2026-02-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260223_000000'
down_revision: Union[str, Sequence[str], None] = '20260222_000003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add multi-cloud provider support."""

    # Add provider column (default to 'openstack' for backward compatibility)
    op.add_column(
        'instances',
        sa.Column(
            'provider',
            sa.String(50),
            nullable=False,
            server_default='openstack'
        )
    )

    # Rename openstack_id to provider_instance_id (provider-agnostic naming)
    op.alter_column(
        'instances',
        'openstack_id',
        new_column_name='provider_instance_id'
    )

    # Add DigitalOcean-specific fields
    op.add_column(
        'instances',
        sa.Column('provider_size_slug', sa.String(100), nullable=True)
    )
    op.add_column(
        'instances',
        sa.Column('provider_region', sa.String(100), nullable=True)
    )

    # Make OpenStack-specific fields nullable (since DO instances won't use them)
    op.alter_column(
        'instances',
        'flavor_id',
        existing_type=sa.String(100),
        nullable=True
    )
    op.alter_column(
        'instances',
        'network_id',
        existing_type=sa.String(100),
        nullable=True
    )

    # Add index on provider for filtering
    op.create_index(
        'ix_instances_provider',
        'instances',
        ['provider']
    )


def downgrade() -> None:
    """Downgrade schema - remove multi-cloud provider support."""

    # Drop index
    op.drop_index('ix_instances_provider', 'instances')

    # Remove nullable constraint from OpenStack fields
    op.alter_column(
        'instances',
        'network_id',
        existing_type=sa.String(100),
        nullable=False
    )
    op.alter_column(
        'instances',
        'flavor_id',
        existing_type=sa.String(100),
        nullable=False
    )

    # Drop DigitalOcean-specific columns
    op.drop_column('instances', 'provider_region')
    op.drop_column('instances', 'provider_size_slug')

    # Rename provider_instance_id back to openstack_id
    op.alter_column(
        'instances',
        'provider_instance_id',
        new_column_name='openstack_id'
    )

    # Drop provider column
    op.drop_column('instances', 'provider')
