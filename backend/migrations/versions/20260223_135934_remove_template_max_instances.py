"""Remove max_instances from instance_templates

Revision ID: 20260223_135934
Revises: 20260223_000001
Create Date: 2026-02-23 13:59:34

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260223_135934'
down_revision = '20260223_000001'
branch_labels = None
depends_on = None


def upgrade():
    """Remove max_instances column from instance_templates.

    Instance limits are now managed at the provider level via app_settings
    with keys like 'provider_max_instances_openstack'.
    """
    op.drop_column('instance_templates', 'max_instances')


def downgrade():
    """Add back max_instances column."""
    op.add_column('instance_templates',
        sa.Column('max_instances', sa.Integer(), nullable=False, server_default='0')
    )
