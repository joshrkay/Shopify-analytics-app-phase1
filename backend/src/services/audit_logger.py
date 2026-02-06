"""
Audit event emitters — standardized audit logging for backfill and data quality lifecycle.

Each function builds the required metadata per the AUDITABLE_EVENTS registry
and delegates to log_system_audit_event_sync. All calls are wrapped in
try/except so audit failures never crash the caller.

Events:
- backfill.requested     — admin submits a backfill request
- backfill.started       — executor begins processing (creates chunk jobs)
- backfill.paused        — operator pauses queued chunks
- backfill.failed        — request reaches terminal failure
- backfill.completed     — all chunks finished successfully
- data.quality.warn      — data quality degraded to WARN state
- data.quality.fail      — data quality degraded to FAIL state
- data.quality.recovered — data quality recovered to PASS state

Story 3.4 - Backfill Audit
Story 4.1 - Data Quality Rules
"""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_RESOURCE_TYPE = "historical_backfill_request"


def _build_base_metadata(request) -> dict:
    """Build the common metadata fields shared by all backfill events."""
    start = (
        request.start_date.isoformat() if request.start_date else ""
    )
    end = (
        request.end_date.isoformat() if request.end_date else ""
    )
    return {
        "backfill_id": request.id,
        "tenant_id": request.tenant_id,
        "source_system": request.source_system,
        "date_range": {"start": start, "end": end},
        "requested_by": request.requested_by,
    }


def emit_backfill_requested(
    db: Session,
    request,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit backfill.requested when an admin creates a backfill request."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        metadata = _build_base_metadata(request)
        metadata["reason"] = request.reason or ""

        log_system_audit_event_sync(
            db=db,
            tenant_id=request.tenant_id,
            action=AuditAction.BACKFILL_REQUESTED,
            resource_type=_RESOURCE_TYPE,
            resource_id=request.id,
            metadata=metadata,
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_backfill_requested_failed",
            extra={"backfill_id": request.id},
            exc_info=True,
        )


def emit_backfill_started(
    db: Session,
    request,
    total_chunks: int,
) -> None:
    """Emit backfill.started when executor creates chunk jobs and begins."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        metadata = _build_base_metadata(request)
        metadata["total_chunks"] = total_chunks
        metadata["started_at"] = (
            request.started_at.isoformat()
            if request.started_at
            else datetime.now(timezone.utc).isoformat()
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=request.tenant_id,
            action=AuditAction.BACKFILL_STARTED,
            resource_type=_RESOURCE_TYPE,
            resource_id=request.id,
            metadata=metadata,
            source="worker",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_backfill_started_failed",
            extra={"backfill_id": request.id},
            exc_info=True,
        )


def emit_backfill_paused(
    db: Session,
    request,
    paused_chunks: int,
) -> None:
    """Emit backfill.paused when an operator pauses a running backfill."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        metadata = _build_base_metadata(request)
        metadata["paused_chunks"] = paused_chunks
        metadata["paused_at"] = datetime.now(timezone.utc).isoformat()

        log_system_audit_event_sync(
            db=db,
            tenant_id=request.tenant_id,
            action=AuditAction.BACKFILL_PAUSED,
            resource_type=_RESOURCE_TYPE,
            resource_id=request.id,
            metadata=metadata,
            source="worker",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_backfill_paused_failed",
            extra={"backfill_id": request.id},
            exc_info=True,
        )


def emit_backfill_failed(
    db: Session,
    request,
) -> None:
    """Emit backfill.failed when a backfill reaches terminal failure."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        metadata = _build_base_metadata(request)
        metadata["reason"] = request.error_message or "Unknown failure"
        metadata["failed_at"] = (
            request.completed_at.isoformat()
            if request.completed_at
            else datetime.now(timezone.utc).isoformat()
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=request.tenant_id,
            action=AuditAction.BACKFILL_FAILED,
            resource_type=_RESOURCE_TYPE,
            resource_id=request.id,
            metadata=metadata,
            source="worker",
            outcome=AuditOutcome.FAILURE,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_backfill_failed_failed",
            extra={"backfill_id": request.id},
            exc_info=True,
        )


def emit_backfill_completed(
    db: Session,
    request,
) -> None:
    """Emit backfill.completed when all chunks finish successfully."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        metadata = _build_base_metadata(request)
        metadata["completed_at"] = (
            request.completed_at.isoformat()
            if request.completed_at
            else datetime.now(timezone.utc).isoformat()
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=request.tenant_id,
            action=AuditAction.BACKFILL_COMPLETED,
            resource_type=_RESOURCE_TYPE,
            resource_id=request.id,
            metadata=metadata,
            source="worker",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_backfill_completed_failed",
            extra={"backfill_id": request.id},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Data quality audit event emitters (Story 4.1)
# ---------------------------------------------------------------------------

_DQ_RESOURCE_TYPE = "data_quality"


def _build_dq_metadata(
    tenant_id: str,
    dataset: str,
    rule_type: str,
    severity: str,
    detected_at: str,
) -> dict:
    """Build metadata dict for data quality audit events."""
    return {
        "tenant_id": tenant_id,
        "dataset": dataset,
        "rule_type": rule_type,
        "severity": severity,
        "detected_at": detected_at,
    }


def emit_quality_warn(
    db: Session,
    tenant_id: str,
    dataset: str,
    rule_type: str,
    severity: str,
    detected_at: str,
) -> None:
    """Emit data.quality.warn when quality degrades to WARN state."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.DATA_QUALITY_WARN,
            resource_type=_DQ_RESOURCE_TYPE,
            metadata=_build_dq_metadata(
                tenant_id, dataset, rule_type, severity, detected_at,
            ),
            source="system",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_quality_warn_failed",
            extra={"tenant_id": tenant_id, "dataset": dataset},
            exc_info=True,
        )


def emit_quality_fail(
    db: Session,
    tenant_id: str,
    dataset: str,
    rule_type: str,
    severity: str,
    detected_at: str,
) -> None:
    """Emit data.quality.fail when quality degrades to FAIL state."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.DATA_QUALITY_FAIL,
            resource_type=_DQ_RESOURCE_TYPE,
            metadata=_build_dq_metadata(
                tenant_id, dataset, rule_type, severity, detected_at,
            ),
            source="system",
            outcome=AuditOutcome.FAILURE,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_quality_fail_failed",
            extra={"tenant_id": tenant_id, "dataset": dataset},
            exc_info=True,
        )


def emit_root_cause_signal_generated(
    db: Session,
    tenant_id: str,
    dataset: str,
    anomaly_type: str,
    signal_id: str,
    top_cause_type: str | None,
    hypothesis_count: int,
    detected_at: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit data.quality.root_cause_generated when a root cause signal is persisted.

    Story 4.2 - Data Quality Root Cause Signals
    """
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ROOT_CAUSE_SIGNAL_GENERATED,
            resource_type="root_cause_signal",
            resource_id=signal_id,
            metadata={
                "tenant_id": tenant_id,
                "dataset": dataset,
                "anomaly_type": anomaly_type,
                "signal_id": signal_id,
                "top_cause_type": top_cause_type or "none",
                "hypothesis_count": hypothesis_count,
                "detected_at": detected_at,
            },
            correlation_id=correlation_id,
            source="system",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_root_cause_signal_generated_failed",
            extra={"tenant_id": tenant_id, "signal_id": signal_id},
            exc_info=True,
        )


def emit_root_cause_signal_updated(
    db: Session,
    tenant_id: str,
    dataset: str,
    signal_id: str,
    update_type: str,
    highest_confidence: float,
    hypothesis_count: int,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit data.quality.root_cause_updated when a root cause signal is updated.

    Story 4.2 - Data Quality Root Cause Signals (Prompt 4.2.8)
    """
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ROOT_CAUSE_SIGNAL_UPDATED,
            resource_type="root_cause_signal",
            resource_id=signal_id,
            metadata={
                "tenant_id": tenant_id,
                "dataset": dataset,
                "signal_id": signal_id,
                "update_type": update_type,
                "highest_confidence": highest_confidence,
                "hypothesis_count": hypothesis_count,
            },
            correlation_id=correlation_id,
            source="system",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_root_cause_signal_updated_failed",
            extra={"tenant_id": tenant_id, "signal_id": signal_id},
            exc_info=True,
        )


def emit_quality_recovered(
    db: Session,
    tenant_id: str,
    dataset: str,
    rule_type: str,
    severity: str,
    detected_at: str,
) -> None:
    """Emit data.quality.recovered when quality returns to PASS state."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.DATA_QUALITY_RECOVERED,
            resource_type=_DQ_RESOURCE_TYPE,
            metadata=_build_dq_metadata(
                tenant_id, dataset, rule_type, severity, detected_at,
            ),
            source="system",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_quality_recovered_failed",
            extra={"tenant_id": tenant_id, "dataset": dataset},
            exc_info=True,
        )
