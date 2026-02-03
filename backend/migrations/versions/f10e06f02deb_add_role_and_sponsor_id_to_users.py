"""Add role and sponsor_id to users

Revision ID: f10e06f02deb
Revises: 2d3773c84f96
Create Date: 2026-01-12 21:24:03.420028

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f10e06f02deb'
down_revision: Union[str, Sequence[str], None] = '2d3773c84f96'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add role column with default value for existing data
    op.add_column('users', sa.Column('role', sa.String(length=20), nullable=False, server_default='participant'))

    # Add sponsor_id column
    op.add_column('users', sa.Column('sponsor_id', sa.Integer(), nullable=True))

    # Create indexes
    op.create_index('idx_users_role', 'users', ['role'], unique=False)
    op.create_index('idx_users_sponsor_id', 'users', ['sponsor_id'], unique=False)

    # Create foreign key
    op.create_foreign_key('fk_users_sponsor_id', 'users', 'users', ['sponsor_id'], ['id'], ondelete='SET NULL')

    # Migrate existing is_admin users to admin role
    op.execute("UPDATE users SET role = 'admin' WHERE is_admin = true")

    # Remove server default after migration (optional, keeps column clean)
    op.alter_column('users', 'role', server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_users_sponsor_id', 'users', type_='foreignkey')
    op.drop_index('idx_users_sponsor_id', table_name='users')
    op.drop_index('idx_users_role', table_name='users')
    op.drop_column('users', 'sponsor_id')
    op.drop_column('users', 'role')
