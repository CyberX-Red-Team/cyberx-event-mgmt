"""Webhook security utilities for signature verification."""
import hmac
import hashlib
import base64
import time
from typing import Optional


def verify_sendgrid_signature(
    payload: bytes,
    signature: str,
    timestamp: str,
    verification_key: str
) -> bool:
    """
    Verify SendGrid webhook signature using HMAC-SHA256.

    SendGrid signs webhooks with: base64(HMAC-SHA256(verification_key, timestamp + payload))

    Args:
        payload: Raw request body (bytes)
        signature: X-Twilio-Email-Event-Webhook-Signature header value
        timestamp: X-Twilio-Email-Event-Webhook-Timestamp header value
        verification_key: Your SendGrid verification key (from dashboard)

    Returns:
        True if signature is valid, False otherwise

    Security Notes:
        - Uses constant-time comparison to prevent timing attacks
        - Signature format: base64(HMAC-SHA256(key, timestamp + payload))

    SendGrid Documentation:
        https://docs.sendgrid.com/for-developers/tracking-events/getting-started-event-webhook-security-features
    """
    if not verification_key:
        # If no key configured, skip verification (dev mode only)
        return True

    if not signature or not timestamp:
        return False

    try:
        # SendGrid's signature algorithm:
        # 1. Concatenate timestamp + payload (payload as string)
        signed_payload = (timestamp + payload.decode('utf-8')).encode('utf-8')

        # 2. Compute HMAC-SHA256 with verification key
        expected_signature = hmac.new(
            verification_key.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).digest()

        # 3. Base64 encode the signature
        expected_signature_b64 = base64.b64encode(expected_signature).decode('utf-8')

        # 4. Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(signature, expected_signature_b64)

    except (ValueError, UnicodeDecodeError, AttributeError):
        return False


def verify_timestamp_freshness(
    timestamp: str,
    max_age_seconds: int = 600
) -> bool:
    """
    Verify webhook timestamp is recent (prevents replay attacks).

    Args:
        timestamp: Unix timestamp as string
        max_age_seconds: Maximum age in seconds (default: 10 minutes)

    Returns:
        True if timestamp is fresh, False if too old or from future

    Security Notes:
        - Prevents replay attacks by rejecting old webhooks
        - Also rejects timestamps from the future (clock skew protection)
        - Default 10-minute window balances security vs clock drift tolerance
    """
    try:
        webhook_time = int(timestamp)
        current_time = int(time.time())
        age = current_time - webhook_time

        # Check if webhook is too old OR from the future (> 1 minute ahead)
        # Allow small future timestamps due to clock drift (60 seconds)
        return -60 <= age <= max_age_seconds

    except (ValueError, TypeError):
        return False
