"""
Shopify webhook handlers for billing events.

SECURITY: All webhooks MUST verify HMAC signature before processing.
Shopify signs webhooks with the app's API secret.

Documentation: https://shopify.dev/docs/apps/webhooks/configuration/https
"""

import os
import hmac
import hashlib
import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status, Header
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks/shopify", tags=["webhooks"])

# Webhook topics we handle
WEBHOOK_TOPIC_SUBSCRIPTION_UPDATE = "app_subscriptions/update"
WEBHOOK_TOPIC_APP_UNINSTALLED = "app/uninstalled"


class WebhookResponse(BaseModel):
    """Standard webhook response."""
    received: bool = True
    message: str = "Webhook processed"


def verify_shopify_webhook(
    data: bytes,
    hmac_header: str,
    api_secret: str
) -> bool:
    """
    Verify Shopify webhook HMAC signature.

    Shopify signs webhooks using HMAC-SHA256 with the app's API secret.

    Args:
        data: Raw request body bytes
        hmac_header: X-Shopify-Hmac-Sha256 header value
        api_secret: Shopify app API secret

    Returns:
        True if signature is valid, False otherwise
    """
    if not hmac_header or not api_secret:
        return False

    try:
        # Compute HMAC
        computed_hmac = hmac.new(
            api_secret.encode("utf-8"),
            data,
            hashlib.sha256
        )
        computed_digest = base64.b64encode(computed_hmac.digest()).decode("utf-8")

        # Constant-time comparison to prevent timing attacks
        return hmac.compare_digest(computed_digest, hmac_header)
    except Exception as e:
        logger.error("HMAC verification error", extra={"error": str(e)})
        return False


async def get_verified_webhook_body(request: Request) -> tuple[dict, str]:
    """
    Get and verify webhook body with HMAC signature.

    Args:
        request: FastAPI request

    Returns:
        Tuple of (parsed body dict, shop domain)

    Raises:
        HTTPException: If verification fails
    """
    # Get HMAC header
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    if not hmac_header:
        logger.warning("Missing HMAC header in webhook")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing HMAC signature"
        )

    # Get shop domain header
    shop_domain = request.headers.get("X-Shopify-Shop-Domain")
    if not shop_domain:
        logger.warning("Missing shop domain header in webhook")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing shop domain"
        )

    # Get API secret
    api_secret = os.getenv("SHOPIFY_API_SECRET")
    if not api_secret:
        logger.error("SHOPIFY_API_SECRET not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook verification not configured"
        )

    # Read raw body for HMAC verification
    body = await request.body()

    # Verify HMAC
    if not verify_shopify_webhook(body, hmac_header, api_secret):
        logger.warning("Invalid webhook HMAC", extra={
            "shop_domain": shop_domain
        })
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid HMAC signature"
        )

    # Parse JSON body
    import json
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook body")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON body"
        )

    return data, shop_domain


async def get_db_session():
    """Get database session for webhook processing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured"
        )

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@router.post("/subscription-update", response_model=WebhookResponse)
async def handle_subscription_update(
    request: Request,
    x_shopify_topic: Optional[str] = Header(None, alias="X-Shopify-Topic"),
    x_shopify_api_version: Optional[str] = Header(None, alias="X-Shopify-API-Version")
):
    """
    Handle app_subscriptions/update webhook from Shopify.

    This webhook is sent when:
    - Subscription is activated (merchant approves charge)
    - Subscription is cancelled
    - Payment fails and subscription is frozen
    - Subscription is renewed

    SECURITY: Verifies HMAC signature before processing.
    """
    data, shop_domain = await get_verified_webhook_body(request)

    logger.info("Subscription update webhook received", extra={
        "shop_domain": shop_domain,
        "topic": x_shopify_topic,
        "api_version": x_shopify_api_version
    })

    # Extract subscription data
    subscription_gid = data.get("app_subscription", {}).get("admin_graphql_api_id")
    subscription_status = data.get("app_subscription", {}).get("status")
    subscription_name = data.get("app_subscription", {}).get("name")

    if not subscription_gid:
        logger.warning("Webhook missing subscription ID", extra={
            "shop_domain": shop_domain,
            "data_keys": list(data.keys())
        })
        return WebhookResponse(message="Missing subscription ID")

    logger.info("Processing subscription update", extra={
        "shop_domain": shop_domain,
        "subscription_gid": subscription_gid,
        "status": subscription_status
    })

    # Get database session
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("Database not configured for webhook processing")
        return WebhookResponse(message="Database not configured")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    try:
        # Find store by shop domain
        from src.models.store import ShopifyStore
        store = session.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == shop_domain
        ).first()

        if not store:
            logger.warning("Store not found for webhook", extra={
                "shop_domain": shop_domain
            })
            return WebhookResponse(message="Store not found")

        # Process based on status
        from src.services.billing_service import BillingService

        billing_service = BillingService(session, store.tenant_id)

        if subscription_status == "ACTIVE":
            # Subscription activated
            current_period_end = None
            if data.get("app_subscription", {}).get("current_period_end"):
                current_period_end = datetime.fromisoformat(
                    data["app_subscription"]["current_period_end"].replace("Z", "+00:00")
                )

            billing_service.activate_subscription(
                shopify_subscription_id=subscription_gid,
                current_period_end=current_period_end
            )
            logger.info("Subscription activated via webhook", extra={
                "shop_domain": shop_domain,
                "subscription_gid": subscription_gid
            })

        elif subscription_status == "CANCELLED":
            # Subscription cancelled
            billing_service.cancel_subscription(
                shopify_subscription_id=subscription_gid,
                cancelled_at=datetime.now(timezone.utc)
            )
            logger.info("Subscription cancelled via webhook", extra={
                "shop_domain": shop_domain,
                "subscription_gid": subscription_gid
            })

        elif subscription_status == "FROZEN":
            # Payment failed
            billing_service.freeze_subscription(
                shopify_subscription_id=subscription_gid,
                reason="payment_failed"
            )
            logger.warning("Subscription frozen via webhook", extra={
                "shop_domain": shop_domain,
                "subscription_gid": subscription_gid
            })

        elif subscription_status == "DECLINED":
            # Merchant declined charge
            billing_service.cancel_subscription(
                shopify_subscription_id=subscription_gid
            )
            logger.info("Subscription declined via webhook", extra={
                "shop_domain": shop_domain,
                "subscription_gid": subscription_gid
            })

        else:
            logger.info("Unhandled subscription status", extra={
                "shop_domain": shop_domain,
                "status": subscription_status
            })

        return WebhookResponse(message=f"Processed status: {subscription_status}")

    except Exception as e:
        logger.error("Error processing subscription webhook", extra={
            "shop_domain": shop_domain,
            "error": str(e)
        })
        session.rollback()
        # Return 200 to acknowledge receipt (Shopify will retry on 4xx/5xx)
        return WebhookResponse(message=f"Error: {str(e)}")
    finally:
        session.close()


@router.post("/app-uninstalled", response_model=WebhookResponse)
async def handle_app_uninstalled(
    request: Request,
    x_shopify_topic: Optional[str] = Header(None, alias="X-Shopify-Topic")
):
    """
    Handle app/uninstalled webhook from Shopify.

    This webhook is sent when the merchant uninstalls the app.
    We should:
    - Cancel any active subscriptions
    - Mark the store as uninstalled
    - Retain data for potential reinstallation (per GDPR)

    SECURITY: Verifies HMAC signature before processing.
    """
    data, shop_domain = await get_verified_webhook_body(request)

    logger.info("App uninstalled webhook received", extra={
        "shop_domain": shop_domain,
        "topic": x_shopify_topic
    })

    # Get database session
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("Database not configured for webhook processing")
        return WebhookResponse(message="Database not configured")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(database_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = SessionLocal()

    try:
        from src.models.store import ShopifyStore
        from src.models.subscription import Subscription, SubscriptionStatus

        # Find and update store
        store = session.query(ShopifyStore).filter(
            ShopifyStore.shop_domain == shop_domain
        ).first()

        if store:
            store.status = "uninstalled"
            store.uninstalled_at = datetime.now(timezone.utc)
            # Clear access token for security
            store.access_token_encrypted = None

            # Cancel any active subscriptions
            subscriptions = session.query(Subscription).filter(
                Subscription.store_id == store.id,
                Subscription.status.in_([
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.PENDING.value,
                    SubscriptionStatus.FROZEN.value
                ])
            ).all()

            for sub in subscriptions:
                sub.status = SubscriptionStatus.CANCELLED.value
                sub.cancelled_at = datetime.now(timezone.utc)

            session.commit()

            logger.info("Store marked as uninstalled", extra={
                "shop_domain": shop_domain,
                "store_id": store.id,
                "subscriptions_cancelled": len(subscriptions)
            })
        else:
            logger.warning("Store not found for uninstall webhook", extra={
                "shop_domain": shop_domain
            })

        return WebhookResponse(message="App uninstalled processed")

    except Exception as e:
        logger.error("Error processing uninstall webhook", extra={
            "shop_domain": shop_domain,
            "error": str(e)
        })
        session.rollback()
        return WebhookResponse(message=f"Error: {str(e)}")
    finally:
        session.close()


@router.post("/customers-redact", response_model=WebhookResponse)
async def handle_customers_redact(request: Request):
    """
    Handle customers/redact webhook (GDPR compliance).

    Shopify requires apps to handle this mandatory webhook.
    We should delete/anonymize customer-specific data.
    """
    data, shop_domain = await get_verified_webhook_body(request)

    logger.info("Customers redact webhook received", extra={
        "shop_domain": shop_domain
    })

    # TODO: Implement customer data deletion/anonymization
    # For billing, we typically don't store customer PII beyond what's in Shopify

    return WebhookResponse(message="Customer redact acknowledged")


@router.post("/shop-redact", response_model=WebhookResponse)
async def handle_shop_redact(request: Request):
    """
    Handle shop/redact webhook (GDPR compliance).

    Shopify requires apps to handle this mandatory webhook.
    We should delete all data associated with the shop.
    """
    data, shop_domain = await get_verified_webhook_body(request)

    logger.info("Shop redact webhook received", extra={
        "shop_domain": shop_domain
    })

    # TODO: Implement shop data deletion
    # This is triggered 48 hours after app uninstall

    return WebhookResponse(message="Shop redact acknowledged")


@router.post("/customers-data-request", response_model=WebhookResponse)
async def handle_customers_data_request(request: Request):
    """
    Handle customers/data_request webhook (GDPR compliance).

    Shopify requires apps to handle this mandatory webhook.
    We should provide all customer data we have stored.
    """
    data, shop_domain = await get_verified_webhook_body(request)

    logger.info("Customers data request webhook received", extra={
        "shop_domain": shop_domain
    })

    # TODO: Implement customer data export
    # Send data to the specified data_request.url

    return WebhookResponse(message="Data request acknowledged")
