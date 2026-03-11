"""Add email_template_id to participant_actions

Revision ID: 20260225_002041
Revises: 20260224_000001
Create Date: 2026-02-25 00:20:41

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260225_002041'
down_revision = '20260224_000001'
branch_labels = None
depends_on = None


def upgrade():
    """Add email_template_id column to participant_actions table."""
    op.add_column('participant_actions',
        sa.Column('email_template_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_participant_actions_email_template',
        'participant_actions', 'email_templates',
        ['email_template_id'], ['id'],
        ondelete='SET NULL'
    )


def downgrade():
    """Remove email_template_id column from participant_actions table."""
    op.drop_constraint('fk_participant_actions_email_template', 'participant_actions', type_='foreignkey')
    op.drop_column('participant_actions', 'email_template_id')
