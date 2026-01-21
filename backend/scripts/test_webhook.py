#!/usr/bin/env python3
"""
Script to test Shopify webhooks locally.

Usage:
    # Start your server first
    uvicorn main:app --reload

    # Then run this script
    python scripts/test_webhook.py --event subscription_activated
    python scripts/test_webhook.py --event subscription_cancelled
    python scripts/test_webhook.py --event billing_failed
"""

import argparse
import hmac
import hashlib
import base64
import json
import os
import httpx

# Default webhook secret for testing
DEFAULT_SECRET = os.getenv("SHOPIFY_API_SECRET", "test_webhook_secret")
DEFAULT_BASE_URL = os.getenv("TEST_BASE_URL", "http://localhost:8000")


def generate_hmac(payload: bytes, secret: str) -> str:
    """Generate HMAC-SHA256 signature for webhook payload."""
    computed = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    ).digest()
    return base64.b64encode(computed).decode("utf-8")


def send_webhook(endpoint: str, payload: dict, topic: str, shop_domain: str = "test-store.myshopify.com"):
    """Send a test webhook to the local server."""
    url = f"{DEFAULT_BASE_URL}{endpoint}"
    payload_bytes = json.dumps(payload).encode("utf-8")
    signature = generate_hmac(payload_bytes, DEFAULT_SECRET)

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Topic": topic,
        "X-Shopify-Shop-Domain": shop_domain,
        "X-Shopify-Hmac-Sha256": signature,
    }

    print(f"\n{'='*60}")
    print(f"Sending webhook: {topic}")
    print(f"URL: {url}")
    print(f"Shop: {shop_domain}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    print(f"{'='*60}\n")

    try:
        response = httpx.post(url, content=payload_bytes, headers=headers)
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        return response
    except Exception as e:
        print(f"Error: {e}")
        return None


def test_subscription_activated():
    """Test subscription activation webhook."""
    payload = {
        "app_subscription": {
            "admin_graphql_api_id": "gid://shopify/AppSubscription/12345",
            "name": "Growth Plan",
            "status": "ACTIVE",
            "created_at": "2024-01-15T10:00:00Z",
            "current_period_end": "2024-02-15T10:00:00Z",
        }
    }
    return send_webhook(
        "/webhooks/shopify/app-subscriptions-update",
        payload,
        "app_subscriptions/update"
    )


def test_subscription_cancelled():
    """Test subscription cancellation webhook."""
    payload = {
        "app_subscription": {
            "admin_graphql_api_id": "gid://shopify/AppSubscription/12345",
            "name": "Growth Plan",
            "status": "CANCELLED",
            "cancelled_on": "2024-01-20T10:00:00Z",
        }
    }
    return send_webhook(
        "/webhooks/shopify/app-subscriptions-update",
        payload,
        "app_subscriptions/update"
    )


def test_billing_success():
    """Test billing success webhook."""
    payload = {
        "subscription_contract": {
            "admin_graphql_api_id": "gid://shopify/AppSubscription/12345",
        },
        "billing_attempt": {
            "id": "gid://shopify/BillingAttempt/67890",
            "ready": True,
        }
    }
    return send_webhook(
        "/webhooks/shopify/billing-attempt-success",
        payload,
        "subscription_billing_attempts/success"
    )


def test_billing_failed():
    """Test billing failure webhook."""
    payload = {
        "subscription_contract": {
            "admin_graphql_api_id": "gid://shopify/AppSubscription/12345",
        },
        "billing_attempt": {
            "id": "gid://shopify/BillingAttempt/67890",
            "ready": False,
            "error_message": "Payment method declined",
        }
    }
    return send_webhook(
        "/webhooks/shopify/billing-attempt-failure",
        payload,
        "subscription_billing_attempts/failure"
    )


def test_app_uninstalled():
    """Test app uninstalled webhook."""
    payload = {
        "id": 12345,
        "name": "Test Store",
        "email": "owner@test-store.com",
        "domain": "test-store.myshopify.com",
    }
    return send_webhook(
        "/webhooks/shopify/app-uninstalled",
        payload,
        "app/uninstalled"
    )


def test_invalid_signature():
    """Test that invalid signatures are rejected."""
    url = f"{DEFAULT_BASE_URL}/webhooks/shopify/app-subscriptions-update"
    payload = {"test": "data"}
    payload_bytes = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Topic": "app_subscriptions/update",
        "X-Shopify-Shop-Domain": "test-store.myshopify.com",
        "X-Shopify-Hmac-Sha256": "invalid_signature_here",
    }

    print(f"\n{'='*60}")
    print("Testing INVALID signature (should be rejected)")
    print(f"{'='*60}\n")

    try:
        response = httpx.post(url, content=payload_bytes, headers=headers)
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.text}")
        if response.status_code == 401:
            print("\n✓ Correctly rejected invalid signature!")
        else:
            print("\n✗ WARNING: Invalid signature was NOT rejected!")
        return response
    except Exception as e:
        print(f"Error: {e}")
        return None


EVENTS = {
    "subscription_activated": test_subscription_activated,
    "subscription_cancelled": test_subscription_cancelled,
    "billing_success": test_billing_success,
    "billing_failed": test_billing_failed,
    "app_uninstalled": test_app_uninstalled,
    "invalid_signature": test_invalid_signature,
    "all": None,  # Special case
}


def main():
    parser = argparse.ArgumentParser(description="Test Shopify webhooks locally")
    parser.add_argument(
        "--event",
        choices=list(EVENTS.keys()),
        default="all",
        help="Which event to test (default: all)"
    )
    parser.add_argument(
        "--secret",
        default=DEFAULT_SECRET,
        help="Webhook secret (default: SHOPIFY_API_SECRET env var or 'test_webhook_secret')"
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="Base URL of your server (default: http://localhost:8000)"
    )

    args = parser.parse_args()

    global DEFAULT_SECRET, DEFAULT_BASE_URL
    DEFAULT_SECRET = args.secret
    DEFAULT_BASE_URL = args.base_url

    if args.event == "all":
        print("\n" + "="*60)
        print("Running ALL webhook tests")
        print("="*60)
        for name, func in EVENTS.items():
            if func is not None:
                func()
    else:
        EVENTS[args.event]()


if __name__ == "__main__":
    main()
