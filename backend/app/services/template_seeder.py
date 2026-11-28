"""Seed required email templates on startup (idempotent)."""
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.email_template import EmailTemplate

logger = logging.getLogger(__name__)

# Templates that must exist for the application to function.
# Only creates missing templates — never overwrites admin edits.
REQUIRED_TEMPLATES = [
    {
        "name": "admin_security_alert",
        "display_name": "Admin Security Alert",
        "description": "Sent to admins when a security lockout is triggered (rate limit exceeded on password reset, brute-force detection, etc.)",
        "subject": "\u26a0\ufe0f Security Alert: {lockout_type}",
        "html_content": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Security Alert</title>
</head>
<body style="font-family: 'Courier New', monospace; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
    <div style="border: 2px solid #dc2626; border-radius: 4px; padding: 30px;">
        <p style="font-size: 10px; letter-spacing: 3px; text-transform: uppercase; color: #dc2626; margin: 0 0 16px 0;">// SECURITY ALERT</p>

        <h1 style="font-family: -apple-system, BlinkMacSystemFont, sans-serif; font-weight: 700; font-size: 24px; color: #dc2626; margin: 0 0 24px 0;">{lockout_type}</h1>

        <p style="font-size: 14px; margin: 0 0 20px 0;">Hi {admin_name}, a security lockout was triggered on the CyberX Event Management platform.</p>

        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin: 20px 0;">
            <tr>
                <td style="padding: 12px 16px; background-color: #fef2f2; border-left: 3px solid #dc2626;">
                    <p style="font-size: 10px; letter-spacing: 2px; text-transform: uppercase; color: #64748b; margin: 0 0 4px 0;">DETAILS</p>
                    <p style="font-size: 14px; margin: 0; color: #1e293b;">{details}</p>
                </td>
            </tr>
        </table>

        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="margin: 20px 0; font-size: 13px;">
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e5e7eb; width: 120px; color: #64748b;">IP Address</td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e5e7eb; font-weight: 600;">{ip_address}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e5e7eb; color: #64748b;">Target Email</td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e5e7eb; font-weight: 600;">{target_email}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; border-bottom: 1px solid #e5e7eb; color: #64748b;">Timestamp</td>
                <td style="padding: 8px 0; border-bottom: 1px solid #e5e7eb; font-weight: 600;">{timestamp}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; color: #64748b;">User Agent</td>
                <td style="padding: 8px 0; font-size: 11px; word-break: break-all;">{user_agent}</td>
            </tr>
        </table>

        <p style="font-size: 13px; color: #64748b; margin: 24px 0 0 0;">
            This is an automated security notification. No action is required unless you suspect unauthorized activity.
            The offending IP has been temporarily rate-limited.
        </p>

        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">

        <p style="font-size: 11px; color: #94a3b8; text-align: center; margin: 0;">
            CyberX Red Team Collective &mdash; Event Management Platform
        </p>
    </div>
</body>
</html>""",
        "text_content": """SECURITY ALERT: {lockout_type}

Hi {admin_name},

A security lockout was triggered on the CyberX Event Management platform.

Details: {details}

IP Address: {ip_address}
Target Email: {target_email}
Timestamp: {timestamp}
User Agent: {user_agent}

This is an automated security notification. No action is required unless you suspect unauthorized activity.

---
CyberX Red Team Collective""",
        "available_variables": [
            "admin_name", "lockout_type", "ip_address",
            "user_agent", "target_email", "details", "timestamp"
        ],
        "is_active": True,
    },
    {
        "name": "account_deletion_warning",
        "display_name": "Account Deletion Notice (inactivity)",
        "description": "Sent 30 days before an account is deleted for two years without taking part in an event (data retention).",
        "subject": "Your CyberX Red Team account will be deleted on {deletion_date}",
        "html_content": """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Account deletion notice</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
    <div style="border: 1px solid #e5e7eb; border-radius: 4px; padding: 30px;">
        <p style="font-size: 14px; margin: 0 0 16px 0;">Hi {first_name},</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">You haven't taken part in a CyberX Red Team event for two years, so we'll delete your account and contact details on <strong>{deletion_date}</strong>.</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">If you'd like to keep them, sign in to the <a href="{login_url}">participant portal</a> or email us at <a href="mailto:{contact_email}">{contact_email}</a> before then.</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">We keep CPE certificate records so certificates can still be reissued and verified.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="font-size: 11px; color: #94a3b8; text-align: center; margin: 0;">
            CyberX Red Team &mdash; <a href="{privacy_policy_url}" style="color: #94a3b8;">Privacy Policy</a>
        </p>
    </div>
</body>
</html>""",
        "text_content": """Hi {first_name},

You haven't taken part in a CyberX Red Team event for two years, so we'll delete your account and contact details on {deletion_date}.

If you'd like to keep them, sign in to the participant portal ({login_url}) or email us at {contact_email} before then.

We keep CPE certificate records so certificates can still be reissued and verified.

---
CyberX Red Team
Privacy Policy: {privacy_policy_url}""",
        "available_variables": [
            "first_name", "deletion_date", "login_url", "contact_email", "privacy_policy_url",
        ],
        "is_active": True,
    },
    {
        "name": "event_closeout_reminder",
        "display_name": "Event Close-out Reminder (admins)",
        "description": "Sent to admins when an event ended more than 30 days ago and hasn't been archived (data retention).",
        "subject": "Close out {event_name}: ended {days_since_end} days ago",
        "html_content": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>Event close-out reminder</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px;">
    <p style="font-size: 14px;">Hi {first_name},</p>
    <p style="font-size: 14px;"><strong>{event_name}</strong> ended on {event_end_date} ({days_since_end} days ago) and hasn't been archived yet.</p>
    <p style="font-size: 14px;">The Privacy Policy says event access (network access, credentials and exercise systems) is deleted when we close out the event, normally within 30 days of it ending. Archive it from the <a href="{events_url}">Events page</a> (preview first: archiving tears down infrastructure).</p>
    <p style="font-size: 12px; color: #64748b;">This reminder repeats weekly until the event is archived.</p>
</body>
</html>""",
        "text_content": """Hi {first_name},

{event_name} ended on {event_end_date} ({days_since_end} days ago) and hasn't been archived yet.

The Privacy Policy says event access (network access, credentials and exercise systems) is deleted when we close out the event, normally within 30 days of it ending. Archive it from the Events page (preview first: archiving tears down infrastructure): {events_url}

This reminder repeats weekly until the event is archived.""",
        "available_variables": [
            "first_name", "event_name", "event_end_date", "days_since_end", "events_url",
        ],
        "is_active": True,
    },
    {
        "name": "data_export_ready",
        "display_name": "Your Data Export Is Ready",
        "description": "Sent to the address on file with a time-limited link to a copy of the person's data (access request).",
        "subject": "Your CyberX Red Team data",
        "html_content": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Your data</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
    <div style="border: 1px solid #e5e7eb; border-radius: 4px; padding: 30px;">
        <p style="font-size: 14px; margin: 0 0 16px 0;">Hi {first_name},</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">Here's the copy of the information we hold about you that you asked for.</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;"><a href="{download_url}">Download your data</a> (a ZIP file). The link stops working after {expiry_days} days.</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">If you didn't ask for this, email us at <a href="mailto:{contact_email}">{contact_email}</a>.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="font-size: 11px; color: #94a3b8; text-align: center; margin: 0;">CyberX Red Team &mdash; <a href="{privacy_policy_url}" style="color: #94a3b8;">Privacy Policy</a></p>
    </div>
</body>
</html>""",
        "text_content": """Hi {first_name},

Here's the copy of the information we hold about you that you asked for.

Download your data (a ZIP file): {download_url}
The link stops working after {expiry_days} days.

If you didn't ask for this, email us at {contact_email}.

---
CyberX Red Team
Privacy Policy: {privacy_policy_url}""",
        "available_variables": ["first_name", "download_url", "expiry_days", "contact_email", "privacy_policy_url"],
        "is_active": True,
    },
    {
        "name": "guardian_consent_needed",
        "display_name": "Guardian Consent Needed",
        "description": "Sent to a parent/guardian when a participant under 18 names them.",
        "subject": "Consent needed for {minor_name} to take part in {event_name}",
        "html_content": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Guardian Consent Needed</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
    <div style="border: 1px solid #e5e7eb; border-radius: 4px; padding: 30px;">
        <p style="font-size: 14px; margin: 0 0 16px 0;">Hi {first_name},</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">{minor_name} named you as their parent or guardian for {event_name}. People aged 16 or 17 can take part only with written consent from a parent or guardian who is also taking part in the event.</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">Review and give consent (or tell us you're not their parent or guardian) in the <a href="{portal_url}">participant portal</a>.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="font-size: 11px; color: #94a3b8; text-align: center; margin: 0;">CyberX Red Team &mdash; <a href="https://cyberxredteam.org/privacy" style="color: #94a3b8;">Privacy Policy</a></p>
    </div>
</body>
</html>""",
        "text_content": """Hi {first_name},

{minor_name} named you as their parent or guardian for {event_name}. People aged 16 or 17 can take part only with written consent from a parent or guardian who is also taking part in the event.

Review and give consent (or tell us you're not their parent or guardian) in the participant portal: {portal_url}.""",
        "available_variables": ['first_name', 'minor_name', 'event_name', 'portal_url'],
        "is_active": True,
    },
    {
        "name": "minor_access_suspended",
        "display_name": "Minor Access Suspended",
        "description": "Sent to a participant under 18 (and copied to their guardian) when guardian consent stops being valid.",
        "subject": "Your event access for {event_name} is paused",
        "html_content": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Minor Access Suspended</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
    <div style="border: 1px solid #e5e7eb; border-radius: 4px; padding: 30px;">
        <p style="font-size: 14px; margin: 0 0 16px 0;">Hi {first_name},</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">Your access for {event_name} is paused because the consent from your parent or guardian is no longer in place (for example, it was withdrawn, or they're no longer taking part).</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">Your parent or guardian can give consent again in their participant portal. Questions: hello@cyberxredteam.org.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="font-size: 11px; color: #94a3b8; text-align: center; margin: 0;">CyberX Red Team &mdash; <a href="https://cyberxredteam.org/privacy" style="color: #94a3b8;">Privacy Policy</a></p>
    </div>
</body>
</html>""",
        "text_content": """Hi {first_name},

Your access for {event_name} is paused because the consent from your parent or guardian is no longer in place (for example, it was withdrawn, or they're no longer taking part).

Your parent or guardian can give consent again in their participant portal. Questions: hello@cyberxredteam.org.""",
        "available_variables": ['first_name', 'event_name'],
        "is_active": True,
    },
    {
        "name": "minor_in_person_cancelled",
        "display_name": "Minor In-Person Attendance Cancelled",
        "description": "Sent to a participant under 18 (and copied to their guardian) when their in-person attendance is cancelled because their guardian isn't attending in person.",
        "subject": "In-person attendance for {event_name} cancelled",
        "html_content": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Minor In-Person Attendance Cancelled</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
    <div style="border: 1px solid #e5e7eb; border-radius: 4px; padding: 30px;">
        <p style="font-size: 14px; margin: 0 0 16px 0;">Hi {first_name},</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">You can attend {event_name} in person only if your parent or guardian also attends in person. They're no longer attending in person, so we've cancelled your in-person attendance. You can still take part remotely.</p>
        <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
        <p style="font-size: 11px; color: #94a3b8; text-align: center; margin: 0;">CyberX Red Team &mdash; <a href="https://cyberxredteam.org/privacy" style="color: #94a3b8;">Privacy Policy</a></p>
    </div>
</body>
</html>""",
        "text_content": """Hi {first_name},

You can attend {event_name} in person only if your parent or guardian also attends in person. They're no longer attending in person, so we've cancelled your in-person attendance. You can still take part remotely.""",
        "available_variables": ['first_name', 'event_name'],
        "is_active": True,
    },
    {
        "name": "admin_minor_alert",
        "display_name": "Admin Alert: Participant Under 18",
        "description": "Sent to admins when a participant under 18 needs attention (guardian not registered, link rejected, access suspended).",
        "subject": "Participant under 18 needs attention: {reason}",
        "html_content": """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>Admin Alert: Participant Under 18</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; padding: 20px; background-color: #ffffff;">
    <div style="border: 1px solid #e5e7eb; border-radius: 4px; padding: 30px;">
        <p style="font-size: 14px; margin: 0 0 16px 0;">Hi {first_name},</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">Participant #{minor_user_id} (under 18) needs attention: <strong>{reason}</strong>.</p>
        <p style="font-size: 14px; margin: 0 0 16px 0;">See the <a href="{minors_url}">Minors page</a>.</p>
    </div>
</body>
</html>""",
        "text_content": """Hi {first_name},

Participant #{minor_user_id} (under 18) needs attention: {reason}.

See the Minors page: {minors_url}.""",
        "available_variables": ['first_name', 'reason', 'minor_user_id', 'minors_url'],
        "is_active": True,
    },
]


async def seed_required_templates(session: AsyncSession) -> None:
    """Create any missing required templates. Does not overwrite existing ones."""
    for tmpl_data in REQUIRED_TEMPLATES:
        result = await session.execute(
            select(EmailTemplate).where(EmailTemplate.name == tmpl_data["name"])
        )
        if result.scalar_one_or_none():
            continue

        logger.info("  Seeding missing template: %s", tmpl_data["name"])
        session.add(EmailTemplate(**tmpl_data))

    await session.commit()
