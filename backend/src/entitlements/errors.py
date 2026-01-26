"""
Structured error classes for entitlement enforcement.
"""

from typing import Optional
from fastapi import status


class EntitlementError(Exception):
    """Base exception for entitlement errors."""
    pass


class EntitlementDeniedError(EntitlementError):
    """
    Raised when a feature entitlement check fails.
    
    Includes machine-readable reason codes for programmatic handling.
    """
    
    def __init__(
        self,
        feature: str,
        reason: str,
        billing_state: str,
        plan_id: Optional[str] = None,
        required_plan: Optional[str] = None,
        http_status: int = status.HTTP_402_PAYMENT_REQUIRED,
    ):
        """
        Initialize entitlement denied error.
        
        Args:
            feature: Feature key that was denied
            reason: Human-readable reason
            billing_state: Current billing state (active, past_due, grace_period, canceled, expired)
            plan_id: Current plan ID (if any)
            required_plan: Required plan ID for this feature (if known)
            http_status: HTTP status code (default 402)
        """
        self.feature = feature
        self.reason = reason
        self.billing_state = billing_state
        self.plan_id = plan_id
        self.required_plan = required_plan
        self.http_status = http_status
        super().__init__(f"Feature '{feature}' denied: {reason}")
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON response."""
        return {
            "error": "entitlement_denied",
            "feature": self.feature,
            "reason": self.reason,
            "billing_state": self.billing_state,
            "plan_id": self.plan_id,
            "required_plan": self.required_plan,
            "machine_readable": {
                "code": self._get_reason_code(),
                "billing_state": self.billing_state,
                "feature": self.feature,
            }
        }
    
    def _get_reason_code(self) -> str:
        """Get machine-readable reason code."""
        if self.billing_state == "expired":
            return "subscription_expired"
        elif self.billing_state == "canceled":
            return "subscription_canceled"
        elif self.billing_state == "past_due":
            return "payment_past_due"
        elif self.billing_state == "grace_period":
            return "payment_grace_period"
        elif self.required_plan:
            return "plan_upgrade_required"
        else:
            return "feature_not_entitled"
