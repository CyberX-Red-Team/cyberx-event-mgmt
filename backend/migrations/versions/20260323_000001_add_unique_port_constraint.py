"""Add unique constraint on (redirector_id, listen_port) and CHECK on protocol

Revision ID: 20260323_000001
Revises: 20260323_000000
Create Date: 2026-03-23 00:00:01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '20260323_000001'
down_revision: Union[str, None] = '20260323_000000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        'uq_stream_configs_redirector_port',
        'stream_configs',
        ['redirector_id', 'listen_port'],
    )
    op.create_check_constraint(
        'ck_stream_protocol',
        'stream_configs',
        "protocol IN ('tcp', 'udp', 'dns')",
    )


def downgrade() -> None:
    op.drop_constraint('ck_stream_protocol', 'stream_configs', type_='check')
    op.drop_constraint('uq_stream_configs_redirector_port', 'stream_configs', type_='unique')
