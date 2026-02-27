"""Webhook handlers for external services."""
import logging
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

logger = logging.getLogger(__name__)


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
            else:
                logger.warning(
                    f"SendGrid webhook event not processed: "
                    f"type={event.get('event')}, email={event.get('email')}"
                )

        logger.info(
            f"SendGrid webhook batch: {processed_count}/{len(events)} events processed"
        )

        return {
            "status": "ok",
            "processed": processed_count,
            "total": len(events)
        }

    except Exception as e:
        # Log error but return 200 to prevent SendGrid from retrying
        logger.error(f"SendGrid webhook error: {e}", exc_info=True)
        return {"status": "error", "message": "Internal processing error"}


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
    Handle Keycloak event listener webhook events.

    Keycloak can be configured to send events via an HTTP event listener SPI.
    Events include user login, registration, password changes, and admin actions.

    Security:
    - Verifies HMAC-SHA256 signature if KEYCLOAK_WEBHOOK_SECRET is configured
    - Logs events to audit trail
    """
    # Verify webhook signature if secret is configured
    if settings.KEYCLOAK_WEBHOOK_SECRET:
        raw_body = await request.body()
        signature = request.headers.get("X-Keycloak-Signature", "")

        if not _verify_keycloak_signature(
            raw_body, signature, settings.KEYCLOAK_WEBHOOK_SECRET
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )

    try:
        data = await request.json()

        event_type = (data.get("type") or "").upper()
        user_data = data.get("details", {})
        username = user_data.get("username", "")
        realm = data.get("realmId", "")

        logger.info(
            f"Keycloak webhook: type={event_type}, username={username}, realm={realm}"
        )

        if event_type == "LOGIN":
            # User authenticated in the exercise environment
            if username:
                from sqlalchemy import select as sa_select
                from app.models.user import User
                from app.services.audit_service import AuditService
                result = await db.execute(
                    sa_select(User).where(User.pandas_username == username)
                )
                user = result.scalar_one_or_none()
                if user:
                    audit = AuditService(db)
                    await audit.log_action(
                        action="KEYCLOAK_LOGIN",
                        user_id=user.id,
                        details={
                            "username": username,
                            "realm": realm,
                            "ip_address": user_data.get("ipAddress"),
                        }
                    )
                    await db.commit()

        elif event_type == "REGISTER":
            # Self-registration in Keycloak (unexpected — users are pre-provisioned)
            logger.warning(
                f"Unexpected Keycloak self-registration: username={username}"
            )

        elif event_type in ("UPDATE_PASSWORD", "RESET_PASSWORD"):
            # Password changed directly in Keycloak
            logger.info(
                f"Password changed in Keycloak for username={username}"
            )

        elif event_type in ("ADMIN_EVENT", "UPDATE_CREDENTIAL"):
            # Admin action in Keycloak
            logger.info(
                f"Keycloak admin event: {data.get('operationType', 'unknown')} "
                f"resource={data.get('resourceType', 'unknown')}"
            )

        return {"status": "ok", "event": event_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Keycloak webhook error: {e}", exc_info=True)
        return {"status": "error", "message": "Internal processing error"}


def _verify_keycloak_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Keycloak webhook HMAC-SHA256 signature."""
    if not signature:
        logger.warning("Keycloak webhook missing signature header")
        return False

    import hmac
    import hashlib

    expected = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


@router.get("/health")
async def webhook_health():
    """Health check for webhook endpoints."""
    return {"status": "healthy", "webhooks": ["sendgrid", "discord", "keycloak"]}
