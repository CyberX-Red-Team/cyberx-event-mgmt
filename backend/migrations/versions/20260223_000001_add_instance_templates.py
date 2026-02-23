"""add instance templates and participant self-service

Revision ID: 20260223_000001
Revises: 20260223_000000
Create Date: 2026-02-23 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260223_000001'
down_revision: Union[str, Sequence[str], None] = '20260223_000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add instance templates and self-service fields."""

    # Create instance_templates table
    op.create_table(
        'instance_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('provider', sa.String(50), nullable=False, server_default='openstack'),
        sa.Column('flavor_id', sa.String(100), nullable=True),
        sa.Column('network_id', sa.String(100), nullable=True),
        sa.Column('provider_size_slug', sa.String(100), nullable=True),
        sa.Column('provider_region', sa.String(100), nullable=True),
        sa.Column('image_id', sa.String(100), nullable=False),
        sa.Column('cloud_init_template_id', sa.Integer(), nullable=True),
        sa.Column('license_product_id', sa.Integer(), nullable=True),
        sa.Column('event_id', sa.Integer(), nullable=False),
        sa.Column('max_instances', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['cloud_init_template_id'], ['cloud_init_templates.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['license_product_id'], ['license_products.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['event_id'], ['events.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_instance_templates_id', 'instance_templates', ['id'])
    op.create_index('ix_instance_templates_name', 'instance_templates', ['name'])
    op.create_index('ix_instance_templates_event_id', 'instance_templates', ['event_id'])

    # Add new columns to instances table
    op.add_column('instances', sa.Column('instance_template_id', sa.Integer(), nullable=True))
    op.add_column('instances', sa.Column('visibility', sa.String(20), nullable=False, server_default='private'))
    op.add_column('instances', sa.Column('notes', sa.Text(), nullable=True))

    # Add foreign key and indexes for new instance columns
    op.create_foreign_key(
        'fk_instances_instance_template_id',
        'instances', 'instance_templates',
        ['instance_template_id'], ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_instances_instance_template_id', 'instances', ['instance_template_id'])
    op.create_index('ix_instances_visibility', 'instances', ['visibility'])


def downgrade() -> None:
    """Downgrade schema - remove instance templates."""

    # Drop indexes and columns from instances table
    op.drop_index('ix_instances_visibility', 'instances')
    op.drop_index('ix_instances_instance_template_id', 'instances')
    op.drop_constraint('fk_instances_instance_template_id', 'instances', type_='foreignkey')
    op.drop_column('instances', 'notes')
    op.drop_column('instances', 'visibility')
    op.drop_column('instances', 'instance_template_id')

    # Drop instance_templates table
    op.drop_index('ix_instance_templates_event_id', 'instance_templates')
    op.drop_index('ix_instance_templates_name', 'instance_templates')
    op.drop_index('ix_instance_templates_id', 'instance_templates')
    op.drop_table('instance_templates')
