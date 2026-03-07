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
