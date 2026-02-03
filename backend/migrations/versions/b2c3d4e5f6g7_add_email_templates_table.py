"""Add email_templates table

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-23 10:00:00.000000

"""
from typing import Sequence, Union
import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed data for email templates
SEED_TEMPLATES = [
    {
        "name": "invite",
        "display_name": "Invitation Email",
        "description": "Initial invitation sent to participants with login credentials and confirmation link",
        "subject": "You're Invited to CyberX {event_name}!",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Welcome to CyberX, {first_name}!</h2>
<p>You have been invited to participate in CyberX {event_name}.</p>
<p>Your login credentials are:</p>
<ul>
    <li><strong>Username:</strong> {pandas_username}</li>
    <li><strong>Password:</strong> {pandas_password}</li>
</ul>
<p>Please confirm your participation by clicking the link below:</p>
<p><a href="{confirm_url}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Confirm Participation</a></p>
<p>If you have any questions, please contact your sponsor or the CyberX team.</p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Welcome to CyberX, {first_name}!

You have been invited to participate in CyberX {event_name}.

Your login credentials are:
- Username: {pandas_username}
- Password: {pandas_password}

Please confirm your participation by visiting: {confirm_url}

If you have any questions, please contact your sponsor or the CyberX team.

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "pandas_username", "pandas_password", "event_name", "confirm_url"],
        "is_system": True,
    },
    {
        "name": "password",
        "display_name": "Credentials Email",
        "description": "Send login credentials to participants",
        "subject": "Your CyberX Credentials",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<p>Here are your CyberX login credentials:</p>
<ul>
    <li><strong>Username:</strong> {pandas_username}</li>
    <li><strong>Password:</strong> {pandas_password}</li>
</ul>
<p>Please keep these credentials secure and do not share them with anyone.</p>
<p>You can log in at: <a href="{login_url}">{login_url}</a></p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

Here are your CyberX login credentials:
- Username: {pandas_username}
- Password: {pandas_password}

Please keep these credentials secure and do not share them with anyone.

You can log in at: {login_url}

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "pandas_username", "pandas_password", "login_url"],
        "is_system": True,
    },
    {
        "name": "reminder",
        "display_name": "Participation Reminder",
        "description": "Reminder for participants who haven't confirmed their participation",
        "subject": "Reminder: Please Confirm Your CyberX Participation",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<p>This is a friendly reminder that we haven't received your confirmation for CyberX {event_name}.</p>
<p>Please confirm your participation by clicking the link below:</p>
<p><a href="{confirm_url}" style="background-color: #28a745; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Confirm Now</a></p>
<p>If you're no longer able to participate, please let us know so we can offer your spot to someone else.</p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

This is a friendly reminder that we haven't received your confirmation for CyberX {event_name}.

Please confirm your participation by visiting: {confirm_url}

If you're no longer able to participate, please let us know so we can offer your spot to someone else.

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "event_name", "confirm_url"],
        "is_system": True,
    },
    {
        "name": "vpn_config",
        "display_name": "VPN Configuration",
        "description": "Send VPN configuration with WireGuard attachment",
        "subject": "Your CyberX VPN Configuration",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<p>Your VPN configuration for CyberX {event_name} is attached to this email.</p>
<p><strong>Instructions:</strong></p>
<ol>
    <li>Download and install WireGuard from <a href="https://www.wireguard.com/install/">wireguard.com</a></li>
    <li>Import the attached configuration file</li>
    <li>Connect to the VPN when the event begins</li>
</ol>
<p>Please do not share your VPN configuration with anyone.</p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

Your VPN configuration for CyberX {event_name} is attached to this email.

Instructions:
1. Download and install WireGuard from https://www.wireguard.com/install/
2. Import the attached configuration file
3. Connect to the VPN when the event begins

Please do not share your VPN configuration with anyone.

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "event_name"],
        "is_system": True,
    },
    {
        "name": "survey",
        "display_name": "Feedback Survey",
        "description": "Post-event feedback survey request",
        "subject": "CyberX Feedback Survey",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<p>Thank you for participating in CyberX {event_name}!</p>
<p>We'd love to hear your feedback. Please take a few minutes to complete our survey:</p>
<p><a href="{survey_url}" style="background-color: #17a2b8; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Take Survey</a></p>
<p>Your feedback helps us improve future events.</p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

Thank you for participating in CyberX {event_name}!

We'd love to hear your feedback. Please take a few minutes to complete our survey:
{survey_url}

Your feedback helps us improve future events.

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "event_name", "survey_url"],
        "is_system": True,
    },
    {
        "name": "orientation",
        "display_name": "Orientation Information",
        "description": "Orientation session details and instructions",
        "subject": "CyberX Orientation Information",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<p>You're registered for the CyberX {event_name} orientation session!</p>
<p><strong>Details:</strong></p>
<ul>
    <li><strong>Date:</strong> {orientation_date}</li>
    <li><strong>Time:</strong> {orientation_time}</li>
    <li><strong>Location:</strong> {orientation_location}</li>
</ul>
<p>Please arrive 15 minutes early. If you can't attend, please let us know.</p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

You're registered for the CyberX {event_name} orientation session!

Details:
- Date: {orientation_date}
- Time: {orientation_time}
- Location: {orientation_location}

Please arrive 15 minutes early. If you can't attend, please let us know.

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "event_name", "orientation_date", "orientation_time", "orientation_location"],
        "is_system": True,
    },
    {
        "name": "announcement",
        "display_name": "General Announcement",
        "description": "General announcements to participants",
        "subject": "CyberX Announcement: {announcement_title}",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<h3>{announcement_title}</h3>
<div style="margin: 20px 0;">
{announcement_body}
</div>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

{announcement_title}

{announcement_body}

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "announcement_title", "announcement_body"],
        "is_system": True,
    },
    {
        "name": "event_start",
        "display_name": "Event Starting",
        "description": "Notification that the event is beginning",
        "subject": "CyberX {event_name} is Starting!",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<p>CyberX {event_name} is starting!</p>
<p><strong>Event Details:</strong></p>
<ul>
    <li><strong>Start Date:</strong> {start_date}</li>
    <li><strong>Start Time:</strong> {start_time}</li>
</ul>
<p>Make sure you have:</p>
<ol>
    <li>Your VPN connected</li>
    <li>Your credentials ready</li>
    <li>Reviewed the rules and guidelines</li>
</ol>
<p><a href="{login_url}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Login Now</a></p>
<p>Good luck!</p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

CyberX {event_name} is starting!

Event Details:
- Start Date: {start_date}
- Start Time: {start_time}

Make sure you have:
1. Your VPN connected
2. Your credentials ready
3. Reviewed the rules and guidelines

Login at: {login_url}

Good luck!

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "event_name", "start_date", "start_time", "login_url"],
        "is_system": True,
    },
    {
        "name": "event_end",
        "display_name": "Event Completed",
        "description": "Thank you message after event concludes",
        "subject": "Thank You for Participating in CyberX {event_name}!",
        "html_content": """<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
<h2>Hello {first_name},</h2>
<p>Thank you for participating in CyberX {event_name}!</p>
<p>We hope you had a great experience and learned something new.</p>
<p><strong>Next Steps:</strong></p>
<ul>
    <li>Please complete our feedback survey to help us improve: <a href="{survey_url}">Take Survey</a></li>
    <li>Stay connected with the CyberX community</li>
    <li>Look out for announcements about future events</li>
</ul>
<p>Thank you for being part of CyberX!</p>
<p>Best regards,<br>CyberX Red Team</p>
</body>
</html>""",
        "text_content": """Hello {first_name},

Thank you for participating in CyberX {event_name}!

We hope you had a great experience and learned something new.

Next Steps:
- Please complete our feedback survey to help us improve: {survey_url}
- Stay connected with the CyberX community
- Look out for announcements about future events

Thank you for being part of CyberX!

Best regards,
CyberX Red Team""",
        "available_variables": ["first_name", "last_name", "email", "event_name", "survey_url"],
        "is_system": True,
    },
]


def upgrade() -> None:
    """Create email_templates table and seed data."""
    # Create the table
    op.create_table(
        'email_templates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('html_content', sa.Text(), nullable=False),
        sa.Column('text_content', sa.Text(), nullable=True),
        sa.Column('available_variables', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='[]'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_email_templates_is_active', 'email_templates', ['is_active'], unique=False)
    op.create_index('idx_email_templates_is_system', 'email_templates', ['is_system'], unique=False)
    op.create_index(op.f('ix_email_templates_id'), 'email_templates', ['id'], unique=False)
    op.create_index(op.f('ix_email_templates_name'), 'email_templates', ['name'], unique=True)

    # Seed the templates
    email_templates = sa.table(
        'email_templates',
        sa.column('name', sa.String),
        sa.column('display_name', sa.String),
        sa.column('description', sa.Text),
        sa.column('subject', sa.String),
        sa.column('html_content', sa.Text),
        sa.column('text_content', sa.Text),
        sa.column('available_variables', postgresql.JSONB),
        sa.column('is_system', sa.Boolean),
        sa.column('is_active', sa.Boolean),
    )

    op.bulk_insert(
        email_templates,
        [
            {
                'name': t['name'],
                'display_name': t['display_name'],
                'description': t['description'],
                'subject': t['subject'],
                'html_content': t['html_content'],
                'text_content': t['text_content'],
                'available_variables': t['available_variables'],
                'is_system': t['is_system'],
                'is_active': True,
            }
            for t in SEED_TEMPLATES
        ]
    )


def downgrade() -> None:
    """Drop email_templates table."""
    op.drop_index(op.f('ix_email_templates_name'), table_name='email_templates')
    op.drop_index(op.f('ix_email_templates_id'), table_name='email_templates')
    op.drop_index('idx_email_templates_is_system', table_name='email_templates')
    op.drop_index('idx_email_templates_is_active', table_name='email_templates')
    op.drop_table('email_templates')
