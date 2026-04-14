"""Backfill redirector visibility to match linked public instances.

Revision 20260413_000000 added the visibility column with a server
default of 'private'. Any redirector already linked to a public
instance is now in a state the new parity rules consider invalid:
non-owners lose visibility on a row whose parent instance is public,
and the row stays hidden until an owner manually flips it.

This backfill restores parity by promoting those rows to 'public'.
BYO redirectors (no linked instance) and rows linked to private
instances are left alone — their correct visibility is the owner's
explicit choice, not something we can infer.

Revision ID: 20260414_000000
Revises: 20260413_000000
Create Date: 2026-04-14 00:00:00
"""
from alembic import op


revision = "20260414_000000"
down_revision = "20260413_000000"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE redirectors
        SET visibility = 'public'
        WHERE visibility = 'private'
          AND instance_id IS NOT NULL
          AND instance_id IN (
              SELECT id FROM instances WHERE visibility = 'public'
          )
        """
    )


def downgrade():
    # Intentional no-op: we cannot distinguish rows the backfill
    # promoted from rows a user later set to 'public' on purpose.
    pass
