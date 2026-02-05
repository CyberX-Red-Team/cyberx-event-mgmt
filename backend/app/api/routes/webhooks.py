"""Webhook handlers for external services."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db
from app.services.email_service import EmailService
from app.config import get_settings
from app.utils.webhook_security import (
    verify_sendgrid_signature,
    verify_timestamp_freshness
)


settings = get_settings()
router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


def get_email_service(db: AsyncSession = Depends(get_db)) -> EmailService:
    """Get email service dependency."""
    return EmailService(db)


@router.post("/sendgrid")
async def sendgrid_webhook(
    request: Request,
    x_twilio_email_event_webhook_signature: Optional[str] = Header(
        None,
        alias="X-Twilio-Email-Event-Webhook-Signature"
    ),
    x_twilio_email_event_webhook_timestamp: Optional[str] = Header(
        None,
        alias="X-Twilio-Email-Event-Webhook-Timestamp"
    ),
    email_service: EmailService = Depends(get_email_service)
):
    """
    Handle SendGrid event webhooks with signature verification.

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

    Security:
    - Verifies HMAC-SHA256 signature to ensure webhook authenticity
    - Checks timestamp to prevent replay attacks
    - Only processes webhooks from SendGrid
    """
    # Get raw body for signature verification
    raw_body = await request.body()

    # Verify signature if verification key is configured
    if settings.SENDGRID_WEBHOOK_VERIFICATION_KEY:
        # Check signature
        if not verify_sendgrid_signature(
            payload=raw_body,
            signature=x_twilio_email_event_webhook_signature or "",
            timestamp=x_twilio_email_event_webhook_timestamp or "",
            verification_key=settings.SENDGRID_WEBHOOK_VERIFICATION_KEY
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )

        # Check timestamp freshness (prevents replay attacks)
        if not verify_timestamp_freshness(
            x_twilio_email_event_webhook_timestamp or "",
            max_age_seconds=600  # 10 minutes
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook timestamp is too old or invalid"
            )

    # Parse and process events
    try:
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
