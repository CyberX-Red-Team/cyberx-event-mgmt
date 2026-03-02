"""Rename ca_chains columns from root/intermediate to signing/chain

The original 4-column design (root_cert, root_key, intermediate_cert,
intermediate_key) assumed a rigid 2-tier CA hierarchy. The new 3-column
design (signing_cert, signing_key, ca_chain) supports any CA depth:
admin uploads the signing CA cert + key, plus the chain of trust above it.

Revision ID: 20260302_000001
Revises: 20260302_000000
Create Date: 2026-03-02 12:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260302_000001'
down_revision = '20260302_000000'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Rename intermediate columns to signing (these hold the signing CA)
    op.alter_column('ca_chains', 'intermediate_cert_r2_key',
                     new_column_name='signing_cert_r2_key')
    op.alter_column('ca_chains', 'intermediate_key_r2_key',
                     new_column_name='signing_key_r2_key')

    # Rename root_cert to ca_chain (stores the full chain above signing cert)
    op.alter_column('ca_chains', 'root_cert_r2_key',
                     new_column_name='ca_chain_r2_key')

    # Drop root_key column (root private key is not needed)
    op.drop_column('ca_chains', 'root_key_r2_key')


def downgrade() -> None:
    # Re-add root_key column
    op.add_column('ca_chains',
                   sa.Column('root_key_r2_key', sa.String(500), nullable=True))

    # Rename back
    op.alter_column('ca_chains', 'ca_chain_r2_key',
                     new_column_name='root_cert_r2_key')
    op.alter_column('ca_chains', 'signing_cert_r2_key',
                     new_column_name='intermediate_cert_r2_key')
    op.alter_column('ca_chains', 'signing_key_r2_key',
                     new_column_name='intermediate_key_r2_key')
