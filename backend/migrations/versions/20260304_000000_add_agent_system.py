"""Add agent task system

Creates the agent_tasks table for dispatching tasks to instance agents,
and adds agent authentication columns to the instances table.

Revision ID: 20260304_000000
Revises: 20260302_000001
Create Date: 2026-03-04 00:00:00

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260304_000000'
down_revision = '20260302_000001'
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    """Check if a column exists in the given table."""
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = :table AND column_name = :column"
    ), {"table": table, "column": column})
    return result.fetchone() is not None


def upgrade() -> None:
    # Create agent_tasks table
    op.create_table(
        'agent_tasks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('instance_id', sa.Integer(),
                  sa.ForeignKey('instances.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('task_type', sa.String(50), nullable=False),
        sa.Column('payload', sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column('status', sa.String(20), server_default='PENDING',
                  nullable=False),
        sa.Column('result', sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now()),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_by_user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'),
                  nullable=True),
    )

    # Indexes for agent_tasks
    op.create_index('idx_agent_tasks_instance_status',
                    'agent_tasks', ['instance_id', 'status'])
    op.create_index('idx_agent_tasks_task_type',
                    'agent_tasks', ['task_type'])

    # Add agent columns to instances table
    if not _column_exists('instances', 'agent_token_hash'):
        op.add_column('instances',
                      sa.Column('agent_token_hash', sa.String(64),
                                nullable=True))
        op.create_index('idx_instances_agent_token_hash',
                        'instances', ['agent_token_hash'])

    if not _column_exists('instances', 'agent_registered_ip'):
        op.add_column('instances',
                      sa.Column('agent_registered_ip', sa.String(50),
                                nullable=True))

    if not _column_exists('instances', 'agent_last_heartbeat'):
        op.add_column('instances',
                      sa.Column('agent_last_heartbeat',
                                sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    # Remove agent columns from instances
    if _column_exists('instances', 'agent_last_heartbeat'):
        op.drop_column('instances', 'agent_last_heartbeat')
    if _column_exists('instances', 'agent_registered_ip'):
        op.drop_column('instances', 'agent_registered_ip')
    if _column_exists('instances', 'agent_token_hash'):
        op.drop_index('idx_instances_agent_token_hash',
                      table_name='instances')
        op.drop_column('instances', 'agent_token_hash')

    # Drop agent_tasks table
    op.drop_index('idx_agent_tasks_task_type', table_name='agent_tasks')
    op.drop_index('idx_agent_tasks_instance_status',
                  table_name='agent_tasks')
    op.drop_table('agent_tasks')
