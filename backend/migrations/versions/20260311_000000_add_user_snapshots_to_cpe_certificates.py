"""Add user identity snapshot fields to cpe_certificates.

Preserves participant and admin identity on certificate records even if
the user is later deleted (FK uses ondelete=SET NULL).  Backfills
existing rows from the users table.

Revision ID: 20260311_000000
Revises: 20260310_000001
Create Date: 2026-03-11
"""
from alembic import op
import sqlalchemy as sa

revision = '20260311_000000'
down_revision = '20260310_000001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Participant (certificate recipient)
    op.add_column('cpe_certificates', sa.Column('user_email', sa.String(255), nullable=True))
    op.add_column('cpe_certificates', sa.Column('user_name', sa.String(500), nullable=True))

    # Issuer
    op.add_column('cpe_certificates', sa.Column('issued_by_name', sa.String(500), nullable=True))

    # Revoker
    op.add_column('cpe_certificates', sa.Column('revoked_by_name', sa.String(500), nullable=True))

    # Backfill participant snapshots
    op.execute(sa.text("""
        UPDATE cpe_certificates c
        SET user_email = u.email,
            user_name = TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
        FROM users u
        WHERE c.user_id = u.id
          AND c.user_email IS NULL
    """))

    # Backfill issuer snapshots
    op.execute(sa.text("""
        UPDATE cpe_certificates c
        SET issued_by_name = TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
        FROM users u
        WHERE c.issued_by_user_id = u.id
          AND c.issued_by_name IS NULL
    """))

    # Backfill revoker snapshots
    op.execute(sa.text("""
        UPDATE cpe_certificates c
        SET revoked_by_name = TRIM(COALESCE(u.first_name, '') || ' ' || COALESCE(u.last_name, ''))
        FROM users u
        WHERE c.revoked_by_user_id = u.id
          AND c.revoked_by_name IS NULL
    """))


def downgrade() -> None:
    op.drop_column('cpe_certificates', 'revoked_by_name')
    op.drop_column('cpe_certificates', 'issued_by_name')
    op.drop_column('cpe_certificates', 'user_name')
    op.drop_column('cpe_certificates', 'user_email')
