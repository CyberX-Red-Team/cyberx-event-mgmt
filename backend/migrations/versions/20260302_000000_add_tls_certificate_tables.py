"""Add ca_chains and tls_certificates tables

Revision ID: 20260302_000000
Revises: 20260228_000000
Create Date: 2026-03-02 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260302_000000'
down_revision = '20260228_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CA Chains table
    op.create_table(
        'ca_chains',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False),

        # R2 storage keys for CA files
        sa.Column('signing_cert_r2_key', sa.String(500), nullable=True),
        sa.Column('signing_key_r2_key', sa.String(500), nullable=True),
        sa.Column('ca_chain_r2_key', sa.String(500), nullable=True),

        # step-ca sidecar
        sa.Column('render_service_id', sa.String(100), nullable=True),
        sa.Column('step_ca_url', sa.String(500), nullable=True),
        sa.Column('step_ca_provisioner', sa.String(100), server_default='cyberx'),
        sa.Column('step_ca_status', sa.String(20), nullable=False, server_default='stopped'),

        # Certificate defaults
        sa.Column('default_duration', sa.String(20), server_default='2160h'),
        sa.Column('allow_wildcard', sa.Boolean(), server_default=sa.text('true')),

        # Tracking
        sa.Column('created_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('idx_ca_chain_event_id', 'ca_chains', ['event_id'])
    op.create_index('idx_ca_chain_status', 'ca_chains', ['step_ca_status'])

    # TLS Certificates table
    op.create_table(
        'tls_certificates',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ca_chain_id', sa.Integer(), sa.ForeignKey('ca_chains.id', ondelete='CASCADE'), nullable=False),

        # Certificate details
        sa.Column('common_name', sa.String(255), nullable=False),
        sa.Column('sans', sa.Text(), nullable=True),  # JSON array
        sa.Column('is_wildcard', sa.Boolean(), server_default=sa.text('false')),
        sa.Column('serial_number', sa.String(100), nullable=True),
        sa.Column('fingerprint', sa.String(100), nullable=True),

        # R2 storage
        sa.Column('cert_bundle_r2_key', sa.String(500), nullable=True),
        sa.Column('private_key_r2_key', sa.String(500), nullable=True),

        # Status and lifecycle
        sa.Column('status', sa.String(20), nullable=False, server_default='issued'),
        sa.Column('issued_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('expires_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('revocation_reason', sa.Text(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )

    op.create_index('idx_tls_cert_user_id', 'tls_certificates', ['user_id'])
    op.create_index('idx_tls_cert_event_id', 'tls_certificates', ['event_id'])
    op.create_index('idx_tls_cert_ca_chain_id', 'tls_certificates', ['ca_chain_id'])
    op.create_index('idx_tls_cert_status', 'tls_certificates', ['status'])
    op.create_index('idx_tls_cert_common_name', 'tls_certificates', ['common_name'])


def downgrade() -> None:
    op.drop_index('idx_tls_cert_common_name', table_name='tls_certificates')
    op.drop_index('idx_tls_cert_status', table_name='tls_certificates')
    op.drop_index('idx_tls_cert_ca_chain_id', table_name='tls_certificates')
    op.drop_index('idx_tls_cert_event_id', table_name='tls_certificates')
    op.drop_index('idx_tls_cert_user_id', table_name='tls_certificates')
    op.drop_table('tls_certificates')

    op.drop_index('idx_ca_chain_status', table_name='ca_chains')
    op.drop_index('idx_ca_chain_event_id', table_name='ca_chains')
    op.drop_table('ca_chains')
