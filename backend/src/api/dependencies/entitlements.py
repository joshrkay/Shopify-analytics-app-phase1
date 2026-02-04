"""
Entitlement check dependencies.

Provides reusable FastAPI dependencies for checking feature entitlements.
Centralizes the duplicate entitlement check logic from route files.
"""

import logging
from typing import Callable

from fastapi import Request, HTTPException, status, Depends

from src.platform.tenant_context import get_tenant_context
from src.database.session import get_db_session
from src.services.billing_entitlements import (
    BillingEntitlementsService,
    BillingFeature,
)


logger = logging.getLogger(__name__)


def create_entitlement_check(
    feature: BillingFeature,
    feature_name: str,
    default_required_tier: str = "paid",
) -> Callable:
    """
    Factory function to create an entitlement check dependency.

    Args:
        feature: The BillingFeature to check
        feature_name: Human-readable name for error messages (e.g., "AI Insights")
        default_required_tier: Default tier name for error message if none specified

    Returns:
        A FastAPI dependency function that checks entitlement and returns db_session
    """

    def check_entitlement(
        request: Request,
        db_session=Depends(get_db_session),
    ):
        """
        Dependency to check feature entitlement.

        Raises 402 Payment Required if tenant is not entitled.
        Returns db_session if entitled.
        """
        tenant_ctx = get_tenant_context(request)
        service = BillingEntitlementsService(db_session, tenant_ctx.tenant_id)
        result = service.check_feature_entitlement(feature)

        if not result.is_entitled:
            logger.warning(
                f"{feature_name} access denied - not entitled",
                extra={
                    "tenant_id": tenant_ctx.tenant_id,
                    "current_tier": result.current_tier,
                    "feature": feature.value,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"{feature_name} requires a {result.required_tier or default_required_tier} plan",
            )

        return db_session

    return check_entitlement


# Pre-configured entitlement checks for common features
check_ai_insights_entitlement = create_entitlement_check(
    feature=BillingFeature.AI_INSIGHTS,
    feature_name="AI Insights",
    default_required_tier="paid",
)

check_ai_recommendations_entitlement = create_entitlement_check(
    feature=BillingFeature.AI_RECOMMENDATIONS,
    feature_name="AI Recommendations",
    default_required_tier="paid",
)

check_ai_actions_entitlement = create_entitlement_check(
    feature=BillingFeature.AI_ACTIONS,
    feature_name="AI Actions",
    default_required_tier="Growth",
)

check_llm_routing_entitlement = create_entitlement_check(
    feature=BillingFeature.LLM_ROUTING,
    feature_name="LLM Routing",
    default_required_tier="Pro",
)
