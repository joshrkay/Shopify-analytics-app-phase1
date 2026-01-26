"""
Entitlement policy evaluation.

Determines billing_state from subscription and evaluates feature access.
"""

import json
import os
import logging
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sqlalchemy.orm import Session

from src.models.subscription import Subscription, SubscriptionStatus
from src.models.plan import Plan, PlanFeature

logger = logging.getLogger(__name__)


class BillingState(str, Enum):
    """Billing state values."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    GRACE_PERIOD = "grace_period"
    CANCELED = "canceled"
    EXPIRED = "expired"
    NONE = "none"  # No subscription


@dataclass
class EntitlementCheckResult:
    """Result of an entitlement check."""
    is_entitled: bool
    billing_state: BillingState
    plan_id: Optional[str]
    feature: str
    reason: Optional[str] = None
    required_plan: Optional[str] = None
    grace_period_ends_on: Optional[datetime] = None


class EntitlementPolicy:
    """
    Evaluates feature entitlements based on billing state and plan features.
    
    Loads plan configuration from:
    1. PlanFeature table (primary source of truth)
    2. config/plans.json (optional policy overrides)
    """
    
    def __init__(self, db_session: Session):
        """
        Initialize entitlement policy.
        
        Args:
            db_session: Database session for querying PlanFeature
        """
        self.db = db_session
        self._config_cache: Optional[Dict[str, Any]] = None
        self._grace_period_days = 3  # Default grace period
    
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration from config/plans.json if it exists."""
        if self._config_cache is not None:
            return self._config_cache
        
        config_path = Path(__file__).parent.parent.parent.parent / "config" / "plans.json"
        
        if not config_path.exists():
            logger.debug("config/plans.json not found, using database PlanFeature table only")
            self._config_cache = {}
            return self._config_cache
        
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
            
            # Extract grace period if configured
            if "grace_period_days" in config:
                self._grace_period_days = int(config["grace_period_days"])
            
            self._config_cache = config
            logger.info("Loaded entitlement config from config/plans.json")
            return config
        except Exception as e:
            logger.warning(f"Failed to load config/plans.json: {e}, using database only")
            self._config_cache = {}
            return self._config_cache
    
    def get_billing_state(self, subscription: Optional[Subscription]) -> BillingState:
        """
        Determine billing_state from subscription.
        
        Args:
            subscription: Subscription object or None
            
        Returns:
            BillingState enum value
        """
        if not subscription:
            return BillingState.NONE
        
        status_value = subscription.status
        
        if status_value == SubscriptionStatus.ACTIVE.value:
            return BillingState.ACTIVE
        
        elif status_value == SubscriptionStatus.FROZEN.value:
            # Check if grace period is still active
            if subscription.grace_period_ends_on:
                now = datetime.now(timezone.utc)
                if now <= subscription.grace_period_ends_on:
                    return BillingState.GRACE_PERIOD
                else:
                    return BillingState.PAST_DUE
            else:
                # Frozen without grace period = past due
                return BillingState.PAST_DUE
        
        elif status_value == SubscriptionStatus.CANCELLED.value:
            return BillingState.CANCELED
        
        elif status_value == SubscriptionStatus.EXPIRED.value:
            return BillingState.EXPIRED
        
        elif status_value == SubscriptionStatus.DECLINED.value:
            return BillingState.EXPIRED
        
        else:
            # PENDING or unknown status
            return BillingState.NONE
    
    def check_feature_entitlement(
        self,
        tenant_id: str,
        feature: str,
        subscription: Optional[Subscription] = None,
    ) -> EntitlementCheckResult:
        """
        Check if tenant is entitled to a feature.
        
        Args:
            tenant_id: Tenant ID
            feature: Feature key to check
            subscription: Optional subscription (will be fetched if not provided)
            
        Returns:
            EntitlementCheckResult with entitlement status
        """
        # Fetch subscription if not provided
        if subscription is None:
            subscription = self.db.query(Subscription).filter(
                Subscription.tenant_id == tenant_id
            ).order_by(Subscription.created_at.desc()).first()
        
        billing_state = self.get_billing_state(subscription)
        plan_id = subscription.plan_id if subscription else None
        
        # Check billing_state-based access rules
        if billing_state == BillingState.EXPIRED:
            return EntitlementCheckResult(
                is_entitled=False,
                billing_state=billing_state,
                plan_id=plan_id,
                feature=feature,
                reason="Subscription has expired",
            )
        
        if billing_state == BillingState.CANCELED:
            # Check config for canceled behavior (end-of-period vs immediate)
            config = self._load_config()
            canceled_behavior = config.get("canceled_behavior", "immediate")
            
            if canceled_behavior == "immediate":
                return EntitlementCheckResult(
                    is_entitled=False,
                    billing_state=billing_state,
                    plan_id=plan_id,
                    feature=feature,
                    reason="Subscription has been canceled",
                )
            # else: end-of-period allows access until period_end
        
        if billing_state == BillingState.PAST_DUE:
            # Past due = hard block
            return EntitlementCheckResult(
                is_entitled=False,
                billing_state=billing_state,
                plan_id=plan_id,
                feature=feature,
                reason="Payment is past due",
            )
        
        if billing_state == BillingState.GRACE_PERIOD:
            # Grace period: allow access but with warning
            # Check if feature is enabled for plan
            if subscription and plan_id:
                is_enabled = self._check_plan_feature(plan_id, feature)
                if not is_enabled:
                    return EntitlementCheckResult(
                        is_entitled=False,
                        billing_state=billing_state,
                        plan_id=plan_id,
                        feature=feature,
                        reason=f"Feature '{feature}' not available in current plan",
                    )
                
                return EntitlementCheckResult(
                    is_entitled=True,
                    billing_state=billing_state,
                    plan_id=plan_id,
                    feature=feature,
                    grace_period_ends_on=subscription.grace_period_ends_on,
                )
            else:
                return EntitlementCheckResult(
                    is_entitled=False,
                    billing_state=billing_state,
                    plan_id=plan_id,
                    feature=feature,
                    reason="No active subscription",
                )
        
        if billing_state == BillingState.ACTIVE:
            # Active subscription: check plan features
            if subscription and plan_id:
                is_enabled = self._check_plan_feature(plan_id, feature)
                if not is_enabled:
                    # Find which plan has this feature
                    required_plan = self._find_plan_with_feature(feature)
                    return EntitlementCheckResult(
                        is_entitled=False,
                        billing_state=billing_state,
                        plan_id=plan_id,
                        feature=feature,
                        reason=f"Feature '{feature}' requires a higher plan",
                        required_plan=required_plan,
                    )
                
                return EntitlementCheckResult(
                    is_entitled=True,
                    billing_state=billing_state,
                    plan_id=plan_id,
                    feature=feature,
                )
            else:
                return EntitlementCheckResult(
                    is_entitled=False,
                    billing_state=billing_state,
                    plan_id=plan_id,
                    feature=feature,
                    reason="No active subscription",
                )
        
        # BillingState.NONE or unknown
        return EntitlementCheckResult(
            is_entitled=False,
            billing_state=billing_state,
            plan_id=plan_id,
            feature=feature,
            reason="No subscription found",
        )
    
    def _check_plan_feature(self, plan_id: str, feature: str) -> bool:
        """
        Check if a plan has a feature enabled.
        
        Args:
            plan_id: Plan ID
            feature: Feature key
            
        Returns:
            True if feature is enabled for plan
        """
        plan_feature = self.db.query(PlanFeature).filter(
            PlanFeature.plan_id == plan_id,
            PlanFeature.feature_key == feature,
            PlanFeature.is_enabled == True
        ).first()
        
        return plan_feature is not None
    
    def _find_plan_with_feature(self, feature: str) -> Optional[str]:
        """
        Find a plan that has the feature enabled.
        
        Args:
            feature: Feature key
            
        Returns:
            Plan ID that has the feature, or None
        """
        plan_feature = self.db.query(PlanFeature).filter(
            PlanFeature.feature_key == feature,
            PlanFeature.is_enabled == True
        ).join(Plan).filter(
            Plan.is_active == True
        ).order_by(Plan.price_monthly_cents.asc().nullslast()).first()
        
        if plan_feature:
            return plan_feature.plan_id
        return None


def get_billing_state_from_subscription(
    subscription: Optional[Subscription]
) -> BillingState:
    """
    Convenience function to get billing state from subscription.
    
    Args:
        subscription: Subscription object or None
        
    Returns:
        BillingState enum value
    """
    if not subscription:
        return BillingState.NONE
    
    status_value = subscription.status
    
    if status_value == SubscriptionStatus.ACTIVE.value:
        return BillingState.ACTIVE
    
    elif status_value == SubscriptionStatus.FROZEN.value:
        # Check if grace period is still active
        if subscription.grace_period_ends_on:
            now = datetime.now(timezone.utc)
            if now <= subscription.grace_period_ends_on:
                return BillingState.GRACE_PERIOD
            else:
                return BillingState.PAST_DUE
        else:
            return BillingState.PAST_DUE
    
    elif status_value == SubscriptionStatus.CANCELLED.value:
        return BillingState.CANCELED
    
    elif status_value == SubscriptionStatus.EXPIRED.value:
        return BillingState.EXPIRED
    
    elif status_value == SubscriptionStatus.DECLINED.value:
        return BillingState.EXPIRED
    
    else:
        return BillingState.NONE
