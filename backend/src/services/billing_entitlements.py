"""
Billing Entitlements Service - RBAC and Billing Tier Integration.

Synchronizes role-based access control with billing tier entitlements.
Agency access requires paid tiers (Growth or Enterprise).

CRITICAL SECURITY:
- Access is revoked IMMEDIATELY on billing downgrade
- Viewer roles are excluded from advanced dashboards
- All entitlement checks are server-side enforced
"""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.constants.permissions import (
    Role,
    Permission,
    BILLING_TIER_ALLOWED_ROLES,
    is_role_allowed_for_billing_tier,
    get_allowed_roles_for_billing_tier,
    has_multi_tenant_access,
)
from src.models.subscription import Subscription, SubscriptionStatus
from src.models.plan import Plan, PlanFeature

logger = logging.getLogger(__name__)


# Feature keys for billing entitlements
class BillingFeature:
    """Feature keys used in PlanFeature table."""
    AGENCY_ACCESS = "agency_access"
    MULTI_TENANT = "multi_tenant"
    ADVANCED_DASHBOARDS = "advanced_dashboards"
    EXPLORE_MODE = "explore_mode"
    DATA_EXPORT = "data_export"
    AI_INSIGHTS = "ai_insights"
    AI_RECOMMENDATIONS = "ai_recommendations"  # Story 8.3
    AI_ACTIONS = "ai_actions"
    CUSTOM_REPORTS = "custom_reports"
    LLM_ROUTING = "llm_routing"  # Story 8.8
    CUSTOM_PROMPTS = "custom_prompts"  # Story 8.8 - Enterprise only


# Billing tier feature matrix
BILLING_TIER_FEATURES = {
    'free': {
        BillingFeature.AGENCY_ACCESS: False,
        BillingFeature.MULTI_TENANT: False,
        BillingFeature.ADVANCED_DASHBOARDS: False,
        BillingFeature.EXPLORE_MODE: False,
        BillingFeature.DATA_EXPORT: False,
        BillingFeature.AI_INSIGHTS: True,  # Limited
        BillingFeature.AI_RECOMMENDATIONS: True,  # Limited (Story 8.3)
        BillingFeature.AI_ACTIONS: False,
        BillingFeature.CUSTOM_REPORTS: False,
        BillingFeature.LLM_ROUTING: False,  # Story 8.8
        BillingFeature.CUSTOM_PROMPTS: False,  # Story 8.8
        'max_dashboard_access': 3,
        'max_dashboard_shares': 0,
        'max_users': 2,
    },
    'growth': {
        BillingFeature.AGENCY_ACCESS: True,  # Limited (agency_viewer only)
        BillingFeature.MULTI_TENANT: True,   # Up to 5 stores
        BillingFeature.ADVANCED_DASHBOARDS: True,
        BillingFeature.EXPLORE_MODE: True,
        BillingFeature.DATA_EXPORT: False,
        BillingFeature.AI_INSIGHTS: True,
        BillingFeature.AI_RECOMMENDATIONS: True,  # Story 8.3
        BillingFeature.AI_ACTIONS: True,     # Limited
        BillingFeature.CUSTOM_REPORTS: True,
        BillingFeature.LLM_ROUTING: True,   # Story 8.8
        BillingFeature.CUSTOM_PROMPTS: False,  # Story 8.8 - Enterprise only
        'max_dashboard_access': 10,
        'max_dashboard_shares': 5,
        'max_users': 10,
        'max_agency_stores': 5,
    },
    'enterprise': {
        BillingFeature.AGENCY_ACCESS: True,   # Full (agency_admin + agency_viewer)
        BillingFeature.MULTI_TENANT: True,    # Unlimited stores
        BillingFeature.ADVANCED_DASHBOARDS: True,
        BillingFeature.EXPLORE_MODE: True,
        BillingFeature.DATA_EXPORT: True,
        BillingFeature.AI_INSIGHTS: True,
        BillingFeature.AI_RECOMMENDATIONS: True,  # Story 8.3
        BillingFeature.AI_ACTIONS: True,
        BillingFeature.CUSTOM_REPORTS: True,
        BillingFeature.LLM_ROUTING: True,    # Story 8.8
        BillingFeature.CUSTOM_PROMPTS: True,  # Story 8.8 - Custom prompt templates
        'max_dashboard_access': 999,
        'max_dashboard_shares': 999,
        'max_users': 999,
        'max_agency_stores': 999,
    },
}


@dataclass
class EntitlementCheckResult:
    """Result of an entitlement check."""
    is_entitled: bool
    reason: Optional[str] = None
    required_tier: Optional[str] = None
    current_tier: Optional[str] = None


@dataclass
class RoleValidationResult:
    """Result of role validation against billing tier."""
    is_valid: bool
    allowed_roles: List[str]
    revoked_roles: List[str]
    reason: Optional[str] = None


class BillingEntitlementsService:
    """
    Service for checking and enforcing billing-based entitlements.

    Integrates RBAC with billing tiers to ensure:
    - Agency access requires paid tier
    - Features are restricted based on plan
    - Access is revoked on downgrade
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize entitlements service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self._subscription: Optional[Subscription] = None
        self._plan: Optional[Plan] = None

    def _get_active_subscription(self) -> Optional[Subscription]:
        """Get cached active subscription for tenant."""
        if self._subscription is None:
            self._subscription = self.db.query(Subscription).filter(
                Subscription.tenant_id == self.tenant_id,
                Subscription.status == SubscriptionStatus.ACTIVE.value
            ).first()
        return self._subscription

    def _get_plan(self) -> Optional[Plan]:
        """Get cached plan for active subscription."""
        if self._plan is None:
            subscription = self._get_active_subscription()
            if subscription:
                self._plan = self.db.query(Plan).filter(
                    Plan.id == subscription.plan_id
                ).first()
        return self._plan

    def get_billing_tier(self) -> str:
        """
        Get the billing tier for the tenant.

        Returns:
            Billing tier name ('free', 'growth', 'enterprise')
        """
        plan = self._get_plan()
        if not plan:
            return 'free'

        # Map plan name to billing tier
        plan_name = plan.name.lower()
        if plan_name in ['enterprise', 'pro', 'business']:
            return 'enterprise'
        elif plan_name in ['growth', 'starter', 'professional']:
            return 'growth'
        return 'free'

    def check_feature_entitlement(self, feature: str) -> EntitlementCheckResult:
        """
        Check if tenant is entitled to a specific feature.

        Args:
            feature: Feature key from BillingFeature

        Returns:
            EntitlementCheckResult with entitlement status
        """
        billing_tier = self.get_billing_tier()
        tier_features = BILLING_TIER_FEATURES.get(billing_tier, {})

        is_entitled = tier_features.get(feature, False)

        if not is_entitled:
            # Determine required tier for feature
            required_tier = None
            for tier, features in BILLING_TIER_FEATURES.items():
                if features.get(feature, False):
                    required_tier = tier
                    break

            return EntitlementCheckResult(
                is_entitled=False,
                reason=f"Feature '{feature}' requires {required_tier or 'higher'} tier",
                required_tier=required_tier,
                current_tier=billing_tier,
            )

        return EntitlementCheckResult(is_entitled=True, current_tier=billing_tier)

    def check_agency_access_entitlement(self) -> EntitlementCheckResult:
        """
        Check if tenant is entitled to agency (multi-tenant) access.

        Agency access requires Growth or Enterprise tier.
        """
        return self.check_feature_entitlement(BillingFeature.AGENCY_ACCESS)

    def validate_role_for_billing(self, role: str) -> RoleValidationResult:
        """
        Validate if a role is allowed for the tenant's billing tier.

        Args:
            role: Role name to validate

        Returns:
            RoleValidationResult with validation status
        """
        billing_tier = self.get_billing_tier()
        allowed_roles = get_allowed_roles_for_billing_tier(billing_tier)

        is_valid = is_role_allowed_for_billing_tier(role, billing_tier)

        if not is_valid:
            return RoleValidationResult(
                is_valid=False,
                allowed_roles=allowed_roles,
                revoked_roles=[role],
                reason=f"Role '{role}' not allowed for billing tier '{billing_tier}'",
            )

        return RoleValidationResult(
            is_valid=True,
            allowed_roles=allowed_roles,
            revoked_roles=[],
        )

    def validate_roles_for_billing(self, roles: List[str]) -> RoleValidationResult:
        """
        Validate multiple roles against billing tier.

        Args:
            roles: List of role names to validate

        Returns:
            RoleValidationResult with validation status for all roles
        """
        billing_tier = self.get_billing_tier()
        allowed_roles = get_allowed_roles_for_billing_tier(billing_tier)

        valid_roles = []
        revoked_roles = []

        for role in roles:
            if is_role_allowed_for_billing_tier(role, billing_tier):
                valid_roles.append(role)
            else:
                revoked_roles.append(role)

        is_valid = len(revoked_roles) == 0

        return RoleValidationResult(
            is_valid=is_valid,
            allowed_roles=valid_roles,
            revoked_roles=revoked_roles,
            reason=f"Roles {revoked_roles} not allowed for tier '{billing_tier}'" if revoked_roles else None,
        )

    def get_max_dashboard_shares(self) -> int:
        """Get the maximum number of dashboard shares allowed per dashboard."""
        billing_tier = self.get_billing_tier()
        tier_features = BILLING_TIER_FEATURES.get(billing_tier, {})
        return tier_features.get('max_dashboard_shares', 0)

    def get_max_agency_stores(self) -> int:
        """
        Get the maximum number of agency stores allowed.

        Returns:
            Maximum number of stores for multi-tenant access
        """
        billing_tier = self.get_billing_tier()
        tier_features = BILLING_TIER_FEATURES.get(billing_tier, {})
        return tier_features.get('max_agency_stores', 0)

    def can_add_agency_store(self, current_store_count: int) -> bool:
        """
        Check if an additional agency store can be added.

        Args:
            current_store_count: Current number of assigned stores

        Returns:
            True if store can be added
        """
        max_stores = self.get_max_agency_stores()
        return current_store_count < max_stores

    def get_feature_limit(self, limit_key: str) -> int:
        """
        Get a numeric limit from plan features.

        Looks up the limit in the PlanFeature.limits JSON column.

        Args:
            limit_key: The limit key to look up (e.g., 'ai_insights_per_month')

        Returns:
            The limit value, or -1 for unlimited, or 0 if not entitled
        """
        plan = self._get_plan()
        if not plan:
            return 0  # Free tier default - no access

        # Check PlanFeature for the ai_insights feature
        feature = self.db.query(PlanFeature).filter(
            PlanFeature.plan_id == plan.id,
            PlanFeature.feature_key == BillingFeature.AI_INSIGHTS,
        ).first()

        if not feature or not feature.is_enabled:
            return 0  # Feature not enabled

        # Check limits JSON column
        if feature.limits and limit_key in feature.limits:
            return feature.limits.get(limit_key, -1)

        # Check limit_value as fallback
        if feature.limit_value is not None:
            return feature.limit_value

        return -1  # Unlimited if not specified


class BillingRoleSync:
    """
    Handles billing tier changes and role synchronization.

    CRITICAL: Access is revoked IMMEDIATELY on downgrade.
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def on_billing_downgrade(
        self,
        tenant_id: str,
        user_id: str,
        old_tier: str,
        new_tier: str,
        current_roles: List[str]
    ) -> Dict[str, Any]:
        """
        Handle billing downgrade - revoke roles not allowed in new tier.

        SECURITY: This MUST be called IMMEDIATELY when billing status changes.
        Access revocation cannot be delayed.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            old_tier: Previous billing tier
            new_tier: New billing tier
            current_roles: User's current roles

        Returns:
            Dict with revoked roles and new allowed roles
        """
        old_allowed = set(get_allowed_roles_for_billing_tier(old_tier))
        new_allowed = set(get_allowed_roles_for_billing_tier(new_tier))

        # Roles that must be revoked
        revoked_roles = old_allowed - new_allowed

        # Filter current roles to only allowed ones
        remaining_roles = [r for r in current_roles if r in new_allowed]

        if revoked_roles:
            logger.warning(
                "Revoking roles due to billing downgrade",
                extra={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "old_tier": old_tier,
                    "new_tier": new_tier,
                    "revoked_roles": list(revoked_roles),
                }
            )

            # SECURITY: Role revocation is enforced at multiple layers:
            # 1. Entitlement checks block access immediately (this service)
            # 2. JWT validation rejects disallowed roles (TenantContextMiddleware)
            # 3. Clerk webhook integration syncs role changes async
            #
            # For immediate revocation in Clerk, configure a webhook handler
            # that listens to billing.downgrade events and updates user metadata.
            # See docs/RBAC_CONFIGURATION.md

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "old_tier": old_tier,
            "new_tier": new_tier,
            "revoked_roles": list(revoked_roles),
            "remaining_roles": remaining_roles,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def on_billing_upgrade(
        self,
        tenant_id: str,
        user_id: str,
        old_tier: str,
        new_tier: str
    ) -> Dict[str, Any]:
        """
        Handle billing upgrade - make new roles available.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            old_tier: Previous billing tier
            new_tier: New billing tier

        Returns:
            Dict with newly available roles
        """
        old_allowed = set(get_allowed_roles_for_billing_tier(old_tier))
        new_allowed = set(get_allowed_roles_for_billing_tier(new_tier))

        # Roles that are now available
        new_roles = new_allowed - old_allowed

        if new_roles:
            logger.info(
                "New roles available after billing upgrade",
                extra={
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "old_tier": old_tier,
                    "new_tier": new_tier,
                    "new_roles": list(new_roles),
                }
            )

        return {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "old_tier": old_tier,
            "new_tier": new_tier,
            "new_roles_available": list(new_roles),
            "all_allowed_roles": list(new_allowed),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def on_subscription_cancelled(
        self,
        tenant_id: str,
        user_id: str,
        cancelled_tier: str,
        current_roles: List[str]
    ) -> Dict[str, Any]:
        """
        Handle subscription cancellation - downgrade to free tier.

        Args:
            tenant_id: Tenant ID
            user_id: User ID
            cancelled_tier: Tier that was cancelled
            current_roles: User's current roles

        Returns:
            Dict with role changes
        """
        return self.on_billing_downgrade(
            tenant_id=tenant_id,
            user_id=user_id,
            old_tier=cancelled_tier,
            new_tier='free',
            current_roles=current_roles,
        )


def check_billing_entitlement_decorator(feature: str):
    """
    Decorator to check billing entitlement before endpoint execution.

    Usage:
        @app.get("/api/agency/stores")
        @check_billing_entitlement_decorator(BillingFeature.AGENCY_ACCESS)
        async def list_agency_stores(request: Request):
            ...
    """
    from functools import wraps
    from fastapi import HTTPException, status, Request
    from src.platform.tenant_context import get_tenant_context

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Find request in args
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
            if not request:
                request = kwargs.get("request")

            if not request:
                raise ValueError("Request object not found")

            tenant_context = get_tenant_context(request)

            # Get DB session from request state or app state
            db_session = getattr(request.state, 'db', None)
            if not db_session:
                logger.error(
                    "DB session not available for entitlement check. Denying access.",
                    extra={"feature": feature, "tenant_id": tenant_context.tenant_id}
                )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Could not verify feature entitlement."
                )

            service = BillingEntitlementsService(db_session, tenant_context.tenant_id)
            result = service.check_feature_entitlement(feature)

            if not result.is_entitled:
                logger.warning(
                    "Entitlement check failed",
                    extra={
                        "tenant_id": tenant_context.tenant_id,
                        "feature": feature,
                        "reason": result.reason,
                    }
                )
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=f"This feature requires a {result.required_tier} plan"
                )

            return await func(*args, **kwargs)

        return wrapper
    return decorator
