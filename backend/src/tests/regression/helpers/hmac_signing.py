"""
HMAC signing helper for Shopify webhook testing.

Uses the same algorithm as Shopify for signing webhooks,
allowing tests to create validly-signed webhook payloads.
"""

import hmac
import hashlib
import base64


def compute_shopify_hmac(payload: bytes, secret: str) -> str:
    """
    Compute Shopify webhook HMAC-SHA256 signature.

    This uses the exact same algorithm Shopify uses to sign webhooks,
    allowing tests to create validly-signed payloads.

    Args:
        payload: Raw webhook body bytes
        secret: Shopify API secret (or test secret)

    Returns:
        Base64-encoded HMAC-SHA256 signature
    """
    computed_hmac = hmac.new(
        secret.encode("utf-8"),
        payload,
        hashlib.sha256
    )
    return base64.b64encode(computed_hmac.digest()).decode("utf-8")


def create_invalid_signature() -> str:
    """
    Create an obviously invalid HMAC signature for testing rejection.

    Returns:
        A base64-encoded string that will fail HMAC verification
    """
    return base64.b64encode(b"invalid-signature-for-testing").decode("utf-8")
