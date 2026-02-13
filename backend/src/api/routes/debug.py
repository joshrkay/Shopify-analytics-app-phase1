"""
Debug endpoints for environment and deployment status.
These endpoints bypass authentication for troubleshooting.
"""

import os
from fastapi import APIRouter

router = APIRouter()


@router.get("/debug/env-status")
def env_status():
    """
    Check which environment variables are configured.
    Returns status without exposing sensitive values.
    """
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
