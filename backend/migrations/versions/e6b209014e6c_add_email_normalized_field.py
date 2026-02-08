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


def normalize_email(email: str) -> str:
    """
    Normalize email address for consistent storage.

    - Lowercase
    - Strip whitespace
    - Gmail-specific: remove periods from local part
    - Preserve plus addressing
    """
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


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()

    # Step 1: Add email_normalized column as nullable
    print("Adding email_normalized column...")
    op.add_column('users', sa.Column('email_normalized', sa.String(255), nullable=True))

    # Step 2: Populate email_normalized with normalized emails
    print("Populating email_normalized from existing emails...")
    try:
        # Fetch all users
        result = connection.execute(sa.text("SELECT id, email FROM users"))
        users = result.fetchall()

        print(f"Found {len(users)} users to update")

        # Update each user with normalized email
        for user_id, email in users:
            try:
                normalized = normalize_email(email)
                connection.execute(
                    sa.text("UPDATE users SET email_normalized = :normalized WHERE id = :id"),
                    {"normalized": normalized, "id": user_id}
                )
            except Exception as e:
                print(f"Error normalizing email for user {user_id}: {e}")
                # Set to original email if normalization fails
                connection.execute(
                    sa.text("UPDATE users SET email_normalized = :email WHERE id = :id"),
                    {"email": email.lower() if email else '', "id": user_id}
                )

        # Note: Alembic manages the transaction, don't commit here
        print("Email normalization complete")

    except Exception as e:
        print(f"Error during email normalization: {e}")
        raise

    # Step 3: Make email_normalized non-nullable
    print("Making email_normalized non-nullable...")
    op.alter_column('users', 'email_normalized', nullable=False)

    # Step 4: Add index and unique constraint on email_normalized
    print("Adding index and unique constraint...")
    op.create_index('ix_users_email_normalized', 'users', ['email_normalized'])
    op.create_unique_constraint('uq_users_email_normalized', 'users', ['email_normalized'])

    # Step 5: Remove unique constraint from email field (if it exists)
    print("Checking for unique constraint on email field...")

    # Query to find unique constraints on the email column
    constraint_query = sa.text("""
        SELECT constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
        WHERE tc.table_name = 'users'
          AND tc.constraint_type = 'UNIQUE'
          AND ccu.column_name = 'email'
    """)

    result = connection.execute(constraint_query)
    constraint_rows = result.fetchall()

    if constraint_rows:
        constraint_name = constraint_rows[0][0]
        print(f"Found unique constraint '{constraint_name}' on email field, dropping...")
        op.drop_constraint(constraint_name, 'users', type_='unique')
        print(f"Dropped constraint: {constraint_name}")
    else:
        print("No unique constraint found on email field (may only have index), skipping...")

    print("Migration complete!")


def downgrade() -> None:
    """Downgrade schema."""
    # Restore unique constraint on email
    op.create_unique_constraint('users_email_key', 'users', ['email'])

    # Remove email_normalized column and constraints
    op.drop_constraint('uq_users_email_normalized', 'users', type_='unique')
    op.drop_index('ix_users_email_normalized', 'users')
    op.drop_column('users', 'email_normalized')
