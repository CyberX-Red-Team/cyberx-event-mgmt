"""Add redirectors and stream_configs tables

Revision ID: 20260323_000000
Revises: 20260321_000000
Create Date: 2026-03-23 00:00:00

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260323_000000'
down_revision: Union[str, None] = '20260321_000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # redirectors
    # ------------------------------------------------------------------
    op.create_table(
        'redirectors',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('current_ip', sa.String(45), nullable=False),
        sa.Column('ssh_port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('ssh_username', sa.String(255), nullable=False),
        sa.Column('ssh_private_key', sa.Text(), nullable=False),
        sa.Column('ssh_key_passphrase', sa.Text(), nullable=True),
        sa.Column('nginx_stream_dir', sa.String(500), nullable=False,
                  server_default='/etc/nginx/stream.d'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, server_default='unknown'),
        sa.Column('last_deployed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('last_tested_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_redirectors_name', 'redirectors', ['name'], unique=True)
    op.create_index('ix_redirectors_status', 'redirectors', ['status'])

    # ------------------------------------------------------------------
    # stream_configs
    # ------------------------------------------------------------------
    op.create_table(
        'stream_configs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column(
            'redirector_id', sa.String(36),
            sa.ForeignKey('redirectors.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('protocol', sa.String(10), nullable=False, server_default='tcp'),
        sa.Column('listen_port', sa.Integer(), nullable=False),
        sa.Column('cs_ip', sa.String(255), nullable=False),
        sa.Column('cs_port', sa.Integer(), nullable=False),
        sa.Column('access_control_enabled', sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column('allowed_cidrs', sa.JSON(), nullable=True),
        sa.Column('ssl_enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('ssl_cert_path', sa.String(500), nullable=True),
        sa.Column('ssl_key_path', sa.String(500), nullable=True),
        sa.Column('ssl_protocols', sa.String(100), nullable=False,
                  server_default='TLSv1.2 TLSv1.3'),
        sa.Column('ssl_ciphers', sa.String(200), nullable=False,
                  server_default='HIGH:!aNULL:!MD5'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_stream_configs_redirector_id', 'stream_configs', ['redirector_id'])
    op.create_index('ix_stream_configs_enabled', 'stream_configs', ['enabled'])


def downgrade() -> None:
    op.drop_index('ix_stream_configs_enabled', table_name='stream_configs')
    op.drop_index('ix_stream_configs_redirector_id', table_name='stream_configs')
    op.drop_table('stream_configs')

    op.drop_index('ix_redirectors_status', table_name='redirectors')
    op.drop_index('ix_redirectors_name', table_name='redirectors')
    op.drop_table('redirectors')
