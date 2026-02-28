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
    Handle Keycloak event webhooks from the p2-inc/keycloak-events plugin.

    EventRepresentation payload fields:
    - uid: Unique event ID
    - time: Event timestamp (epoch ms)
    - realmId, realmName: Realm identifiers
    - type: Prefixed event type (e.g. "access.LOGIN", "access.REGISTER")
    - operationType: For admin events (CREATE, UPDATE, DELETE, ACTION)
    - resourcePath, resourceType: For admin events
    - authDetails: {realmId, clientId, userId, ipAddress, username, sessionId}
    - details: Key-value map with additional event context
    - error: Error string if the event represents a failure

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
            logger.warning(
                f"Keycloak webhook signature verification failed. "
                f"Header present: {bool(signature)}, "
                f"IP: {request.client.host if request.client else 'unknown'}"
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid webhook signature"
            )

    try:
        data = await request.json()

        if settings.KEYCLOAK_WEBHOOK_DEBUG:
            import json
            logger.info(f"Keycloak webhook raw payload: {json.dumps(data, indent=2, default=str)}")

        # p2-inc/keycloak-events uses prefixed type (e.g. "access.LOGIN")
        raw_type = data.get("type") or ""
        # Strip the prefix (access., admin., etc.) to get the base event type
        event_type = raw_type.rsplit(".", 1)[-1].upper() if raw_type else ""

        # authDetails contains user context (username, IP, etc.)
        auth_details = data.get("authDetails") or {}
        username = auth_details.get("username", "")
        ip_address = auth_details.get("ipAddress")
        client_id = auth_details.get("clientId")
        session_id = auth_details.get("sessionId")

        # details is a sibling key-value map with extra context
        details = data.get("details") or {}

        realm = data.get("realmId", "")
        realm_name = data.get("realmName", "")
        error = data.get("error")

        logger.info(
            f"Keycloak webhook: type={raw_type}, username={username}, "
            f"realm={realm_name or realm}"
        )

        if error:
            logger.warning(
                f"Keycloak event error: type={raw_type}, username={username}, "
                f"error={error}"
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
                            "realm": realm_name or realm,
                            "ip_address": ip_address,
                            "client_id": client_id,
                            "session_id": session_id,
                        }
                    )
                    await db.commit()

                # PowerDNS-Admin: auto-assign user to configured account
                if client_id == "powerdns-admin":
                    if settings.POWERDNS_API_URL and settings.POWERDNS_USERNAME:
                        try:
                            from app.services.powerdns_service import PowerDNSService
                            pdns = PowerDNSService()
                            pdns_result = await pdns.ensure_user_in_account(
                                username, settings.POWERDNS_ACCOUNT_NAME
                            )
                            logger.info(
                                f"PowerDNS account assignment: username={username}, "
                                f"result={pdns_result['status']}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"PowerDNS account assignment failed for "
                                f"{username}: {e}"
                            )

        elif event_type == "LOGIN_ERROR":
            logger.warning(
                f"Keycloak login failure: username={username}, "
                f"ip={ip_address}, error={error}"
            )

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

        elif event_type == "LOGOUT":
            logger.info(
                f"Keycloak logout: username={username}, session={session_id}"
            )

        # Admin events come via operationType + resourceType/resourcePath
        operation_type = data.get("operationType")
        if operation_type:
            resource_type = data.get("resourceType", "unknown")
            resource_path = data.get("resourcePath", "")
            logger.info(
                f"Keycloak admin event: {operation_type} "
                f"resource={resource_type} path={resource_path}"
            )

        return {"status": "ok", "event": raw_type}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Keycloak webhook error: {e}", exc_info=True)
        return {"status": "error", "message": "Internal processing error"}


def _verify_keycloak_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify Keycloak webhook HMAC-SHA256 signature.

    The p2-inc/keycloak-events plugin sends HMAC-SHA256 as hex.
    We compare in both hex and Base64 to be robust.
    """
    if not signature:
        logger.warning("Keycloak webhook missing signature header")
        return False

    import base64
    import hmac
    import hashlib

    # Strip optional "sha256=" prefix (some webhook implementations add it)
    sig_value = signature
    if sig_value.startswith("sha256="):
        sig_value = sig_value[7:]

    computed = hmac.new(
        secret.encode('utf-8'),
        payload,
        hashlib.sha256
    ).digest()

    expected_hex = computed.hex()
    expected_b64 = base64.b64encode(computed).decode('utf-8')

    # Debug logging to diagnose signature mismatch
    logger.info(
        f"Keycloak signature debug: "
        f"received='{sig_value[:16]}...' (len={len(sig_value)}), "
        f"expected_hex='{expected_hex[:16]}...' (len={len(expected_hex)}), "
        f"expected_b64='{expected_b64[:16]}...' (len={len(expected_b64)}), "
        f"payload_len={len(payload)}"
    )

    # Compare as hex (p2-inc/keycloak-events default format)
    if hmac.compare_digest(expected_hex, sig_value):
        return True

    # Fallback: compare as Base64
    return hmac.compare_digest(expected_b64, sig_value)


@router.get("/health")
async def webhook_health():
    """Health check for webhook endpoints."""
    return {"status": "healthy", "webhooks": ["sendgrid", "discord", "keycloak"]}
