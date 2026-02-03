"""add email workflows table

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2024-01-31 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'd4e5f6g7h8i9'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade():
    # Create email_workflows table
    op.create_table(
        'email_workflows',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('trigger_event', sa.String(length=100), nullable=False),
        sa.Column('template_name', sa.String(length=100), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('custom_vars', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('delay_minutes', sa.Integer(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index('idx_workflow_name', 'email_workflows', ['name'], unique=True)
    op.create_index('idx_workflow_trigger', 'email_workflows', ['trigger_event'])
    op.create_index('idx_workflow_enabled', 'email_workflows', ['is_enabled'])
    op.create_index('idx_workflow_trigger_enabled', 'email_workflows', ['trigger_event', 'is_enabled'])

    # Seed default workflows
    op.execute("""
        INSERT INTO email_workflows (name, display_name, description, trigger_event, template_name, priority, custom_vars, is_enabled, is_system)
        VALUES
        (
            'user_confirmation',
            'User Confirmation Email',
            'Sends password email when a user is confirmed for participation',
            'user_confirmed',
            'password',
            2,
            '{"login_url": "https://portal.cyberxredteam.org/login"}'::jsonb,
            true,
            true
        ),
        (
            'user_discovery',
            'User Discovery Email',
            'Fallback workflow to catch any confirmed users who have not received a password email',
            'user_created',
            'password',
            5,
            '{"login_url": "https://portal.cyberxredteam.org/login"}'::jsonb,
            true,
            true
        ),
        (
            'vpn_assigned',
            'VPN Credentials Email',
            'Sends VPN configuration when credentials are assigned to a user',
            'vpn_assigned',
            'vpn_config',
            3,
            '{}'::jsonb,
            false,
            true
        ),
        (
            'event_reminder',
            'Event Reminder Email',
            'Reminds users about upcoming event participation',
            'event_reminder',
            'reminder',
            5,
            '{}'::jsonb,
            false,
            true
        ),
        (
            'survey_request',
            'Post-Event Survey Email',
            'Requests feedback after event completion',
            'survey_request',
            'survey',
            7,
            '{}'::jsonb,
            false,
            true
        )
    """)


def downgrade():
    # Drop indexes
    op.drop_index('idx_workflow_trigger_enabled', table_name='email_workflows')
    op.drop_index('idx_workflow_enabled', table_name='email_workflows')
    op.drop_index('idx_workflow_trigger', table_name='email_workflows')
    op.drop_index('idx_workflow_name', table_name='email_workflows')

    # Drop table
    op.drop_table('email_workflows')
