"""
Governance Module for Shopify Analytics App

This module implements:
- 5.8.1: Approval-gated deployment system
- 5.8.2: Metric version enforcement
- 5.8.3: Rollback orchestrator
- 5.8.4: Pre-deploy validation framework
- 5.8.5: AI guardrails

IMPORTANT: AI agents may implement logic but MUST NOT:
- Approve changes
- Classify breaking vs non-breaking
- Decide merchant communication
- Sign off production deployments
- Trigger rollbacks autonomously
"""

from .approval_gate import ApprovalGate, ApprovalResult
from .metric_versioning import MetricVersionResolver, DeprecationWarning
from .rollback_orchestrator import RollbackOrchestrator, RollbackState
from .pre_deploy_validator import PreDeployValidator, ValidationResult
from .ai_guardrails import AIGuardrails, GuardrailRefusal

__all__ = [
    "ApprovalGate",
    "ApprovalResult",
    "MetricVersionResolver",
    "DeprecationWarning",
    "RollbackOrchestrator",
    "RollbackState",
    "PreDeployValidator",
    "ValidationResult",
    "AIGuardrails",
    "GuardrailRefusal",
]
