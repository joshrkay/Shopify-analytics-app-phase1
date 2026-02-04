"""
API Dependencies module.

Provides shared FastAPI dependencies for route handlers.
"""

from src.api.dependencies.entitlements import (
    create_entitlement_check,
    check_ai_insights_entitlement,
    check_ai_recommendations_entitlement,
    check_ai_actions_entitlement,
    check_llm_routing_entitlement,
)

__all__ = [
    "create_entitlement_check",
    "check_ai_insights_entitlement",
    "check_ai_recommendations_entitlement",
    "check_ai_actions_entitlement",
    "check_llm_routing_entitlement",
]
