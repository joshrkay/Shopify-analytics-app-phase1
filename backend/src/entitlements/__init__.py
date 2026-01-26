"""
Entitlements enforcement system for billing-based feature access control.

This module provides:
- EntitlementLoader: Load entitlements from config/plans.json
- AccessRules: Define access rules by billing state
- EntitlementCache: Redis-backed cache with real-time invalidation
- EntitlementMiddleware: FastAPI middleware for API enforcement
- AuditLogger: Log all access denials for compliance

Grace period: 3 days (configurable via billing_rules.grace_period_days)
"""

from src.entitlements.loader import EntitlementLoader, PlanEntitlements
from src.entitlements.rules import AccessRules, AccessLevel, BillingState
from src.entitlements.cache import EntitlementCache
from src.entitlements.middleware import (
    EntitlementMiddleware,
    require_entitlement,
    require_billing_state,
)
from src.entitlements.audit import EntitlementAuditLogger, AccessDenialEvent

__all__ = [
    "EntitlementLoader",
    "PlanEntitlements",
    "AccessRules",
    "AccessLevel",
    "BillingState",
    "EntitlementCache",
    "EntitlementMiddleware",
    "require_entitlement",
    "require_billing_state",
    "EntitlementAuditLogger",
    "AccessDenialEvent",
]
