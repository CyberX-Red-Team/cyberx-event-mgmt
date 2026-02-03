"""Seed script to create invitation reminder email templates."""
import asyncio
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.email_template import EmailTemplate


# Template 1: First Reminder (7 days after invite)
TEMPLATE_1 = {
    "name": "invite_reminder_1",
    "display_name": "Invitation Reminder - Stage 1",
    "description": "First reminder sent 7 days after initial invitation",
    "subject": "Reminder: RSVP for {event_name}",
    "html_content": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RSVP Reminder</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #f8f9fa; padding: 30px; border-radius: 10px;">
        <h1 style="color: #dc3545; margin-top: 0;">CyberX Red Team</h1>

        <h2 style="color: #495057;">Hi {first_name},</h2>

        <p>We wanted to follow up on your invitation to <strong>{event_name}</strong>.</p>

        <p>We sent you an invitation about a week ago, and we haven't heard back from you yet. We'd love to have you join us!</p>

        <div style="background-color: #fff; padding: 20px; border-left: 4px solid #dc3545; margin: 20px 0;">
            <p style="margin: 0;"><strong>Event Details:</strong></p>
            <p style="margin: 5px 0;">📅 Start Date: {event_start_date}</p>
            <p style="margin: 5px 0;">⏰ {days_until_event} days until the event!</p>
        </div>

        <p>Please confirm your participation as soon as possible so we can plan accordingly.</p>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{confirmation_url}" style="background-color: #dc3545; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                CONFIRM YOUR PARTICIPATION
            </a>
        </div>

        <p style="font-size: 14px; color: #6c757d;">
            If you have any questions or concerns, please don't hesitate to reach out to us.
        </p>

        <hr style="border: none; border-top: 1px solid #dee2e6; margin: 30px 0;">

        <p style="font-size: 12px; color: #6c757d; text-align: center;">
            CyberX Red Team<br>
            This is an automated reminder
        </p>
    </div>
</body>
</html>""",
    "text_content": """Hi {first_name},

We wanted to follow up on your invitation to {event_name}.

We sent you an invitation about a week ago, and we haven't heard back from you yet. We'd love to have you join us!

Event Details:
Start Date: {event_start_date}
{days_until_event} days until the event!

Please confirm your participation as soon as possible: {confirmation_url}

If you have any questions or concerns, please don't hesitate to reach out to us.

CyberX Red Team
""",
    "available_variables": [
        "first_name", "last_name", "email", "event_name",
        "event_start_date", "days_until_event", "confirmation_url",
        "reminder_stage"
    ],
    "is_active": True,
    "is_system": True
}

# Template 2: Second Reminder (14 days after invite)
TEMPLATE_2 = {
    "name": "invite_reminder_2",
    "display_name": "Invitation Reminder - Stage 2",
    "description": "Second reminder sent 14 days after initial invitation",
    "subject": "Don't Miss Out: {event_name} is Coming Soon!",
    "html_content": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>RSVP Reminder</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #f8f9fa; padding: 30px; border-radius: 10px;">
        <h1 style="color: #dc3545; margin-top: 0;">CyberX Red Team</h1>

        <h2 style="color: #495057;">Hi {first_name},</h2>

        <p><strong>{event_name}</strong> is approaching quickly, and we still haven't received your RSVP!</p>

        <p>We really hope you can join us for this exciting event. Time is running out to confirm your spot.</p>

        <div style="background-color: #fff3cd; padding: 20px; border-left: 4px solid #ffc107; margin: 20px 0;">
            <p style="margin: 0;"><strong>⚠️ Event Starting Soon:</strong></p>
            <p style="margin: 5px 0;">📅 Start Date: {event_start_date}</p>
            <p style="margin: 5px 0;">⏰ Only {days_until_event} days left!</p>
        </div>

        <p><strong>Why should you join us?</strong></p>
        <ul>
            <li>Network with fellow red teamers</li>
            <li>Hands-on cybersecurity challenges</li>
            <li>Learn cutting-edge techniques</li>
            <li>Be part of an elite community</li>
        </ul>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{confirmation_url}" style="background-color: #dc3545; color: white; padding: 15px 30px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold;">
                CONFIRM YOUR SPOT NOW
            </a>
        </div>

        <p style="font-size: 14px; color: #6c757d;">
            Questions? Reach out to us - we're here to help!
        </p>

        <hr style="border: none; border-top: 1px solid #dee2e6; margin: 30px 0;">

        <p style="font-size: 12px; color: #6c757d; text-align: center;">
            CyberX Red Team<br>
            This is an automated reminder
        </p>
    </div>
</body>
</html>""",
    "text_content": """Hi {first_name},

{event_name} is approaching quickly, and we still haven't received your RSVP!

We really hope you can join us for this exciting event. Time is running out to confirm your spot.

Event Starting Soon:
Start Date: {event_start_date}
Only {days_until_event} days left!

Why should you join us?
- Network with fellow red teamers
- Hands-on cybersecurity challenges
- Learn cutting-edge techniques
- Be part of an elite community

Please confirm your participation now: {confirmation_url}

Questions? Reach out to us - we're here to help!

CyberX Red Team
""",
    "available_variables": [
        "first_name", "last_name", "email", "event_name",
        "event_start_date", "days_until_event", "confirmation_url",
        "reminder_stage"
    ],
    "is_active": True,
    "is_system": True
}

# Template 3: Final Reminder (3 days before event)
TEMPLATE_3 = {
    "name": "invite_reminder_final",
    "display_name": "Invitation Reminder - Final",
    "description": "Final reminder sent 3 days before event starts",
    "subject": "⚠️ Last Chance: RSVP for {event_name} by Tomorrow!",
    "html_content": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Final RSVP Reminder</title>
</head>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <div style="background-color: #f8f9fa; padding: 30px; border-radius: 10px;">
        <h1 style="color: #dc3545; margin-top: 0;">CyberX Red Team</h1>

        <div style="background-color: #dc3545; color: white; padding: 20px; border-radius: 5px; text-align: center; margin-bottom: 20px;">
            <h2 style="margin: 0; font-size: 24px;">⚠️ FINAL REMINDER ⚠️</h2>
        </div>

        <h2 style="color: #495057;">Hi {first_name},</h2>

        <p><strong>This is your last chance to RSVP for {event_name}!</strong></p>

        <p>The event starts in just <strong>{days_until_event} days</strong>, and we need to finalize our participant list.</p>

        <div style="background-color: #f8d7da; padding: 20px; border-left: 4px solid #dc3545; margin: 20px 0;">
            <p style="margin: 0;"><strong>🚨 URGENT: Final Deadline Approaching</strong></p>
            <p style="margin: 5px 0;">📅 Event Starts: {event_start_date}</p>
            <p style="margin: 5px 0;">⏰ RSVP by tomorrow to secure your spot!</p>
        </div>

        <p><strong>Don't miss out on this opportunity!</strong></p>

        <p>If we don't hear from you soon, we'll assume you can't make it and we'll need to give your spot to someone on the waitlist.</p>

        <div style="text-align: center; margin: 30px 0;">
            <a href="{confirmation_url}" style="background-color: #dc3545; color: white; padding: 20px 40px; text-decoration: none; border-radius: 5px; display: inline-block; font-weight: bold; font-size: 18px;">
                RSVP NOW - LAST CHANCE!
            </a>
        </div>

        <p style="font-size: 14px; color: #6c757d; font-style: italic;">
            <strong>Note:</strong> This is our final reminder. If you can't attend, no action is needed - we understand that schedules change!
        </p>

        <hr style="border: none; border-top: 1px solid #dee2e6; margin: 30px 0;">

        <p style="font-size: 12px; color: #6c757d; text-align: center;">
            CyberX Red Team<br>
            This is your final automated reminder
        </p>
    </div>
</body>
</html>""",
    "text_content": """Hi {first_name},

⚠️ FINAL REMINDER ⚠️

This is your last chance to RSVP for {event_name}!

The event starts in just {days_until_event} days, and we need to finalize our participant list.

🚨 URGENT: Final Deadline Approaching
Event Starts: {event_start_date}
RSVP by tomorrow to secure your spot!

Don't miss out on this opportunity!

If we don't hear from you soon, we'll assume you can't make it and we'll need to give your spot to someone on the waitlist.

RSVP NOW - LAST CHANCE: {confirmation_url}

Note: This is our final reminder. If you can't attend, no action is needed - we understand that schedules change!

CyberX Red Team
""",
    "available_variables": [
        "first_name", "last_name", "email", "event_name",
        "event_start_date", "days_until_event", "confirmation_url",
        "reminder_stage", "is_final_reminder"
    ],
    "is_active": True,
    "is_system": True
}


async def seed_reminder_templates():
    """Create the three reminder email templates in the database."""
    async with AsyncSessionLocal() as session:
        templates_to_create = [TEMPLATE_1, TEMPLATE_2, TEMPLATE_3]

        for template_data in templates_to_create:
            # Check if template already exists
            result = await session.execute(
                select(EmailTemplate).where(EmailTemplate.name == template_data["name"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"✓ Template '{template_data['name']}' already exists - skipping")
                continue

            # Create new template
            template = EmailTemplate(**template_data)
            session.add(template)
            print(f"✓ Created template: {template_data['name']}")

        await session.commit()
        print("\n✓ All reminder templates created successfully!")


if __name__ == "__main__":
    asyncio.run(seed_reminder_templates())
