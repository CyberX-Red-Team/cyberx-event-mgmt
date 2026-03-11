"""Make user_id nullable with SET NULL on record tables.

Preserves participant_actions, tls_certificates, cpe_certificates,
password_sync_queue, email_queue, and vpn_requests records when a user
is deleted, instead of cascading the delete to those rows.

Revision ID: 20260307_000003
Revises: 20260307_000002
Create Date: 2026-03-07
"""
from alembic import op
import sqlalchemy as sa

revision = '20260307_000003'
down_revision = '20260307_000002'
branch_labels = None
depends_on = None

# Tables to update: (table_name, fk_constraint_name)
TABLES = [
    ("participant_actions", "participant_actions_user_id_fkey"),
    ("tls_certificates", "tls_certificates_user_id_fkey"),
    ("cpe_certificates", "cpe_certificates_user_id_fkey"),
    ("password_sync_queue", "password_sync_queue_user_id_fkey"),
    ("email_queue", "email_queue_user_id_fkey"),
    ("vpn_requests", "vpn_requests_user_id_fkey"),
]


def upgrade() -> None:
    for table, fk_name in TABLES:
        # Drop old CASCADE FK
        op.drop_constraint(fk_name, table, type_="foreignkey")
        # Make column nullable
        op.alter_column(table, "user_id", existing_type=sa.Integer(), nullable=True)
        # Re-create FK with SET NULL
        op.create_foreign_key(fk_name, table, "users", ["user_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    for table, fk_name in TABLES:
        # Set any NULLs back (can't restore original user_id, but column must be NOT NULL)
        op.execute(sa.text(f"DELETE FROM {table} WHERE user_id IS NULL"))
        # Drop SET NULL FK
        op.drop_constraint(fk_name, table, type_="foreignkey")
        # Make column NOT NULL again
        op.alter_column(table, "user_id", existing_type=sa.Integer(), nullable=False)
        # Re-create FK with CASCADE
        op.create_foreign_key(fk_name, table, "users", ["user_id"], ["id"], ondelete="CASCADE")
