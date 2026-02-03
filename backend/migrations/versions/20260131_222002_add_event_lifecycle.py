"""add event lifecycle management

Revision ID: 20260131_222002
Revises: 20260131_205116
Create Date: 2026-01-31 22:20:02

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '20260131_222002'
down_revision = '20260131_205116'
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Add registration_open to events table (if not exists)
    op.add_column('events', sa.Column('registration_open', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('events', sa.Column('confirmation_expires_days', sa.Integer(), nullable=False, server_default='30'))

    # Add confirmation fields to users table
    op.add_column('users', sa.Column('confirmation_code', sa.String(100), nullable=True))
    op.add_column('users', sa.Column('confirmation_sent_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_accepted', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('users', sa.Column('terms_accepted_at', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('terms_version', sa.String(50), nullable=True))

    # Create indexes
    op.create_index('idx_users_confirmation_code', 'users', ['confirmation_code'], unique=True)

    # Seed default event for 2026 (inactive by default)
    op.execute("""
        INSERT INTO events (year, name, is_active, registration_open, terms_version, terms_content, created_at)
        VALUES (
            2026,
            'CyberX Red Team Exercise 2026',
            false,
            false,
            '2026-v1',
            '# CyberX Red Team Exercise 2026 - Terms and Conditions

## Participation Agreement

By confirming your participation, you agree to:

1. **Code of Conduct**: Maintain professional behavior
2. **Confidentiality**: Keep sensitive information confidential
3. **Legal Compliance**: Operate only within authorized scope
4. **Data Usage**: Allow anonymized data usage for training
5. **Communication**: Maintain responsive communication

Last Updated: January 31, 2026
Version: 2026-v1',
            NOW()
        )
        ON CONFLICT (year) DO NOTHING
    """)

def downgrade() -> None:
    op.drop_index('idx_users_confirmation_code', 'users')
    op.drop_column('users', 'terms_version')
    op.drop_column('users', 'terms_accepted_at')
    op.drop_column('users', 'terms_accepted')
    op.drop_column('users', 'confirmation_sent_at')
    op.drop_column('users', 'confirmation_code')
    op.drop_column('events', 'confirmation_expires_days')
    op.drop_column('events', 'registration_open')
