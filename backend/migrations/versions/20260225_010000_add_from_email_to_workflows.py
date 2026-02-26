"""Add from_email and from_name to email_workflows

Revision ID: 20260225_010000
Revises: 20260225_002041
Create Date: 2026-02-25 01:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260225_010000'
down_revision = '20260225_002041'
branch_labels = None
depends_on = None


def upgrade():
    """Add from_email and from_name columns to email_workflows table."""
    op.add_column('email_workflows',
        sa.Column('from_email', sa.String(255), nullable=True)
    )
    op.add_column('email_workflows',
        sa.Column('from_name', sa.String(255), nullable=True)
    )


def downgrade():
    """Remove from_email and from_name columns from email_workflows table."""
    op.drop_column('email_workflows', 'from_name')
    op.drop_column('email_workflows', 'from_email')
