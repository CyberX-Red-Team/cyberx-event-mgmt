"""Webhook handlers for external services."""
import hmac
import hashlib
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.email_service import EmailService
from app.config import get_settings


settings = get_settings()
router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


def get_email_service(db: AsyncSession = Depends(get_db)) -> EmailService:
    """Get email service dependency."""
    return EmailService(db)


@router.post("/sendgrid")
async def sendgrid_webhook(
    request: Request,
    email_service: EmailService = Depends(get_email_service)
):
    """
    Handle SendGrid event webhooks.

    SendGrid sends events for:
    - processed: Email accepted for delivery
    - delivered: Email delivered to recipient
    - open: Recipient opened email
    - click: Recipient clicked a link
    - bounce: Email bounced
    - dropped: Email dropped (invalid, blocked, etc.)
    - spamreport: Recipient marked as spam
    - unsubscribe: Recipient unsubscribed
    - deferred: Email delivery deferred
    """
    try:
        # Parse JSON body
        events = await request.json()

        if not isinstance(events, list):
            events = [events]

        processed_count = 0
        for event in events:
            success = await email_service.process_webhook_event(event)
            if success:
                processed_count += 1

        return {
            "status": "ok",
            "processed": processed_count,
            "total": len(events)
        }

    except Exception as e:
        # Log error but return 200 to prevent SendGrid from retrying
        print(f"SendGrid webhook error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/sendgrid/inbound")
async def sendgrid_inbound_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle SendGrid inbound parse webhook for email replies.

    This can be used to process participant replies to automated emails.
    """
    try:
        # Parse form data (SendGrid sends inbound as multipart/form-data)
        form = await request.form()

        from_email = form.get("from")
        to_email = form.get("to")
        subject = form.get("subject")
        text = form.get("text")
        html = form.get("html")

        # Log inbound email for processing
        # TODO: Implement inbound email processing logic

        return {"status": "ok", "from": from_email, "subject": subject}

    except Exception as e:
        print(f"SendGrid inbound webhook error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/discord")
async def discord_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Discord webhook events.

    This can be used for:
    - New member joined server
    - Member left server
    - Role assignments
    """
    try:
        data = await request.json()

        event_type = data.get("t")  # Event type
        event_data = data.get("d")  # Event data

        if event_type == "GUILD_MEMBER_ADD":
            # New member joined
            user_id = event_data.get("user", {}).get("id")
            username = event_data.get("user", {}).get("username")

            # TODO: Update user record with Discord info

        elif event_type == "GUILD_MEMBER_REMOVE":
            # Member left
            user_id = event_data.get("user", {}).get("id")

            # TODO: Update user record

        return {"status": "ok", "event": event_type}

    except Exception as e:
        print(f"Discord webhook error: {e}")
        return {"status": "error", "message": str(e)}


@router.post("/keycloak")
async def keycloak_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handle Keycloak SSO webhook events.

    This can be used for:
    - User login events
    - User registration
    - Password changes
    """
    try:
        data = await request.json()

        event_type = data.get("type")
        user_data = data.get("details", {})

        if event_type == "LOGIN":
            # User logged in via Keycloak
            email = user_data.get("email")
            # TODO: Track login event

        elif event_type == "REGISTER":
            # New user registered via Keycloak
            email = user_data.get("email")
            # TODO: Create user record if needed

        return {"status": "ok", "event": event_type}

    except Exception as e:
        print(f"Keycloak webhook error: {e}")
        return {"status": "error", "message": str(e)}


@router.get("/health")
async def webhook_health():
    """Health check for webhook endpoints."""
    return {"status": "healthy", "webhooks": ["sendgrid", "discord", "keycloak"]}
