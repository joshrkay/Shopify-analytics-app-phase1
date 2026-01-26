"""
5.8.1 - Approval-Gated Deployment System

Reads approvals from config, blocks deployment if requirements not met.
AI MUST NOT decide who approves or auto-approve anything.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .base import load_yaml_config, serialize_dataclass

logger = logging.getLogger(__name__)


class ApprovalStatus(Enum):
    """Possible approval statuses."""

    PASS = "PASS"
    BLOCK = "BLOCK"
    PENDING = "PENDING"
    EXPIRED = "EXPIRED"


@dataclass
class ApprovalResult:
    """
    Deterministic output from approval validation.

    Attributes:
        status: PASS or BLOCK
        reason: Human-readable explanation
        change_request_id: ID of the change request
        missing_approvals: List of missing required approvals
        expired: Whether the SLA has expired
        checklist_incomplete: List of incomplete checklist items
        audit_id: Unique ID for audit trail
        timestamp: When this result was generated
    """

    status: ApprovalStatus
    reason: str
    change_request_id: str
    missing_approvals: list[str] = field(default_factory=list)
    expired: bool = False
    checklist_incomplete: list[str] = field(default_factory=list)
    audit_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return serialize_dataclass(self)


@dataclass
class AuditLogEntry:
    """Immutable audit log entry for approval decisions."""

    audit_id: str
    timestamp: datetime
    change_request_id: str
    action: str
    result: ApprovalStatus
    reason: str
    context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return serialize_dataclass(self)


class ApprovalGate:
    """
    Approval-gated deployment system.

    Validates change requests against approval configuration and
    blocks deployment if requirements are not met.
    """

    def __init__(
        self,
        config_path: str | Path,
        change_requests_path: str | Path,
        audit_logger: logging.Logger | None = None,
    ):
        """
        Initialize the approval gate.

        Args:
            config_path: Path to change_approvals.yaml
            change_requests_path: Path to change_requests.yaml
            audit_logger: Logger for immutable audit trail
        """
        self.config_path = Path(config_path)
        self.change_requests_path = Path(change_requests_path)
        self.audit_logger = audit_logger or logging.getLogger("approval_audit")

        self._config: dict[str, Any] = {}
        self._change_requests: dict[str, Any] = {}
        self._audit_log: list[AuditLogEntry] = []

        self._load_config()
        self._load_change_requests()

    def _load_config(self) -> None:
        """Load approval configuration from YAML."""
        self._config = load_yaml_config(self.config_path, logger)

    def _load_change_requests(self) -> None:
        """Load change requests from YAML."""
        self._change_requests = load_yaml_config(self.change_requests_path, logger)

    def _log_audit(self, entry: AuditLogEntry) -> None:
        """
        Log an audit entry immutably.

        Audit logs are append-only and cannot be modified or deleted.
        """
        self._audit_log.append(entry)
        self.audit_logger.info(
            f"AUDIT: {entry.action} | CR: {entry.change_request_id} | "
            f"Result: {entry.result.value} | Reason: {entry.reason}"
        )

    def validate_change_request(self, change_request_id: str) -> ApprovalResult:
        """
        Validate a change request for deployment.

        Args:
            change_request_id: The ID of the change request to validate

        Returns:
            ApprovalResult with PASS or BLOCK status and human-readable reason
        """
        # Find the change request
        change_request = self._find_change_request(change_request_id)
        if not change_request:
            result = ApprovalResult(
                status=ApprovalStatus.BLOCK,
                reason=f"Change request '{change_request_id}' not found",
                change_request_id=change_request_id,
            )
            self._log_audit(
                AuditLogEntry(
                    audit_id=result.audit_id,
                    timestamp=result.timestamp,
                    change_request_id=change_request_id,
                    action="validate_change_request",
                    result=ApprovalStatus.BLOCK,
                    reason="Change request not found",
                    context={},
                )
            )
            return result

        change_type = change_request.get("type", "unknown")
        approval_config = self._get_approval_config(change_type)

        if not approval_config:
            result = ApprovalResult(
                status=ApprovalStatus.BLOCK,
                reason=f"No approval configuration found for type '{change_type}'",
                change_request_id=change_request_id,
            )
            self._log_audit(
                AuditLogEntry(
                    audit_id=result.audit_id,
                    timestamp=result.timestamp,
                    change_request_id=change_request_id,
                    action="validate_change_request",
                    result=ApprovalStatus.BLOCK,
                    reason="No approval configuration",
                    context={"change_type": change_type},
                )
            )
            return result

        # Check if approval is required
        if not approval_config.get("approval_required", True):
            result = ApprovalResult(
                status=ApprovalStatus.PASS,
                reason=f"Approval not required for type '{change_type}'",
                change_request_id=change_request_id,
            )
            self._log_audit(
                AuditLogEntry(
                    audit_id=result.audit_id,
                    timestamp=result.timestamp,
                    change_request_id=change_request_id,
                    action="validate_change_request",
                    result=ApprovalStatus.PASS,
                    reason="Approval not required",
                    context={"change_type": change_type},
                )
            )
            return result

        # Validate SLA deadline
        sla_result = self._check_sla_deadline(change_request, approval_config)
        if sla_result.status == ApprovalStatus.BLOCK:
            self._log_audit(
                AuditLogEntry(
                    audit_id=sla_result.audit_id,
                    timestamp=sla_result.timestamp,
                    change_request_id=change_request_id,
                    action="validate_sla",
                    result=ApprovalStatus.BLOCK,
                    reason="SLA expired",
                    context={"sla_deadline": change_request.get("sla_deadline")},
                )
            )
            return sla_result

        # Validate checklist completion
        checklist_result = self._check_checklist(change_request, approval_config)
        if checklist_result.status == ApprovalStatus.BLOCK:
            self._log_audit(
                AuditLogEntry(
                    audit_id=checklist_result.audit_id,
                    timestamp=checklist_result.timestamp,
                    change_request_id=change_request_id,
                    action="validate_checklist",
                    result=ApprovalStatus.BLOCK,
                    reason="Checklist incomplete",
                    context={
                        "incomplete_items": checklist_result.checklist_incomplete
                    },
                )
            )
            return checklist_result

        # Validate approvals
        approval_result = self._check_approvals(change_request, approval_config)

        self._log_audit(
            AuditLogEntry(
                audit_id=approval_result.audit_id,
                timestamp=approval_result.timestamp,
                change_request_id=change_request_id,
                action="validate_approvals",
                result=approval_result.status,
                reason=approval_result.reason,
                context={
                    "missing_approvals": approval_result.missing_approvals,
                    "existing_approvals": [
                        a.get("role") for a in change_request.get("approvals", [])
                    ],
                },
            )
        )

        return approval_result

    def validate_rollback(self, rollback_request: dict[str, Any]) -> ApprovalResult:
        """
        Validate a rollback request.

        Rollbacks bypass normal approval checks but require:
        - Authorized trigger authority
        - Audit logging

        Args:
            rollback_request: Dict containing rollback details

        Returns:
            ApprovalResult - rollbacks typically PASS if authority is valid
        """
        rollback_config = self._config.get("rollback_approval", {})

        if not rollback_config.get("bypass_normal_approval", True):
            # Treat as normal change request
            return self.validate_change_request(
                rollback_request.get("change_request_id", "unknown")
            )

        # Verify trigger authority
        triggered_by = rollback_request.get("triggered_by", "")
        trigger_role = rollback_request.get("trigger_role", "")
        allowed_authorities = rollback_config.get("trigger_authority", [])

        if trigger_role not in allowed_authorities:
            result = ApprovalResult(
                status=ApprovalStatus.BLOCK,
                reason=f"Rollback trigger not authorized. '{trigger_role}' is not in allowed authorities: {allowed_authorities}",
                change_request_id=rollback_request.get("rollback_id", "unknown"),
            )
        else:
            result = ApprovalResult(
                status=ApprovalStatus.PASS,
                reason=f"Rollback authorized by {trigger_role} ({triggered_by})",
                change_request_id=rollback_request.get("rollback_id", "unknown"),
            )

        # Always log rollback decisions
        self._log_audit(
            AuditLogEntry(
                audit_id=result.audit_id,
                timestamp=result.timestamp,
                change_request_id=rollback_request.get("rollback_id", "unknown"),
                action="validate_rollback",
                result=result.status,
                reason=result.reason,
                context={
                    "triggered_by": triggered_by,
                    "trigger_role": trigger_role,
                    "rollback_reason": rollback_request.get("reason", ""),
                    "post_mortem_required": rollback_config.get(
                        "post_rollback_review", "required"
                    )
                    == "required",
                },
            )
        )

        return result

    def _find_change_request(self, change_request_id: str) -> dict[str, Any] | None:
        """Find a change request by ID."""
        requests = self._change_requests.get("change_requests", [])
        for request in requests:
            if request.get("id") == change_request_id:
                return request
        return None

    def _get_approval_config(self, change_type: str) -> dict[str, Any] | None:
        """Get approval configuration for a change type."""
        return self._config.get("change_approvals", {}).get(change_type)

    def _check_sla_deadline(
        self, change_request: dict[str, Any], approval_config: dict[str, Any]
    ) -> ApprovalResult:
        """Check if SLA deadline has passed."""
        sla_deadline_str = change_request.get("sla_deadline")
        if not sla_deadline_str:
            return ApprovalResult(
                status=ApprovalStatus.PASS,
                reason="No SLA deadline specified",
                change_request_id=change_request.get("id", "unknown"),
            )

        try:
            sla_deadline = datetime.fromisoformat(
                sla_deadline_str.replace("Z", "+00:00")
            )
            now = datetime.now(timezone.utc)

            if now > sla_deadline:
                return ApprovalResult(
                    status=ApprovalStatus.BLOCK,
                    reason=f"SLA deadline expired at {sla_deadline_str}. Request new approval.",
                    change_request_id=change_request.get("id", "unknown"),
                    expired=True,
                )
        except ValueError as e:
            logger.warning(f"Invalid SLA deadline format: {sla_deadline_str} - {e}")

        return ApprovalResult(
            status=ApprovalStatus.PASS,
            reason="SLA deadline not expired",
            change_request_id=change_request.get("id", "unknown"),
        )

    def _check_checklist(
        self, change_request: dict[str, Any], approval_config: dict[str, Any]
    ) -> ApprovalResult:
        """Check if pre-approval checklist is complete."""
        required_items = approval_config.get("pre_approval_checklist", [])
        completed_items = change_request.get("checklist_completed", [])
        pending_items = change_request.get("checklist_pending", [])

        # Items that are required but not completed
        incomplete = [item for item in required_items if item not in completed_items]

        if incomplete:
            return ApprovalResult(
                status=ApprovalStatus.BLOCK,
                reason=f"Pre-approval checklist incomplete. Missing: {incomplete}",
                change_request_id=change_request.get("id", "unknown"),
                checklist_incomplete=incomplete,
            )

        return ApprovalResult(
            status=ApprovalStatus.PASS,
            reason="Pre-approval checklist complete",
            change_request_id=change_request.get("id", "unknown"),
        )

    def _check_approvals(
        self, change_request: dict[str, Any], approval_config: dict[str, Any]
    ) -> ApprovalResult:
        """Check if required approvals are present."""
        # Check for emergency approval
        if change_request.get("emergency", False):
            return self._check_emergency_approval(change_request, approval_config)

        approvers_config = approval_config.get("approvers", {})
        required_roles = []

        if isinstance(approvers_config, dict):
            if "primary" in approvers_config:
                required_roles.append(approvers_config["primary"])
        elif isinstance(approvers_config, list):
            for approver in approvers_config:
                if isinstance(approver, dict) and "primary" in approver:
                    required_roles.append(approver["primary"])

        existing_approvals = change_request.get("approvals", [])
        approved_roles = [a.get("role") for a in existing_approvals]

        missing = [role for role in required_roles if role not in approved_roles]

        if missing:
            return ApprovalResult(
                status=ApprovalStatus.BLOCK,
                reason=f"Missing required approvals from: {missing}",
                change_request_id=change_request.get("id", "unknown"),
                missing_approvals=missing,
            )

        return ApprovalResult(
            status=ApprovalStatus.PASS,
            reason="All required approvals present",
            change_request_id=change_request.get("id", "unknown"),
        )

    def _check_emergency_approval(
        self, change_request: dict[str, Any], approval_config: dict[str, Any]
    ) -> ApprovalResult:
        """Check emergency approval requirements."""
        emergency_config = approval_config.get("emergency_approval", {})
        allowed_approvers = emergency_config.get("allows", [])
        min_approvers = emergency_config.get("min_approvers", 2)
        requirements = emergency_config.get("requires", [])

        existing_approvals = change_request.get("approvals", [])

        # Check minimum approvers
        if len(existing_approvals) < min_approvers:
            return ApprovalResult(
                status=ApprovalStatus.BLOCK,
                reason=f"Emergency approval requires at least {min_approvers} approvers, got {len(existing_approvals)}",
                change_request_id=change_request.get("id", "unknown"),
            )

        # Check that approvers are in allowed list
        approved_roles = [a.get("role") for a in existing_approvals]
        valid_approvers = [role for role in approved_roles if role in allowed_approvers]

        if len(valid_approvers) < min_approvers:
            return ApprovalResult(
                status=ApprovalStatus.BLOCK,
                reason=f"Emergency approval requires approvers from {allowed_approvers}",
                change_request_id=change_request.get("id", "unknown"),
                missing_approvals=allowed_approvers,
            )

        # Check requirements (incident ticket, post-mortem)
        if "incident ticket" in requirements:
            if not change_request.get("incident_ticket"):
                return ApprovalResult(
                    status=ApprovalStatus.BLOCK,
                    reason="Emergency approval requires incident ticket",
                    change_request_id=change_request.get("id", "unknown"),
                )

        if "post-mortem" in requirements:
            if not change_request.get("post_mortem_required"):
                return ApprovalResult(
                    status=ApprovalStatus.BLOCK,
                    reason="Emergency approval requires post-mortem commitment",
                    change_request_id=change_request.get("id", "unknown"),
                )

        return ApprovalResult(
            status=ApprovalStatus.PASS,
            reason="Emergency approval requirements met",
            change_request_id=change_request.get("id", "unknown"),
        )

    def get_audit_log(self) -> list[dict[str, Any]]:
        """
        Get the immutable audit log.

        Returns:
            List of audit log entries as dictionaries
        """
        return [entry.to_dict() for entry in self._audit_log]

    def get_pending_requests(self) -> list[dict[str, Any]]:
        """Get all pending change requests."""
        requests = self._change_requests.get("change_requests", [])
        return [r for r in requests if r.get("status") == "pending_approval"]
