"""
Backfill audit event emitters — standardized audit logging for backfill lifecycle.

Each function builds the required metadata per the AUDITABLE_EVENTS registry
and delegates to log_system_audit_event_sync. All calls are wrapped in
try/except so audit failures never crash the caller.

Events:
- backfill.requested  — admin submits a backfill request
- backfill.started    — executor begins processing (creates chunk jobs)
- backfill.paused     — operator pauses queued chunks
- backfill.failed     — request reaches terminal failure
- backfill.completed  — all chunks finished successfully

Story 3.4 - Backfill Audit
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
