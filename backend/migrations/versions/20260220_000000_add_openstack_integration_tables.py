"""add openstack integration tables

Revision ID: 20260220_000000
Revises: e6b209014e6c
Create Date: 2026-02-20 00:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '20260220_000000'
down_revision: Union[str, None] = 'e6b209014e6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Cloud-init templates (must be created before instances due to FK)
    op.create_table(
        'cloud_init_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_default', sa.Boolean(), server_default=sa.text('false'), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_cloud_init_templates_id', 'cloud_init_templates', ['id'])

    # License products (must be created before tokens/slots due to FK)
    op.create_table(
        'license_products',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('license_blob', sa.Text(), nullable=False),
        sa.Column('max_concurrent', sa.Integer(), server_default=sa.text('2'), nullable=False),
        sa.Column('slot_ttl', sa.Integer(), server_default=sa.text('7200'), nullable=False),
        sa.Column('token_ttl', sa.Integer(), server_default=sa.text('7200'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('download_filename', sa.String(500), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_license_products_id', 'license_products', ['id'])

    # Instances
    op.create_table(
        'instances',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('openstack_id', sa.String(100), nullable=True),
        sa.Column('status', sa.String(50), server_default=sa.text("'BUILDING'"), nullable=False),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('flavor_id', sa.String(100), nullable=False),
        sa.Column('image_id', sa.String(100), nullable=False),
        sa.Column('network_id', sa.String(100), nullable=False),
        sa.Column('key_name', sa.String(100), nullable=True),
        sa.Column('cloud_init_template_id', sa.Integer(), sa.ForeignKey('cloud_init_templates.id', ondelete='SET NULL'), nullable=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id', ondelete='SET NULL'), nullable=True),
        sa.Column('assigned_to_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('openstack_id'),
    )
    op.create_index('ix_instances_id', 'instances', ['id'])
    op.create_index('ix_instances_name', 'instances', ['name'])
    op.create_index('ix_instances_event_id', 'instances', ['event_id'])
    op.create_index('ix_instances_assigned_to_user_id', 'instances', ['assigned_to_user_id'])

    # License tokens
    op.create_table(
        'license_tokens',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('license_products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('used', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('used_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('used_by_ip', sa.String(50), nullable=True),
        sa.Column('instance_id', sa.Integer(), sa.ForeignKey('instances.id', ondelete='SET NULL'), nullable=True),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index('ix_license_tokens_id', 'license_tokens', ['id'])
    op.create_index('ix_license_tokens_token_hash', 'license_tokens', ['token_hash'])
    op.create_index('ix_license_tokens_product_id', 'license_tokens', ['product_id'])
    op.create_index('ix_license_tokens_instance_id', 'license_tokens', ['instance_id'])

    # License slots
    op.create_table(
        'license_slots',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slot_id', sa.String(50), nullable=False),
        sa.Column('product_id', sa.Integer(), sa.ForeignKey('license_products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('hostname', sa.String(255), nullable=True),
        sa.Column('ip_address', sa.String(50), nullable=True),
        sa.Column('acquired_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column('released_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('result', sa.String(50), nullable=True),
        sa.Column('elapsed_seconds', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slot_id'),
    )
    op.create_index('ix_license_slots_id', 'license_slots', ['id'])
    op.create_index('ix_license_slots_slot_id', 'license_slots', ['slot_id'])
    op.create_index('ix_license_slots_product_id', 'license_slots', ['product_id'])
    op.create_index('ix_license_slots_is_active', 'license_slots', ['is_active'])


def downgrade() -> None:
    op.drop_table('license_slots')
    op.drop_table('license_tokens')
    op.drop_table('instances')
    op.drop_table('license_products')
    op.drop_table('cloud_init_templates')
