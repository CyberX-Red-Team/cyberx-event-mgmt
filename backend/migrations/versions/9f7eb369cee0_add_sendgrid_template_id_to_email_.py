"""add_sendgrid_template_id_to_email_templates

Revision ID: 9f7eb369cee0
Revises: 6088bc3a22f2
Create Date: 2026-02-02 15:21:41.119031

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f7eb369cee0'
down_revision: Union[str, Sequence[str], None] = '6088bc3a22f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add sendgrid_template_id column to email_templates table
    op.add_column('email_templates', sa.Column('sendgrid_template_id', sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove sendgrid_template_id column from email_templates table
    op.drop_column('email_templates', 'sendgrid_template_id')
