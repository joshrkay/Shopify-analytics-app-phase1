"""
LLM Integration helpers for Story 8.8 - Model Routing & Prompt Governance.

Provides simple integration points for existing services to optionally
use LLM-enhanced content generation.

DESIGN PRINCIPLES:
- Existing services remain deterministic by default
- LLM is opt-in, not required
- Graceful fallback on LLM failure (use deterministic template)
- No changes required to existing service signatures

SECURITY:
- Tenant isolation enforced
- All LLM calls are logged
- No PII in prompts

Usage:
    # In a service that wants optional LLM enhancement
    from src.services.llm_integration import enhance_with_llm

    # Deterministic fallback if LLM fails or is disabled
    summary = deterministic_template_render(data)

    # Optionally enhance with LLM (if enabled and entitled)
    enhanced_summary = await enhance_with_llm(
        db_session=self.db,
        tenant_id=self.tenant_id,
        template_key="insight_analysis",
        variables={"metric_name": "ROAS", ...},
        fallback_content=summary,  # Use if LLM fails
    )
"""

import logging
from typing import Optional, Dict, Any

from sqlalchemy.orm import Session

from src.services.billing_entitlements import BillingEntitlementsService, BillingFeature


logger = logging.getLogger(__name__)


async def enhance_with_llm(
    db_session: Session,
    tenant_id: str,
    template_key: str,
    variables: Dict[str, Any],
    fallback_content: str,
    system_message: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Optionally enhance content using LLM.

    Returns fallback_content if:
    - LLM routing is not entitled for tenant
    - Template is not found
    - LLM call fails for any reason

    This ensures existing deterministic behavior is preserved.

    Args:
        db_session: Database session
        tenant_id: Tenant ID from JWT
        template_key: Prompt template to use
        variables: Variables for template rendering
        fallback_content: Content to return if LLM fails
        system_message: Optional system message
        metadata: Optional request metadata for logging

    Returns:
        LLM-enhanced content or fallback_content
    """
    # Check entitlement first
    entitlements = BillingEntitlementsService(db_session, tenant_id)
    result = entitlements.check_feature_entitlement(BillingFeature.LLM_ROUTING)

    if not result.is_entitled:
        logger.debug(
            "LLM enhancement skipped - not entitled",
            extra={"tenant_id": tenant_id, "template_key": template_key},
        )
        return fallback_content

    try:
        from src.services.llm_routing_service import LLMRoutingService

        service = LLMRoutingService(db_session, tenant_id)

        result = await service.complete_with_template(
            template_key=template_key,
            variables=variables,
            system_message=system_message,
            metadata=metadata,
        )

        logger.info(
            "LLM enhancement successful",
            extra={
                "tenant_id": tenant_id,
                "template_key": template_key,
                "model_id": result.model_id,
                "tokens": result.total_tokens,
            },
        )

        return result.content

    except Exception as e:
        # Log and return fallback - never fail the calling service
        logger.warning(
            "LLM enhancement failed, using fallback",
            extra={
                "tenant_id": tenant_id,
                "template_key": template_key,
                "error": str(e),
            },
        )
        return fallback_content


def is_llm_enabled(db_session: Session, tenant_id: str) -> bool:
    """
    Check if LLM routing is enabled for a tenant.

    Args:
        db_session: Database session
        tenant_id: Tenant ID from JWT

    Returns:
        True if tenant has LLM routing entitlement
    """
    entitlements = BillingEntitlementsService(db_session, tenant_id)
    result = entitlements.check_feature_entitlement(BillingFeature.LLM_ROUTING)
    return result.is_entitled
