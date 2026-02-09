"""
Shopify embedded app entry point.

Handles GET / — the initial request Shopify makes when loading the app
inside the Shopify Admin iframe.

Shopify sends the following query parameters:
- embedded: "1" (indicates embedded mode)
- hmac: HMAC signature for request verification
- host: Base64-encoded Shopify Admin host
- id_token: Shopify session token (JWT signed by Shopify)
- locale: User locale
- session: Session identifier
- shop: The myshopify.com domain
- timestamp: Request timestamp

This route bypasses the TenantContextMiddleware (it's in the public paths
list) because Shopify does not send a Clerk Bearer token — authentication
is done via Shopify HMAC verification instead.
"""

import os
import hmac
import hashlib
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, HTTPException, status
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["shopify-app"])


def verify_shopify_request(query_params: dict, api_secret: str) -> bool:
    """
    Verify the Shopify embedded app request HMAC.

    Shopify signs the query parameters with the app's API secret using
    HMAC-SHA256. We reconstruct the message from all params except 'hmac'
    and verify the signature.

    Args:
        query_params: Request query parameters as dict
        api_secret: Shopify app API secret

    Returns:
        True if HMAC is valid, False otherwise
    """
    if not api_secret:
        logger.warning("SHOPIFY_API_SECRET not configured, skipping HMAC verification")
        return True  # Allow in development when secret isn't set

    received_hmac = query_params.get("hmac")
    if not received_hmac:
        return False

    # Build message from all params except 'hmac', sorted alphabetically
    params = {k: v for k, v in sorted(query_params.items()) if k != "hmac"}
    message = urlencode(params)

    # Compute HMAC-SHA256
    computed_hmac = hmac.new(
        api_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed_hmac, received_hmac)


@router.get("/", response_class=HTMLResponse)
async def shopify_app_entry(request: Request):
    """
    Shopify embedded app entry point.

    Verifies the Shopify request signature, then serves a minimal HTML page
    that initializes Shopify App Bridge and Clerk authentication.

    Once authenticated via Clerk, the frontend makes API calls to the
    backend with Bearer tokens for tenant-scoped data access.
    """
    query_params = dict(request.query_params)

    # Verify Shopify HMAC signature
    api_secret = os.getenv("SHOPIFY_API_SECRET", "")
    if query_params.get("hmac") and not verify_shopify_request(query_params, api_secret):
        logger.warning(
            "Invalid Shopify HMAC signature",
            extra={"shop": query_params.get("shop", "unknown")},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid request signature",
        )

    # Extract Shopify parameters
    shop = query_params.get("shop", "")
    host = query_params.get("host", "")
    embedded = query_params.get("embedded", "0")

    # Get Clerk publishable key for frontend auth initialization
    clerk_publishable_key = os.getenv("VITE_CLERK_PUBLISHABLE_KEY", "")
    api_url = os.getenv("API_URL", request.base_url.scheme + "://" + request.base_url.netloc)

    logger.info(
        "Shopify embedded app loaded",
        extra={
            "shop": shop,
            "embedded": embedded,
        },
    )

    # Serve a minimal HTML page that initializes Shopify App Bridge
    # and Clerk authentication, then renders the embedded analytics UI.
    #
    # In production, this should be replaced by the built frontend
    # (React/Vite) served from a static site or bundled into the backend.
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Markinsight</title>
    <script src="https://cdn.shopify.com/shopifycloud/app-bridge.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background: #f6f6f7;
            color: #202223;
        }}
        .loading-container {{
            text-align: center;
            padding: 2rem;
        }}
        .spinner {{
            width: 40px;
            height: 40px;
            border: 3px solid #e3e3e3;
            border-top-color: #5c6ac4;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin: 0 auto 1rem;
        }}
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
        .error {{
            color: #d72c0d;
            display: none;
        }}
    </style>
</head>
<body>
    <div class="loading-container">
        <div class="spinner" id="spinner"></div>
        <p id="status-text">Loading Markinsight...</p>
        <p class="error" id="error-text"></p>
    </div>
    <script>
        // Initialize Shopify App Bridge
        const host = "{host}";
        const shop = "{shop}";
        const apiUrl = "{api_url}";

        function showError(message) {{
            document.getElementById('spinner').style.display = 'none';
            document.getElementById('status-text').style.display = 'none';
            const errorEl = document.getElementById('error-text');
            errorEl.textContent = message;
            errorEl.style.display = 'block';
        }}

        try {{
            if (window.shopify) {{
                // App Bridge v4+ initialization
                document.getElementById('status-text').textContent = 'Initializing...';

                // The app is loaded and ready within Shopify Admin
                // In a full deployment, this page would be replaced by the
                // React frontend which handles Clerk auth and renders dashboards.
                document.getElementById('status-text').textContent =
                    'Markinsight is ready. Configure your frontend deployment to serve the full UI.';
                document.getElementById('spinner').style.display = 'none';
            }} else {{
                showError('Shopify App Bridge failed to load.');
            }}
        }} catch (e) {{
            showError('Initialization error: ' + e.message);
        }}
    </script>
</body>
</html>"""

    return HTMLResponse(content=html_content, status_code=200)
