"""Add cpe_certificates table

Revision ID: 20260228_000000
Revises: 20260227_000001
Create Date: 2026-02-28 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260228_000000'
down_revision = '20260227_000001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'cpe_certificates',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('events.id', ondelete='CASCADE'), nullable=False),
        sa.Column('issued_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('certificate_number', sa.String(50), unique=True, nullable=False),
        sa.Column('cpe_hours', sa.Float(), nullable=False, server_default='32.0'),
        sa.Column('status', sa.String(20), nullable=False, server_default='issued'),
        sa.Column('has_nextcloud_login', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('has_powerdns_login', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('has_vpn_assigned', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('pdf_storage_key', sa.String(500), nullable=True),
        sa.Column('pdf_generated_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('revoked_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('revoked_by_user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('revocation_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'event_id', name='uq_cpe_user_event'),
    )

    op.create_index('idx_cpe_cert_number', 'cpe_certificates', ['certificate_number'])
    op.create_index('idx_cpe_user_id', 'cpe_certificates', ['user_id'])
    op.create_index('idx_cpe_event_id', 'cpe_certificates', ['event_id'])
    op.create_index('idx_cpe_status', 'cpe_certificates', ['status'])


def downgrade() -> None:
    op.drop_index('idx_cpe_status', table_name='cpe_certificates')
    op.drop_index('idx_cpe_event_id', table_name='cpe_certificates')
    op.drop_index('idx_cpe_user_id', table_name='cpe_certificates')
    op.drop_index('idx_cpe_cert_number', table_name='cpe_certificates')
    op.drop_table('cpe_certificates')
