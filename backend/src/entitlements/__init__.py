"""
Entitlements enforcement system for billing-based feature access control.

This module provides:
- EntitlementService: Central service for resolving and caching entitlements
- EntitlementLoader: Load entitlements from config/plans.json
- AccessRules: Define access rules by billing state
- EntitlementCache: Redis-backed cache with real-time invalidation
- EntitlementMiddleware: FastAPI middleware for API enforcement
- AuditLogger: Log all access denials for compliance
- ResolvedEntitlement: Typed snapshot of a tenant's entitlements
- TenantOverride: Per-tenant feature override with mandatory expiry

Resolution order: override → plan → deny
Grace period: 3 days (configurable via billing_rules.grace_period_days)
"""

from src.entitlements.models import (
    BillingState as BillingStateCanonical,
    AccessLevel as AccessLevelCanonical,
    FeatureGrant,
    FeatureSource,
    TenantOverride,
    ResolvedEntitlement,
    TenantEntitlementOverride,
    resolve_features,
)
from src.entitlements.service import (
    EntitlementService,
    EntitlementEvaluationError,
    get_entitlements,
    invalidate_entitlements,
)
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
    # New — Story 6.2
    "EntitlementService",
    "EntitlementEvaluationError",
    "ResolvedEntitlement",
    "FeatureGrant",
    "FeatureSource",
    "TenantOverride",
    "TenantEntitlementOverride",
    "resolve_features",
    "get_entitlements",
    "invalidate_entitlements",
    "BillingStateCanonical",
    "AccessLevelCanonical",
    # Existing
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
