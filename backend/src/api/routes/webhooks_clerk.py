"""
Clerk webhook handlers for identity synchronization.

SECURITY: All webhooks MUST verify Svix signature before processing.
Clerk uses Svix for webhook delivery and signature verification.

Documentation: https://clerk.com/docs/webhooks

Supported Events:
- user.created, user.updated, user.deleted
- organization.created, organization.updated, organization.deleted
- organizationMembership.created, organizationMembership.updated, organizationMembership.deleted
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.database.session import get_db_session_sync
from src.services.clerk_webhook_handler import ClerkWebhookHandler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


class WebhookResponse(BaseModel):
    """Standard webhook response."""
    received: bool = True
    status: str = "processed"
    message: Optional[str] = None


def verify_clerk_webhook(
    payload: bytes,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    webhook_secret: str,
) -> bool:
    """
    Verify Clerk webhook signature using Svix.

    Clerk uses Svix for webhook delivery. The signature is verified using:
    - svix-id: Unique message identifier
    - svix-timestamp: Unix timestamp of the message
    - svix-signature: Signature(s) to verify

    Args:
        payload: Raw request body bytes
        svix_id: Svix-Id header
        svix_timestamp: Svix-Timestamp header
        svix_signature: Svix-Signature header
        webhook_secret: Clerk webhook signing secret

    Returns:
        True if signature is valid, False otherwise
    """
    if not all([svix_id, svix_timestamp, svix_signature, webhook_secret]):
        logger.warning("Missing Svix headers or webhook secret")
        return False

    try:
        # Try using svix library if available
        from svix.webhooks import Webhook

        wh = Webhook(webhook_secret)
        wh.verify(
            payload,
            {
                "svix-id": svix_id,
                "svix-timestamp": svix_timestamp,
                "svix-signature": svix_signature,
            }
        )
        return True

    except ImportError:
        # Fallback: Manual signature verification
        logger.warning("svix library not installed, using manual verification")
        return _verify_signature_manual(
            payload, svix_id, svix_timestamp, svix_signature, webhook_secret
        )

    except Exception as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        return False


def _verify_signature_manual(
    payload: bytes,
    svix_id: str,
    svix_timestamp: str,
    svix_signature: str,
    webhook_secret: str,
) -> bool:
    """
    Manual signature verification fallback.

    Svix signature format: v1,<base64-signature>
    Signed content: "{svix_id}.{svix_timestamp}.{payload}"

    Args:
        payload: Raw request body bytes
        svix_id: Svix-Id header
        svix_timestamp: Svix-Timestamp header
        svix_signature: Svix-Signature header
        webhook_secret: Webhook signing secret (format: whsec_...)

    Returns:
        True if signature is valid, False otherwise
    """
    import hmac
    import hashlib
    import base64
    import time

    try:
        # Validate timestamp (prevent replay attacks - 5 minute tolerance)
        try:
            ts = int(svix_timestamp)
            now = int(time.time())
            if abs(now - ts) > 300:  # 5 minutes
                logger.warning("Webhook timestamp outside tolerance window")
                return False
        except ValueError:
            return False

        # Extract secret key (remove 'whsec_' prefix and decode)
        if webhook_secret.startswith("whsec_"):
            secret_key = base64.b64decode(webhook_secret[6:])
        else:
            secret_key = webhook_secret.encode()

        # Build signed content
        signed_content = f"{svix_id}.{svix_timestamp}.".encode() + payload

        # Parse signatures (format: v1,sig1 v1,sig2 ...)
        signatures = svix_signature.split(" ")

        for sig in signatures:
            if not sig.startswith("v1,"):
                continue

            expected_sig = sig[3:]  # Remove 'v1,' prefix

            # Compute HMAC-SHA256
            computed = hmac.new(
                secret_key,
                signed_content,
                hashlib.sha256
            )
            computed_sig = base64.b64encode(computed.digest()).decode()

            if hmac.compare_digest(computed_sig, expected_sig):
                return True

        return False

    except Exception as e:
        logger.error(f"Manual signature verification error: {e}")
        return False


@router.post("/clerk", response_model=WebhookResponse)
async def handle_clerk_webhook(
    request: Request,
    svix_id: Optional[str] = Header(None, alias="svix-id"),
    svix_timestamp: Optional[str] = Header(None, alias="svix-timestamp"),
    svix_signature: Optional[str] = Header(None, alias="svix-signature"),
):
    """
    Handle incoming Clerk webhooks.

    This endpoint receives all Clerk webhook events and routes them
    to appropriate handlers for identity synchronization.

    Security:
    - Verifies Svix signature using CLERK_WEBHOOK_SECRET
    - Rejects requests with invalid or missing signatures
    - Does not require JWT authentication (webhooks are server-to-server)

    Returns:
        WebhookResponse with processing status
    """
    # Get webhook secret from environment
    webhook_secret = os.getenv("CLERK_WEBHOOK_SECRET")

    if not webhook_secret:
        logger.error("CLERK_WEBHOOK_SECRET not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook handler not configured",
        )

    # Get raw body for signature verification
    try:
        body = await request.body()
    except Exception as e:
        logger.error(f"Failed to read request body: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid request body",
        )

    # Verify signature
    if not verify_clerk_webhook(
        payload=body,
        svix_id=svix_id or "",
        svix_timestamp=svix_timestamp or "",
        svix_signature=svix_signature or "",
        webhook_secret=webhook_secret,
    ):
        logger.warning(
            "Clerk webhook signature verification failed",
            extra={
                "svix_id": svix_id,
                "has_timestamp": bool(svix_timestamp),
                "has_signature": bool(svix_signature),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    # Parse payload
    try:
        import json
        payload = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in webhook payload: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    # Extract event type
    event_type = payload.get("type")
    if not event_type:
        logger.warning("Missing event type in webhook payload")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing event type",
        )

    logger.info(
        "Received Clerk webhook",
        extra={
            "event_type": event_type,
            "svix_id": svix_id,
        }
    )

    # Process webhook with database session
    try:
        session = get_db_session_sync()
        try:
            handler = ClerkWebhookHandler(session)
            result = handler.handle_event(event_type, payload)

            logger.info(
                "Processed Clerk webhook",
                extra={
                    "event_type": event_type,
                    "result": result,
                }
            )

            return WebhookResponse(
                received=True,
                status=result.get("status", "processed"),
                message=f"Event {event_type} processed successfully",
            )

        except ValueError as e:
            # Invalid payload data
            logger.warning(f"Invalid webhook data: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            )

        except Exception as e:
            # Unexpected error - log but still return 200 to prevent retries
            # for non-recoverable errors
            logger.error(
                f"Error processing webhook: {e}",
                extra={"event_type": event_type},
                exc_info=True,
            )
            # Return 200 to acknowledge receipt (Clerk will retry on 4xx/5xx)
            return WebhookResponse(
                received=True,
                status="error",
                message=f"Error processing event: {str(e)}",
            )

        finally:
            session.close()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Database session error: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )


@router.get("/clerk/health")
async def clerk_webhook_health():
    """
    Health check for Clerk webhook endpoint.

    Used to verify the webhook endpoint is accessible.
    Does not require authentication.
    """
    webhook_secret = os.getenv("CLERK_WEBHOOK_SECRET")

    return {
        "status": "healthy",
        "webhook_secret_configured": bool(webhook_secret),
    }
