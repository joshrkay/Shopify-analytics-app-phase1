"""
Merchant-facing data health state model.

Provides a simplified, merchant-safe abstraction over the internal
data availability (FRESH/STALE/UNAVAILABLE) and data quality
(PASS/WARN/FAIL) systems.

Merchant Health States:
    HEALTHY     — All features enabled
    DELAYED     — AI disabled, dashboards allowed
    UNAVAILABLE — Dashboards blocked, clear message shown

Mapping rules:
    availability=UNAVAILABLE OR quality=FAIL  → UNAVAILABLE
    availability=STALE       OR quality=WARN  → DELAYED
    availability=FRESH      AND quality=PASS  → HEALTHY

SECURITY: Never exposes internal system names, SLA thresholds,
or technical error codes to the merchant.

Story 4.3 - Merchant Data Health Trust Layer
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MerchantHealthState(str, Enum):
    """Merchant-facing data health states."""
    HEALTHY = "healthy"
    DELAYED = "delayed"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Merchant-safe messages (no internal jargon)
# ---------------------------------------------------------------------------

MERCHANT_MESSAGES = {
    MerchantHealthState.HEALTHY: "Your data is up to date.",
    MerchantHealthState.DELAYED: (
        "Some data is delayed. Reports may be incomplete."
    ),
    MerchantHealthState.UNAVAILABLE: (
        "Your data is temporarily unavailable."
    ),
}


def get_merchant_message(state: MerchantHealthState) -> str:
    """Return the merchant-safe message for a health state."""
    return MERCHANT_MESSAGES[state]


# ---------------------------------------------------------------------------
# Feature gating flags per state
# ---------------------------------------------------------------------------

FEATURE_FLAGS = {
    MerchantHealthState.HEALTHY: {
        "ai_insights_enabled": True,
        "dashboards_enabled": True,
        "exports_enabled": True,
    },
    MerchantHealthState.DELAYED: {
        "ai_insights_enabled": False,
        "dashboards_enabled": True,
        "exports_enabled": False,
    },
    MerchantHealthState.UNAVAILABLE: {
        "ai_insights_enabled": False,
        "dashboards_enabled": False,
        "exports_enabled": False,
    },
}


# ---------------------------------------------------------------------------
# API response schema
# ---------------------------------------------------------------------------

class MerchantDataHealthResponse(BaseModel):
    """
    API response for the merchant data health endpoint.

    Fields are intentionally minimal and merchant-safe.
    No internal state names, SLA details, or error codes.
    """
    health_state: str = Field(
        description="Merchant health state: healthy, delayed, or unavailable",
    )
    last_updated: str = Field(
        description="ISO 8601 timestamp of the evaluation",
    )
    user_safe_message: str = Field(
        description="Human-readable message for the merchant",
    )
    ai_insights_enabled: bool = Field(
        description="Whether AI insights are currently available",
    )
    dashboards_enabled: bool = Field(
        description="Whether dashboards are currently available",
    )
    exports_enabled: bool = Field(
        description="Whether data exports are currently available",
    )
