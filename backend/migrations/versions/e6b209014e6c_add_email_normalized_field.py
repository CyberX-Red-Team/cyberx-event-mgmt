"""add_email_normalized_field

Revision ID: e6b209014e6c
Revises: 4b6039cd8b1a
Create Date: 2026-02-08 08:10:31.285844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6b209014e6c'
down_revision: Union[str, Sequence[str], None] = '4b6039cd8b1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def normalize_email_sql(email: str) -> str:
    """
    SQL function to normalize email addresses.

    - Lowercase
    - Strip whitespace
    - Gmail-specific: remove periods from local part
    - Preserve plus addressing
    """
    # This will be done in Python in the data migration step
    pass


def upgrade() -> None:
    """Upgrade schema."""
    # Step 1: Add email_normalized column as nullable
    op.add_column('users', sa.Column('email_normalized', sa.String(255), nullable=True))

    # Step 2: Populate email_normalized with normalized emails using Python
    # We need to fetch all users and normalize their emails
    connection = op.get_bind()

    # Define normalization function inline
    def normalize_email(email):
        if not email:
            return email
        email = email.strip().lower()
        if '@' not in email:
            return email
        local_part, domain = email.rsplit('@', 1)
        # Gmail normalization: remove periods
        gmail_domains = {'gmail.com', 'googlemail.com'}
        if domain in gmail_domains or domain.endswith('.google.com'):
            local_part = local_part.replace('.', '')
        return f"{local_part}@{domain}"

    # Fetch all users
    result = connection.execute(sa.text("SELECT id, email FROM users"))
    users = result.fetchall()

    # Update each user with normalized email
    for user_id, email in users:
        normalized = normalize_email(email)
        connection.execute(
            sa.text("UPDATE users SET email_normalized = :normalized WHERE id = :id"),
            {"normalized": normalized, "id": user_id}
        )

    # Step 3: Make email_normalized non-nullable and add unique constraint
    op.alter_column('users', 'email_normalized', nullable=False)
    op.create_index('ix_users_email_normalized', 'users', ['email_normalized'])
    op.create_unique_constraint('uq_users_email_normalized', 'users', ['email_normalized'])

    # Step 4: Remove unique constraint from email field (keep it indexed for sending)
    # Note: The constraint name might vary, let's try to drop it
    try:
        op.drop_constraint('users_email_key', 'users', type_='unique')
    except Exception:
        # Constraint might have different name or not exist
        pass


def downgrade() -> None:
    """Downgrade schema."""
    # Restore unique constraint on email
    op.create_unique_constraint('users_email_key', 'users', ['email'])

    # Remove email_normalized column and constraints
    op.drop_constraint('uq_users_email_normalized', 'users', type_='unique')
    op.drop_index('ix_users_email_normalized', 'users')
    op.drop_column('users', 'email_normalized')
