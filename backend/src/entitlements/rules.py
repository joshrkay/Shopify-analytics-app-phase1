"""
Access Rules - Define access rules by billing state.

Provides:
- BillingState: Enum of all possible billing states
- AccessLevel: Enum of access levels
- AccessRules: Evaluate access based on billing state and features

CRITICAL: Access rules are config-driven from plans.json.
Do NOT hardcode access logic elsewhere.
"""

import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Set, Dict, Any

from src.entitlements.loader import (
    EntitlementLoader,
    PlanEntitlements,
    AccessRuleConfig,
    get_entitlement_loader,
)

logger = logging.getLogger(__name__)


class BillingState(str, Enum):
    """
    Billing states that affect feature access.

    Maps to subscription status with additional grace period handling.
    """

    ACTIVE = "active"
    PAST_DUE = "past_due"
    GRACE_PERIOD = "grace_period"
    CANCELED = "canceled"
    EXPIRED = "expired"
    FROZEN = "frozen"
    PENDING = "pending"
    TRIALING = "trialing"
    NONE = "none"  # No subscription

    @classmethod
    def from_subscription_status(
        cls,
        status: str,
        grace_period_ends_on: Optional[datetime] = None,
        current_period_end: Optional[datetime] = None,
    ) -> 'BillingState':
        """
        Map subscription status to billing state.

        Args:
            status: Subscription status string
            grace_period_ends_on: When grace period ends (for frozen status)
            current_period_end: When current period ends (for canceled status)

        Returns:
            Appropriate BillingState
        """
        status_lower = status.lower() if status else ""
        now = datetime.now(timezone.utc)

        # Handle frozen with grace period check
        if status_lower == "frozen":
            if grace_period_ends_on and now <= grace_period_ends_on:
                return cls.GRACE_PERIOD
            return cls.FROZEN

        # Handle canceled with period end check
        if status_lower in ("cancelled", "canceled"):
            if current_period_end and now <= current_period_end:
                return cls.CANCELED  # Still has access until period end
            return cls.EXPIRED

        # Direct mappings
        status_map = {
            "active": cls.ACTIVE,
            "pending": cls.PENDING,
            "trialing": cls.TRIALING,
            "trial_active": cls.TRIALING,
            "expired": cls.EXPIRED,
            "trial_expired": cls.EXPIRED,
            "declined": cls.EXPIRED,
            "past_due": cls.PAST_DUE,
        }

        return status_map.get(status_lower, cls.NONE)


class AccessLevel(str, Enum):
    """Access levels for billing states."""

    FULL = "full"
    READ_ONLY = "read_only"
    READ_ONLY_ANALYTICS = "read_only_analytics"
    LIMITED = "limited"
    FULL_UNTIL_PERIOD_END = "full_until_period_end"
    NONE = "none"

    def allows_writes(self) -> bool:
        """Check if this access level allows write operations."""
        return self in (AccessLevel.FULL, AccessLevel.FULL_UNTIL_PERIOD_END)

    def allows_reads(self) -> bool:
        """Check if this access level allows read operations."""
        return self != AccessLevel.NONE

    def allows_analytics(self) -> bool:
        """Check if this access level allows analytics access."""
        return self != AccessLevel.NONE


@dataclass
class AccessDecision:
    """Result of an access check."""

    allowed: bool
    billing_state: BillingState
    access_level: AccessLevel
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    feature_key: Optional[str] = None
    restrictions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    reason: Optional[str] = None
    required_plan: Optional[str] = None
    upgrade_url: Optional[str] = None
    expires_at: Optional[datetime] = None

    def to_error_response(self) -> Dict[str, Any]:
        """Convert to API error response format."""
        return {
            "error": "entitlement_required" if not self.allowed else None,
            "message": self.reason or "Access denied",
            "feature": self.feature_key,
            "billing_state": self.billing_state.value,
            "current_plan": self.plan_name,
            "required_plan": self.required_plan,
            "access_level": self.access_level.value,
            "warnings": self.warnings,
            "action": "upgrade" if self.required_plan else None,
            "upgrade_url": self.upgrade_url,
        }


@dataclass
class WarningInfo:
    """Warning information to display to user."""

    code: str
    message: str
    severity: str = "warning"  # "info", "warning", "error"
    action_url: Optional[str] = None


class AccessRules:
    """
    Evaluate access rules based on billing state and plan entitlements.

    Thread-safe and uses the singleton EntitlementLoader.

    Usage:
        rules = AccessRules(tenant_id, subscription)
        decision = rules.check_feature_access("ai_insights")
        if not decision.allowed:
            raise HTTPException(status_code=402, detail=decision.to_error_response())
    """

    # Feature restrictions by access level
    ACCESS_LEVEL_RESTRICTIONS: Dict[AccessLevel, Set[str]] = {
        AccessLevel.READ_ONLY: {
            "data_export",
            "data_export_csv",
            "data_export_api",
            "ai_actions",
            "api_access",
            "custom_reports",
            "scheduled_reports",
        },
        AccessLevel.READ_ONLY_ANALYTICS: {
            "data_export",
            "data_export_csv",
            "data_export_api",
            "ai_actions",
            "ai_insights",
            "api_access",
            "custom_reports",
            "scheduled_reports",
        },
        AccessLevel.LIMITED: {
            "data_export_api",
            "ai_actions",
        },
        AccessLevel.NONE: set(),  # Block everything
    }

    # Warning messages by code
    WARNING_MESSAGES: Dict[str, WarningInfo] = {
        "payment_past_due": WarningInfo(
            code="payment_past_due",
            message="Your payment is past due. Please update your payment method to maintain full access.",
            severity="warning",
            action_url="/billing/payment-method",
        ),
        "payment_grace_period": WarningInfo(
            code="payment_grace_period",
            message="Your payment failed. You have 3 days to resolve this before access is limited.",
            severity="warning",
            action_url="/billing/payment-method",
        ),
        "subscription_canceled": WarningInfo(
            code="subscription_canceled",
            message="Your subscription is canceled. You have access until the end of your billing period.",
            severity="info",
            action_url="/billing/reactivate",
        ),
        "subscription_expired": WarningInfo(
            code="subscription_expired",
            message="Your subscription has expired. Upgrade to restore full access.",
            severity="error",
            action_url="/billing/plans",
        ),
        "payment_failed_frozen": WarningInfo(
            code="payment_failed_frozen",
            message="Your account is frozen due to payment failure. Some features are restricted.",
            severity="error",
            action_url="/billing/payment-method",
        ),
    }

    def __init__(
        self,
        tenant_id: str,
        plan_id: Optional[str] = None,
        billing_state: Optional[BillingState] = None,
        grace_period_ends_on: Optional[datetime] = None,
        current_period_end: Optional[datetime] = None,
        feature_flags_override: Optional[Dict[str, bool]] = None,
    ):
        """
        Initialize access rules for a tenant.

        Args:
            tenant_id: Tenant identifier
            plan_id: Current plan ID (defaults to free plan)
            billing_state: Current billing state
            grace_period_ends_on: When grace period ends
            current_period_end: When current billing period ends
            feature_flags_override: Emergency feature flag overrides (admin-only)
        """
        self.tenant_id = tenant_id
        self.plan_id = plan_id or "plan_free"
        self._billing_state = billing_state or BillingState.ACTIVE
        self.grace_period_ends_on = grace_period_ends_on
        self.current_period_end = current_period_end
        self._feature_flags_override = feature_flags_override or {}

        self._loader = get_entitlement_loader()
        self._plan: Optional[PlanEntitlements] = None
        self._access_rule: Optional[AccessRuleConfig] = None

    @property
    def billing_state(self) -> BillingState:
        """Get current billing state."""
        return self._billing_state

    @property
    def plan(self) -> Optional[PlanEntitlements]:
        """Get plan entitlements (lazy loaded)."""
        if self._plan is None:
            self._plan = self._loader.get_plan(self.plan_id)
        return self._plan

    @property
    def access_rule(self) -> Optional[AccessRuleConfig]:
        """Get access rule config for current billing state (lazy loaded)."""
        if self._access_rule is None:
            self._access_rule = self._loader.get_access_rule(self._billing_state.value)
        return self._access_rule

    def get_access_level(self) -> AccessLevel:
        """Get the access level for current billing state."""
        if not self.access_rule:
            # Default to FULL for active, NONE for unknown
            if self._billing_state == BillingState.ACTIVE:
                return AccessLevel.FULL
            return AccessLevel.NONE

        level_str = self.access_rule.access_level
        try:
            return AccessLevel(level_str)
        except ValueError:
            logger.warning(f"Unknown access level: {level_str}")
            return AccessLevel.LIMITED

    def get_state_restrictions(self) -> Set[str]:
        """Get features restricted by current billing state."""
        if not self.access_rule:
            if self._billing_state == BillingState.ACTIVE:
                return set()
            return set()  # Unknown state - no extra restrictions

        return set(self.access_rule.restrictions)

    def get_warnings(self) -> List[WarningInfo]:
        """Get warning messages for current billing state."""
        if not self.access_rule:
            return []

        warnings = []
        for warning_code in self.access_rule.warnings:
            if warning_code in self.WARNING_MESSAGES:
                warnings.append(self.WARNING_MESSAGES[warning_code])
            else:
                warnings.append(WarningInfo(
                    code=warning_code,
                    message=f"Warning: {warning_code}",
                ))
        return warnings

    def check_feature_access(
        self,
        feature_key: str,
        operation: str = "read",
    ) -> AccessDecision:
        """
        Check if a specific feature is accessible.

        Args:
            feature_key: Feature to check (e.g., "ai_insights", "data_export")
            operation: Type of operation ("read" or "write")

        Returns:
            AccessDecision with full access information
        """
        plan = self.plan
        access_level = self.get_access_level()
        state_restrictions = self.get_state_restrictions()
        warnings = self.get_warnings()

        # Check for emergency feature flag override (admin-only)
        if feature_key in self._feature_flags_override:
            override_value = self._feature_flags_override[feature_key]
            return AccessDecision(
                allowed=override_value,
                billing_state=self._billing_state,
                access_level=access_level,
                plan_id=self.plan_id,
                plan_name=plan.display_name if plan else None,
                feature_key=feature_key,
                warnings=[w.code for w in warnings],
                reason="Feature flag override" if not override_value else None,
            )

        # Check if billing state blocks this feature
        if feature_key in state_restrictions:
            return AccessDecision(
                allowed=False,
                billing_state=self._billing_state,
                access_level=access_level,
                plan_id=self.plan_id,
                plan_name=plan.display_name if plan else None,
                feature_key=feature_key,
                restrictions=list(state_restrictions),
                warnings=[w.code for w in warnings],
                reason=f"Feature '{feature_key}' is restricted in billing state '{self._billing_state.value}'",
            )

        # Check access level restrictions
        if access_level in self.ACCESS_LEVEL_RESTRICTIONS:
            level_restrictions = self.ACCESS_LEVEL_RESTRICTIONS[access_level]
            if feature_key in level_restrictions:
                return AccessDecision(
                    allowed=False,
                    billing_state=self._billing_state,
                    access_level=access_level,
                    plan_id=self.plan_id,
                    plan_name=plan.display_name if plan else None,
                    feature_key=feature_key,
                    restrictions=list(level_restrictions),
                    warnings=[w.code for w in warnings],
                    reason=f"Feature '{feature_key}' requires higher access level than '{access_level.value}'",
                )

        # Check write operations
        if operation == "write" and not access_level.allows_writes():
            return AccessDecision(
                allowed=False,
                billing_state=self._billing_state,
                access_level=access_level,
                plan_id=self.plan_id,
                plan_name=plan.display_name if plan else None,
                feature_key=feature_key,
                warnings=[w.code for w in warnings],
                reason=f"Write operations not allowed in billing state '{self._billing_state.value}'",
            )

        # Check plan entitlements
        if plan and not plan.has_feature(feature_key):
            # Find which plan provides this feature
            required_plan = self._find_plan_with_feature(feature_key)
            return AccessDecision(
                allowed=False,
                billing_state=self._billing_state,
                access_level=access_level,
                plan_id=self.plan_id,
                plan_name=plan.display_name,
                feature_key=feature_key,
                warnings=[w.code for w in warnings],
                reason=f"Feature '{feature_key}' requires plan upgrade",
                required_plan=required_plan,
                upgrade_url=f"/billing/upgrade?to={required_plan}" if required_plan else None,
            )

        # Access granted
        return AccessDecision(
            allowed=True,
            billing_state=self._billing_state,
            access_level=access_level,
            plan_id=self.plan_id,
            plan_name=plan.display_name if plan else None,
            feature_key=feature_key,
            warnings=[w.code for w in warnings],
            expires_at=self.current_period_end if self._billing_state == BillingState.CANCELED else None,
        )

    def check_limit(
        self,
        limit_key: str,
        current_usage: int,
    ) -> AccessDecision:
        """
        Check if usage is within plan limits.

        Args:
            limit_key: Limit to check (e.g., "max_dashboards", "api_calls_per_month")
            current_usage: Current usage count

        Returns:
            AccessDecision indicating if limit is exceeded
        """
        plan = self.plan
        warnings = self.get_warnings()

        if not plan:
            return AccessDecision(
                allowed=True,  # No plan = no limits (default to free plan limits elsewhere)
                billing_state=self._billing_state,
                access_level=self.get_access_level(),
                warnings=[w.code for w in warnings],
            )

        limit_value = plan.limits.get_limit(limit_key)

        # -1 or None means unlimited
        if limit_value is None or limit_value == -1:
            return AccessDecision(
                allowed=True,
                billing_state=self._billing_state,
                access_level=self.get_access_level(),
                plan_id=self.plan_id,
                plan_name=plan.display_name,
                warnings=[w.code for w in warnings],
            )

        # Check if limit exceeded
        if current_usage >= limit_value:
            required_plan = self._find_plan_with_higher_limit(limit_key, current_usage)
            return AccessDecision(
                allowed=False,
                billing_state=self._billing_state,
                access_level=self.get_access_level(),
                plan_id=self.plan_id,
                plan_name=plan.display_name,
                warnings=[w.code for w in warnings],
                reason=f"Limit '{limit_key}' exceeded: {current_usage}/{limit_value}",
                required_plan=required_plan,
                upgrade_url=f"/billing/upgrade?to={required_plan}" if required_plan else None,
            )

        return AccessDecision(
            allowed=True,
            billing_state=self._billing_state,
            access_level=self.get_access_level(),
            plan_id=self.plan_id,
            plan_name=plan.display_name,
            warnings=[w.code for w in warnings],
        )

    def _find_plan_with_feature(self, feature_key: str) -> Optional[str]:
        """Find the lowest tier plan that has a feature."""
        for plan in self._loader.get_all_plans():
            if plan.has_feature(feature_key) and plan.tier > 0:
                return plan.display_name
        return None

    def _find_plan_with_higher_limit(
        self,
        limit_key: str,
        required_value: int,
    ) -> Optional[str]:
        """Find the lowest tier plan with a higher limit."""
        current_tier = self.plan.tier if self.plan else 0

        for plan in self._loader.get_all_plans():
            if plan.tier <= current_tier:
                continue

            limit = plan.limits.get_limit(limit_key)
            if limit is None or limit == -1 or limit > required_value:
                return plan.display_name

        return None

    def can_access_feature(self, feature_key: str, operation: str = "read") -> bool:
        """Convenience method to check if feature is accessible."""
        return self.check_feature_access(feature_key, operation).allowed

    def can_write(self) -> bool:
        """Check if write operations are allowed."""
        return self.get_access_level().allows_writes()

    def can_read(self) -> bool:
        """Check if read operations are allowed."""
        return self.get_access_level().allows_reads()

    def is_in_grace_period(self) -> bool:
        """Check if currently in grace period."""
        return self._billing_state == BillingState.GRACE_PERIOD

    def get_grace_period_days_remaining(self) -> Optional[int]:
        """Get days remaining in grace period."""
        if not self.is_in_grace_period() or not self.grace_period_ends_on:
            return None

        now = datetime.now(timezone.utc)
        delta = self.grace_period_ends_on - now
        return max(0, delta.days)


def create_access_rules_from_subscription(
    tenant_id: str,
    subscription: Any,  # Subscription model
    feature_flags_override: Optional[Dict[str, bool]] = None,
) -> AccessRules:
    """
    Factory function to create AccessRules from a Subscription model.

    Args:
        tenant_id: Tenant identifier
        subscription: Subscription model instance
        feature_flags_override: Emergency feature flag overrides

    Returns:
        AccessRules instance configured for the subscription
    """
    if not subscription:
        return AccessRules(
            tenant_id=tenant_id,
            plan_id="plan_free",
            billing_state=BillingState.NONE,
            feature_flags_override=feature_flags_override,
        )

    billing_state = BillingState.from_subscription_status(
        status=subscription.status,
        grace_period_ends_on=getattr(subscription, 'grace_period_ends_on', None),
        current_period_end=getattr(subscription, 'current_period_end', None),
    )

    return AccessRules(
        tenant_id=tenant_id,
        plan_id=subscription.plan_id,
        billing_state=billing_state,
        grace_period_ends_on=getattr(subscription, 'grace_period_ends_on', None),
        current_period_end=getattr(subscription, 'current_period_end', None),
        feature_flags_override=feature_flags_override,
    )
