"""
Debug endpoints for environment and deployment status.
These endpoints bypass authentication for troubleshooting.

SECURITY: Disabled in production (ENV=production) to prevent information leakage.
"""

import os
import base64
import json
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()
logger = logging.getLogger(__name__)


def _production_guard():
    """Return a 404 response if running in production, else None."""
    if os.getenv("ENV") == "production":
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return None


@router.get("/debug/env-status")
def env_status():
    """
    Check which environment variables are configured.
    Returns status without exposing sensitive values.
    """
    blocked = _production_guard()
    if blocked:
        return blocked
    # Environment variables to check
    env_vars = [
        "ENV",
        "DATABASE_URL",
        "REDIS_URL",
        "CLERK_FRONTEND_API",
        "CLERK_SECRET_KEY",
        "SHOPIFY_API_KEY",
        "SHOPIFY_API_SECRET",
        "OPENROUTER_API_KEY",
        "ENCRYPTION_KEY",
        "CORS_ORIGINS",
    ]

    status = {}
    for var in env_vars:
        value = os.getenv(var)
        if value:
            # Show first 4 chars to confirm it's set, but don't expose full value
            status[var] = {
                "configured": True,
                "prefix": value[:4] + "..." if len(value) > 4 else "***"
            }
        else:
            status[var] = {
                "configured": False,
                "prefix": None
            }

    # Summary counts
    configured_count = sum(1 for v in status.values() if v["configured"])
    total_count = len(status)

    return {
        "environment": os.getenv("ENV", "unknown"),
        "configured": f"{configured_count}/{total_count}",
        "variables": status,
        "deployment_info": {
            "python_version": os.sys.version,
            "port": os.getenv("PORT", "8000"),
        }
    }


@router.get("/debug/auth-check")
async def auth_check(request: Request):
    """
    Diagnose JWT/JWKS authentication issues.

    Tests:
    1. CLERK_FRONTEND_API is configured
    2. JWKS endpoint is reachable from the backend
    3. JWKS contains valid signing keys
    4. If Authorization header is provided, decodes (without verifying)
       the JWT payload to show issuer/expiry/org_id for comparison
    """
    blocked = _production_guard()
    if blocked:
        return blocked

    results: dict = {"checks": {}, "token_info": None}

    # 1. Check CLERK_FRONTEND_API
    clerk_api = os.getenv("CLERK_FRONTEND_API", "")
    if not clerk_api:
        results["checks"]["clerk_frontend_api"] = {
            "status": "FAIL",
            "detail": "CLERK_FRONTEND_API not set",
        }
        return results

    if not clerk_api.startswith("http"):
        clerk_api = f"https://{clerk_api}"
    clerk_api = clerk_api.rstrip("/")

    results["checks"]["clerk_frontend_api"] = {
        "status": "OK",
        "value": clerk_api,
    }

    # 2. Fetch JWKS endpoint
    jwks_url = f"{clerk_api}/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(jwks_url)
        results["checks"]["jwks_fetch"] = {
            "status": "OK" if resp.status_code == 200 else "FAIL",
            "url": jwks_url,
            "http_status": resp.status_code,
        }
        if resp.status_code == 200:
            jwks_data = resp.json()
            key_count = len(jwks_data.get("keys", []))
            key_ids = [k.get("kid", "?") for k in jwks_data.get("keys", [])]
            results["checks"]["jwks_keys"] = {
                "status": "OK" if key_count > 0 else "FAIL",
                "key_count": key_count,
                "key_ids": key_ids,
            }
        else:
            results["checks"]["jwks_keys"] = {
                "status": "FAIL",
                "detail": f"Could not parse JWKS (HTTP {resp.status_code})",
            }
    except Exception as e:
        results["checks"]["jwks_fetch"] = {
            "status": "FAIL",
            "url": jwks_url,
            "error": f"{type(e).__name__}: {str(e)}",
        }

    # 3. If an Authorization header is present, decode the JWT payload
    #    (without signature verification) to show issuer/expiry for comparison
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            # Decode JWT payload without verification (just base64)
            parts = token.split(".")
            if len(parts) == 3:
                # Add padding for base64
                payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)
                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                results["token_info"] = {
                    "iss": payload.get("iss"),
                    "sub": payload.get("sub"),
                    "exp": payload.get("exp"),
                    "org_id": payload.get("org_id"),
                    "azp": payload.get("azp"),
                    "issuer_matches_config": payload.get("iss") == clerk_api,
                }

                # Check token kid against JWKS keys
                header_b64 = parts[0] + "=" * (4 - len(parts[0]) % 4)
                header = json.loads(base64.urlsafe_b64decode(header_b64))
                token_kid = header.get("kid")
                results["token_info"]["token_kid"] = token_kid
                if "jwks_keys" in results["checks"] and results["checks"]["jwks_keys"].get("key_ids"):
                    results["token_info"]["kid_in_jwks"] = token_kid in results["checks"]["jwks_keys"]["key_ids"]
            else:
                results["token_info"] = {"error": "Token does not have 3 parts"}
        except Exception as e:
            results["token_info"] = {"error": f"Failed to decode: {type(e).__name__}: {str(e)}"}
    else:
        results["token_info"] = {"note": "No Authorization header — pass a Bearer token to check it"}

    # 4. Summary
    all_ok = all(
        c.get("status") == "OK"
        for c in results["checks"].values()
    )
    issuer_match = (results.get("token_info") or {}).get("issuer_matches_config")
    if issuer_match is False:
        all_ok = False

    results["summary"] = {
        "all_checks_pass": all_ok,
        "expected_issuer": clerk_api,
    }

    return results
