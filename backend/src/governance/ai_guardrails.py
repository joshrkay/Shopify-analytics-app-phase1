"""
5.8.5 - AI Guardrails System

Enforces boundaries on AI agents. Never approve changes, always require human accountability.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .base import load_yaml_config, serialize_dataclass

logger = logging.getLogger(__name__)


class RefusalReason(Enum):
    """Categories of refusal reasons."""

    PROHIBITED_ACTION = "prohibited_action"
    REQUIRES_HUMAN_JUDGMENT = "requires_human_judgment"
    BUSINESS_DECISION = "business_decision"
    SECURITY_CRITICAL = "security_critical"
    ACCOUNTABILITY_REQUIRED = "accountability_required"


@dataclass
class GuardrailRefusal:
    """
    Result when an action is refused by guardrails.

    Attributes:
        request_id: Unique ID for this refusal
        action_attempted: What action was attempted
        reason: Why it was refused
        reason_category: Category of refusal
        redirect_to: Who should handle this instead
        timestamp: When the refusal occurred
        user_context: Additional context about the request
    """

    request_id: str
    action_attempted: str
    reason: str
    reason_category: RefusalReason
    redirect_to: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return serialize_dataclass(self)

    def format_response(self) -> str:
        """Format the refusal as a human-readable response."""
        return f"""REFUSED: {self.action_attempted}

Reason: {self.reason}

This action requires human decision-making.
Please contact: {self.redirect_to}

Request ID: {self.request_id}
Timestamp: {self.timestamp.isoformat()}"""


@dataclass
class GuardrailCheck:
    """Result of checking an action against guardrails."""

    allowed: bool
    action_id: str
    refusal: GuardrailRefusal | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return serialize_dataclass(self)


@dataclass
class AuditEntry:
    """Audit log entry for guardrail decisions."""

    entry_id: str
    timestamp: datetime
    action_id: str
    action_type: str
    allowed: bool
    refusal_reason: str | None
    redirect_target: str | None
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return serialize_dataclass(self)


class AIGuardrails:
    """
    AI Guardrails enforcement system.

    Checks all AI agent actions against defined restrictions and
    refuses prohibited actions with clear messaging.
    """

    def __init__(
        self,
        config_path: str | Path,
        audit_logger: logging.Logger | None = None,
        on_refusal: Callable[[GuardrailRefusal], None] | None = None,
    ):
        """
        Initialize the guardrails system.

        Args:
            config_path: Path to ai_restrictions.yaml
            audit_logger: Logger for audit trail
            on_refusal: Callback when an action is refused
        """
        self.config_path = Path(config_path)
        self.audit_logger = audit_logger or logging.getLogger("guardrails_audit")
        self.on_refusal = on_refusal

        self._config: dict[str, Any] = {}
        self._prohibited_actions: dict[str, dict[str, Any]] = {}
        self._required_behaviors: dict[str, dict[str, Any]] = {}
        self._audit_log: list[AuditEntry] = []

        self._load_config()

    def _load_config(self) -> None:
        """Load guardrails configuration from YAML."""
        self._config = load_yaml_config(self.config_path, logger)

        # Index prohibited actions for fast lookup
        restrictions = self._config.get("ai_restrictions", {})
        for action in restrictions.get("prohibited_actions", []):
            action_id = action.get("id", "")
            self._prohibited_actions[action_id] = action

        # Index required behaviors
        for behavior in restrictions.get("required_behaviors", []):
            behavior_id = behavior.get("id", "")
            self._required_behaviors[behavior_id] = behavior

    def check_action(
        self,
        action_id: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailCheck:
        """
        Check if an action is allowed.

        Args:
            action_id: ID of the action to check
            context: Additional context about the action

        Returns:
            GuardrailCheck with allowed status and any refusal details
        """
        context = context or {}
        request_id = str(uuid.uuid4())

        # Check if action is prohibited
        if action_id in self._prohibited_actions:
            prohibition = self._prohibited_actions[action_id]

            refusal = GuardrailRefusal(
                request_id=request_id,
                action_attempted=prohibition.get("description", action_id),
                reason=prohibition.get("reason", "Action is prohibited"),
                reason_category=RefusalReason.PROHIBITED_ACTION,
                redirect_to=prohibition.get("redirect_to", "Human supervisor"),
                user_context=context,
            )

            self._log_audit(
                action_id=action_id,
                action_type="prohibited_action",
                allowed=False,
                refusal_reason=refusal.reason,
                redirect_target=refusal.redirect_to,
                context=context,
            )

            # Call refusal callback if registered
            if self.on_refusal:
                self.on_refusal(refusal)

            return GuardrailCheck(
                allowed=False,
                action_id=action_id,
                refusal=refusal,
            )

        # Action is allowed
        self._log_audit(
            action_id=action_id,
            action_type="allowed_action",
            allowed=True,
            refusal_reason=None,
            redirect_target=None,
            context=context,
        )

        return GuardrailCheck(allowed=True, action_id=action_id)

    def refuse_action(
        self,
        action_description: str,
        reason: str,
        reason_category: RefusalReason,
        redirect_to: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailRefusal:
        """
        Explicitly refuse an action.

        Use this when an action should be refused based on runtime context,
        not just configuration.

        Args:
            action_description: What action was attempted
            reason: Why it's being refused
            reason_category: Category of the refusal
            redirect_to: Who should handle this
            context: Additional context

        Returns:
            GuardrailRefusal with full details
        """
        context = context or {}
        request_id = str(uuid.uuid4())

        refusal = GuardrailRefusal(
            request_id=request_id,
            action_attempted=action_description,
            reason=reason,
            reason_category=reason_category,
            redirect_to=redirect_to,
            user_context=context,
        )

        self._log_audit(
            action_id=f"runtime_refusal_{request_id}",
            action_type="runtime_refusal",
            allowed=False,
            refusal_reason=reason,
            redirect_target=redirect_to,
            context=context,
        )

        if self.on_refusal:
            self.on_refusal(refusal)

        return refusal

    def require_human_approval(
        self,
        action_description: str,
        approver_role: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailRefusal:
        """
        Require human approval for an action.

        Args:
            action_description: What needs approval
            approver_role: Role that must approve
            context: Additional context

        Returns:
            GuardrailRefusal redirecting to the approver
        """
        return self.refuse_action(
            action_description=action_description,
            reason=f"This action requires approval from {approver_role}",
            reason_category=RefusalReason.ACCOUNTABILITY_REQUIRED,
            redirect_to=approver_role,
            context=context,
        )

    def check_business_decision(
        self,
        decision_description: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailRefusal:
        """
        Refuse a business decision that AI should not make.

        Args:
            decision_description: What decision is being requested
            context: Additional context

        Returns:
            GuardrailRefusal for the business decision
        """
        return self.refuse_action(
            action_description=decision_description,
            reason="AI cannot make business decisions. This requires human judgment "
            "based on domain expertise, customer relationships, and business context.",
            reason_category=RefusalReason.BUSINESS_DECISION,
            redirect_to="Product Manager or Domain Expert",
            context=context,
        )

    def enforce_behavior(self, behavior_id: str) -> bool:
        """
        Check if a required behavior is enforced.

        Args:
            behavior_id: ID of the behavior to check

        Returns:
            True if the behavior should be enforced
        """
        behavior = self._required_behaviors.get(behavior_id, {})
        return behavior.get("enforcement") == "mandatory"

    def _log_audit(
        self,
        action_id: str,
        action_type: str,
        allowed: bool,
        refusal_reason: str | None,
        redirect_target: str | None,
        context: dict[str, Any],
    ) -> None:
        """Log an audit entry."""
        entry = AuditEntry(
            entry_id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc),
            action_id=action_id,
            action_type=action_type,
            allowed=allowed,
            refusal_reason=refusal_reason,
            redirect_target=redirect_target,
            context=context,
        )

        self._audit_log.append(entry)
        self.audit_logger.info(
            f"GUARDRAIL: action={action_id} | allowed={allowed} | "
            f"reason={refusal_reason or 'N/A'}"
        )

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Get the audit log."""
        return [entry.to_dict() for entry in self._audit_log]

    def get_prohibited_actions(self) -> list[dict[str, Any]]:
        """Get list of all prohibited actions."""
        return list(self._prohibited_actions.values())

    def get_required_behaviors(self) -> list[dict[str, Any]]:
        """Get list of all required behaviors."""
        return list(self._required_behaviors.values())


class GuardrailDecorator:
    """
    Decorator for enforcing guardrails on functions.

    Usage:
        guardrails = AIGuardrails(config_path)
        decorator = GuardrailDecorator(guardrails)

        @decorator.check("approve_metric_changes")
        def approve_metric(metric_id: str):
            # This will be refused
            pass
    """

    def __init__(self, guardrails: AIGuardrails):
        """Initialize with guardrails instance."""
        self.guardrails = guardrails

    def check(self, action_id: str):
        """
        Decorator that checks guardrails before function execution.

        Args:
            action_id: The action ID to check

        Returns:
            Decorator function
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                check_result = self.guardrails.check_action(
                    action_id, context={"args": str(args), "kwargs": str(kwargs)}
                )

                if not check_result.allowed:
                    raise GuardrailViolation(check_result.refusal)

                return func(*args, **kwargs)

            return wrapper

        return decorator

    def require_approval(self, approver_role: str):
        """
        Decorator that requires human approval before function execution.

        Args:
            approver_role: Role that must approve

        Returns:
            Decorator function
        """

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                refusal = self.guardrails.require_human_approval(
                    action_description=f"Execute {func.__name__}",
                    approver_role=approver_role,
                    context={"function": func.__name__},
                )
                raise GuardrailViolation(refusal)

            return wrapper

        return decorator


class GuardrailViolation(Exception):
    """Exception raised when a guardrail is violated."""

    def __init__(self, refusal: GuardrailRefusal):
        """Initialize with refusal details."""
        self.refusal = refusal
        super().__init__(refusal.format_response())


# Pre-built guardrail checks for common scenarios
class CommonGuardrails:
    """Common guardrail checks for analytics operations."""

    def __init__(self, guardrails: AIGuardrails):
        """Initialize with guardrails instance."""
        self.guardrails = guardrails

    def check_metric_approval(self, metric_id: str) -> GuardrailCheck:
        """Check if AI can approve a metric change."""
        return self.guardrails.check_action(
            "approve_metric_changes",
            context={"metric_id": metric_id},
        )

    def check_breaking_change_classification(
        self, change_description: str
    ) -> GuardrailCheck:
        """Check if AI can classify a breaking change."""
        return self.guardrails.check_action(
            "classify_breaking_changes",
            context={"change_description": change_description},
        )

    def check_merchant_communication(self, message: str) -> GuardrailCheck:
        """Check if AI can decide merchant communication."""
        return self.guardrails.check_action(
            "decide_merchant_communication",
            context={"message_preview": message[:100]},
        )

    def check_production_signoff(self, deployment_id: str) -> GuardrailCheck:
        """Check if AI can sign off on production."""
        return self.guardrails.check_action(
            "sign_off_production",
            context={"deployment_id": deployment_id},
        )

    def check_rollback_trigger(self, reason: str) -> GuardrailCheck:
        """Check if AI can autonomously trigger rollback."""
        return self.guardrails.check_action(
            "trigger_rollback",
            context={"reason": reason},
        )

    def check_rls_modification(self, rule_id: str) -> GuardrailCheck:
        """Check if AI can modify RLS rules."""
        return self.guardrails.check_action(
            "modify_rls_rules",
            context={"rule_id": rule_id},
        )

    def refuse_data_discrepancy_interpretation(
        self,
        merchant_report: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailRefusal:
        """
        Refuse to interpret a data discrepancy.

        Data discrepancies require human investigation because:
        - Multiple possible causes (RLS, freshness, definition, rounding, cache)
        - Requires domain knowledge to determine root cause
        - May require customer communication
        """
        return self.guardrails.refuse_action(
            action_description="Interpret merchant-reported data discrepancy",
            reason=(
                "Data discrepancy interpretation requires human investigation. "
                "Possible causes include: RLS configuration, data freshness, "
                "metric definition differences, rounding errors, or cached data. "
                "AI cannot determine the correct cause without domain expertise."
            ),
            reason_category=RefusalReason.REQUIRES_HUMAN_JUDGMENT,
            redirect_to="Data Engineer or Support",
            context={
                "merchant_report": merchant_report,
                **(context or {}),
            },
        )
