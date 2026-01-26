"""
Governance Module - Story 5.8

AI agents MUST NOT: approve changes, classify breaking changes,
decide communication, sign off deployments, or trigger rollbacks.
"""

from .approval_gate import ApprovalGate, ApprovalResult
from .metric_versioning import MetricVersionResolver, DeprecationWarning
from .rollback_orchestrator import RollbackOrchestrator, RollbackState
from .pre_deploy_validator import PreDeployValidator, ValidationResult
from .ai_guardrails import AIGuardrails, GuardrailRefusal
from .base import load_yaml_config, serialize_dataclass, AuditLogger

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
    "load_yaml_config",
    "serialize_dataclass",
    "AuditLogger",
]
