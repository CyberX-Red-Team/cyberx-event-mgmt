"""Webhook security utilities for signature verification."""
import base64
import time
import logging

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger(__name__)


def verify_sendgrid_signature(
    payload: bytes,
    signature: str,
    timestamp: str,
    verification_key: str
) -> bool:
    """
    Verify SendGrid Event Webhook signature using ECDSA.

    SendGrid signs webhooks with ECDSA (P-256 / SHA-256). The verification
    key from the SendGrid dashboard is a base64-encoded DER public key.

    Signed data = timestamp + payload (raw bytes concatenation).

    Args:
        payload: Raw request body (bytes)
        signature: X-Twilio-Email-Event-Webhook-Signature header value (base64)
        timestamp: X-Twilio-Email-Event-Webhook-Timestamp header value
        verification_key: Base64-encoded ECDSA public key from SendGrid dashboard

    Returns:
        True if signature is valid, False otherwise

    SendGrid Documentation:
        https://docs.sendgrid.com/for-developers/tracking-events/getting-started-event-webhook-security-features
    """
    if not verification_key:
        # If no key configured, skip verification (dev mode only)
        return True

    if not signature or not timestamp:
        logger.warning("SendGrid webhook missing signature or timestamp header")
        return False

    try:
        # 1. Decode the verification key (base64 → DER public key)
        public_key_der = base64.b64decode(verification_key)
        public_key = serialization.load_der_public_key(public_key_der)

        # 2. Build the signed payload: timestamp + raw body
        signed_payload = timestamp.encode('utf-8') + payload

        # 3. Decode the signature from base64
        decoded_signature = base64.b64decode(signature)

        # 4. Verify ECDSA signature (P-256 / SHA-256)
        public_key.verify(
            decoded_signature,
            signed_payload,
            ECDSA(hashes.SHA256())
        )

        return True

    except InvalidSignature:
        logger.warning("SendGrid webhook signature verification failed")
        return False
    except Exception as e:
        logger.error(f"SendGrid webhook signature verification error: {e}")
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
