"""Remove 13 legacy/obsolete columns from users table.

Phase 1 (dead columns): sharepoint_id, azure_object_id, pandas_groups,
slated_in_person, discord_invite_sent, discord_invite_code.

Phase 2 (vestigial columns): future_participation, remove_permanently,
invite_id, check_microsoft_email_sent, survey_response_timestamp,
in_person_email_sent, orientation_invite_email_sent.

Revision ID: 20260309_000004
Revises: 20260309_000003
Create Date: 2026-03-09
"""
from alembic import op
import sqlalchemy as sa


revision = '20260309_000004'
down_revision = '20260309_000003'
branch_labels = None
depends_on = None


COLUMNS_TO_DROP = [
    # Phase 1: clearly dead
    'sharepoint_id',
    'azure_object_id',
    'pandas_groups',
    'slated_in_person',
    'discord_invite_sent',
    'discord_invite_code',
    # Phase 2: vestigial
    'future_participation',
    'remove_permanently',
    'invite_id',
    'check_microsoft_email_sent',
    'survey_response_timestamp',
    'in_person_email_sent',
    'orientation_invite_email_sent',
]


def _column_exists(table: str, column: str) -> bool:
    """Check if a column exists in the given table."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    return result.fetchone() is not None


def upgrade() -> None:
    for col in COLUMNS_TO_DROP:
        if _column_exists('users', col):
            op.drop_column('users', col)


def downgrade() -> None:
    # Re-add columns with their original types and defaults
    columns = [
        sa.Column('sharepoint_id', sa.String(50), unique=True, nullable=True),
        sa.Column('azure_object_id', sa.String(100), nullable=True),
        sa.Column('pandas_groups', sa.String(500), nullable=True),
        sa.Column('slated_in_person', sa.Boolean(), default=False),
        sa.Column('discord_invite_sent', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('discord_invite_code', sa.String(50), nullable=True),
        sa.Column('future_participation', sa.String(20), default='UNKNOWN'),
        sa.Column('remove_permanently', sa.String(20), default='UNKNOWN'),
        sa.Column('invite_id', sa.String(50), nullable=True),
        sa.Column('check_microsoft_email_sent', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('survey_response_timestamp', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('in_person_email_sent', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('orientation_invite_email_sent', sa.TIMESTAMP(timezone=True), nullable=True),
    ]
    for col in columns:
        if not _column_exists('users', col.name):
            op.add_column('users', col)
