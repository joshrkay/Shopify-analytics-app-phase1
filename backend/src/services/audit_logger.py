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
from typing import Any

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


# ---------------------------------------------------------------------------
# Merchant data health audit event emitters (Story 4.3)
# ---------------------------------------------------------------------------

_MERCHANT_HEALTH_RESOURCE_TYPE = "merchant_data_health"


def emit_merchant_health_changed(
    db: Session,
    tenant_id: str,
    previous_state: str,
    new_state: str,
) -> None:
    """Emit merchant.data_health.changed when merchant health state transitions."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.MERCHANT_DATA_HEALTH_CHANGED,
            resource_type=_MERCHANT_HEALTH_RESOURCE_TYPE,
            metadata={
                "tenant_id": tenant_id,
                "previous_state": previous_state,
                "new_state": new_state,
            },
            source="system",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_merchant_health_changed_failed",
            extra={
                "tenant_id": tenant_id,
                "previous_state": previous_state,
                "new_state": new_state,
            },
            exc_info=True,
        )


def emit_merchant_health_unavailable(
    db: Session,
    tenant_id: str,
    previous_state: str,
) -> None:
    """Emit merchant.data_health.unavailable when health degrades to UNAVAILABLE."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.MERCHANT_DATA_HEALTH_UNAVAILABLE,
            resource_type=_MERCHANT_HEALTH_RESOURCE_TYPE,
            metadata={
                "tenant_id": tenant_id,
                "previous_state": previous_state,
            },
            source="system",
            outcome=AuditOutcome.FAILURE,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_merchant_health_unavailable_failed",
            extra={
                "tenant_id": tenant_id,
                "previous_state": previous_state,
            },
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


# ---------------------------------------------------------------------------
# Superset analytics audit event emitters (Story 5.1.7)
# ---------------------------------------------------------------------------

_ANALYTICS_RESOURCE_TYPE = "superset_analytics"


def emit_dashboard_viewed(
    db: Session,
    tenant_id: str,
    user_id: str,
    dashboard_id: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.dashboard.viewed when a user views an embedded dashboard."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ANALYTICS_DASHBOARD_VIEWED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            resource_id=dashboard_id,
            metadata={
                "dashboard_id": dashboard_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
            correlation_id=correlation_id,
            source="superset",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dashboard_viewed_failed",
            extra={"tenant_id": tenant_id, "dashboard_id": dashboard_id},
            exc_info=True,
        )


def emit_dashboard_filtered(
    db: Session,
    tenant_id: str,
    user_id: str,
    dashboard_id: str,
    filter_state: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.dashboard.filtered when a user applies filters."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ANALYTICS_DASHBOARD_FILTERED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            resource_id=dashboard_id,
            metadata={
                "dashboard_id": dashboard_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "filter_state": filter_state,
            },
            correlation_id=correlation_id,
            source="superset",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dashboard_filtered_failed",
            extra={"tenant_id": tenant_id, "dashboard_id": dashboard_id},
            exc_info=True,
        )


def emit_dashboard_drilldown_used(
    db: Session,
    tenant_id: str,
    user_id: str,
    dashboard_id: str,
    source_chart_id: int,
    target_chart_id: int,
    filter_state: dict[str, Any],
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.dashboard.drilldown_used when a user drills down."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ANALYTICS_DRILLDOWN_USED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            resource_id=dashboard_id,
            metadata={
                "dashboard_id": dashboard_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
                "source_chart_id": source_chart_id,
                "target_chart_id": target_chart_id,
                "filter_state": filter_state,
            },
            correlation_id=correlation_id,
            source="superset",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dashboard_drilldown_used_failed",
            extra={"tenant_id": tenant_id, "dashboard_id": dashboard_id},
            exc_info=True,
        )


def emit_explore_accessed(
    db: Session,
    tenant_id: str,
    user_id: str,
    dataset_name: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.explore.accessed when a user accesses Explore mode."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ANALYTICS_EXPLORE_ACCESSED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            metadata={
                "dataset_name": dataset_name,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
            correlation_id=correlation_id,
            source="superset",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_explore_accessed_failed",
            extra={"tenant_id": tenant_id, "dataset_name": dataset_name},
            exc_info=True,
        )


def emit_access_denied(
    db: Session,
    tenant_id: str,
    user_id: str,
    reason: str,
    path: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.access.denied when JWT auth fails."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id or "unknown",
            action=AuditAction.ANALYTICS_ACCESS_DENIED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            metadata={
                "reason": reason,
                "path": path,
                "user_id": user_id or "unknown",
                "tenant_id": tenant_id or "unknown",
            },
            correlation_id=correlation_id,
            source="superset",
            outcome=AuditOutcome.DENIED,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_access_denied_failed",
            extra={"tenant_id": tenant_id, "reason": reason},
            exc_info=True,
        )


def emit_cross_tenant_blocked(
    db: Session,
    tenant_id: str,
    user_id: str,
    attempted_tenant_id: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.cross_tenant.blocked when cross-tenant access is attempted."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ANALYTICS_CROSS_TENANT_BLOCKED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            metadata={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "attempted_tenant_id": attempted_tenant_id,
            },
            correlation_id=correlation_id,
            source="superset",
            outcome=AuditOutcome.DENIED,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_cross_tenant_blocked_failed",
            extra={"tenant_id": tenant_id, "attempted_tenant_id": attempted_tenant_id},
            exc_info=True,
        )


def emit_token_generated(
    db: Session,
    tenant_id: str,
    user_id: str,
    dashboard_id: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.token.generated when an embed token is created."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ANALYTICS_TOKEN_GENERATED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            resource_id=dashboard_id,
            metadata={
                "dashboard_id": dashboard_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_token_generated_failed",
            extra={"tenant_id": tenant_id, "dashboard_id": dashboard_id},
            exc_info=True,
        )


def emit_token_refreshed(
    db: Session,
    tenant_id: str,
    user_id: str,
    dashboard_id: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit analytics.token.refreshed when an embed token is refreshed."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.ANALYTICS_TOKEN_REFRESHED,
            resource_type=_ANALYTICS_RESOURCE_TYPE,
            resource_id=dashboard_id,
            metadata={
                "dashboard_id": dashboard_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_token_refreshed_failed",
            extra={"tenant_id": tenant_id, "dashboard_id": dashboard_id},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Dataset sync lifecycle audit event emitters (Story 5.2.10)
# ---------------------------------------------------------------------------

_DATASET_SYNC_RESOURCE_TYPE = "dataset_sync"


def emit_dataset_sync_started(
    db: Session,
    dataset_name: str,
    version: str,
    *,
    tenant_scope: str = "system",
    correlation_id: str | None = None,
) -> None:
    """Emit dataset.sync.started when a dataset sync job begins."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_scope,
            action=AuditAction.DATASET_SYNC_STARTED,
            resource_type=_DATASET_SYNC_RESOURCE_TYPE,
            resource_id=dataset_name,
            metadata={
                "dataset_name": dataset_name,
                "version": version,
                "tenant_scope": tenant_scope,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="sync_job",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dataset_sync_started_failed",
            extra={"dataset_name": dataset_name, "version": version},
            exc_info=True,
        )


def emit_dataset_sync_completed(
    db: Session,
    dataset_name: str,
    version: str,
    duration_seconds: float,
    *,
    tenant_scope: str = "system",
    correlation_id: str | None = None,
) -> None:
    """Emit dataset.sync.completed when a dataset sync succeeds."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_scope,
            action=AuditAction.DATASET_SYNC_COMPLETED,
            resource_type=_DATASET_SYNC_RESOURCE_TYPE,
            resource_id=dataset_name,
            metadata={
                "dataset_name": dataset_name,
                "version": version,
                "duration_seconds": duration_seconds,
                "tenant_scope": tenant_scope,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="sync_job",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dataset_sync_completed_failed",
            extra={"dataset_name": dataset_name, "version": version},
            exc_info=True,
        )


def emit_dataset_sync_failed(
    db: Session,
    dataset_name: str,
    version: str,
    error: str,
    *,
    tenant_scope: str = "system",
    correlation_id: str | None = None,
) -> None:
    """Emit dataset.sync.failed when a dataset sync fails."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_scope,
            action=AuditAction.DATASET_SYNC_FAILED,
            resource_type=_DATASET_SYNC_RESOURCE_TYPE,
            resource_id=dataset_name,
            metadata={
                "dataset_name": dataset_name,
                "version": version,
                "error": error,
                "tenant_scope": tenant_scope,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="sync_job",
            outcome=AuditOutcome.FAILURE,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dataset_sync_failed_failed",
            extra={"dataset_name": dataset_name, "version": version},
            exc_info=True,
        )


def emit_dataset_version_activated(
    db: Session,
    dataset_name: str,
    version: str,
    *,
    tenant_scope: str = "system",
    correlation_id: str | None = None,
) -> None:
    """Emit dataset.version.activated when a new version is promoted to ACTIVE."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_scope,
            action=AuditAction.DATASET_VERSION_ACTIVATED,
            resource_type=_DATASET_SYNC_RESOURCE_TYPE,
            resource_id=dataset_name,
            metadata={
                "dataset_name": dataset_name,
                "version": version,
                "tenant_scope": tenant_scope,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="sync_job",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dataset_version_activated_failed",
            extra={"dataset_name": dataset_name, "version": version},
            exc_info=True,
        )


def emit_dataset_version_rolled_back(
    db: Session,
    dataset_name: str,
    rolled_back_version: str,
    restored_version: str,
    *,
    tenant_scope: str = "system",
    correlation_id: str | None = None,
) -> None:
    """Emit dataset.version.rolled_back when a version rollback occurs."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_scope,
            action=AuditAction.DATASET_VERSION_ROLLED_BACK,
            resource_type=_DATASET_SYNC_RESOURCE_TYPE,
            resource_id=dataset_name,
            metadata={
                "dataset_name": dataset_name,
                "rolled_back_version": rolled_back_version,
                "restored_version": restored_version,
                "tenant_scope": tenant_scope,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="sync_job",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_dataset_version_rolled_back_failed",
            extra={
                "dataset_name": dataset_name,
                "rolled_back_version": rolled_back_version,
            },
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Agency access audit event emitters (Story 5.5.2)
# ---------------------------------------------------------------------------

_AGENCY_ACCESS_RESOURCE_TYPE = "agency_access_request"


def emit_agency_access_requested(
    db: Session,
    tenant_id: str,
    requesting_user_id: str,
    request_id: str,
    requested_role_slug: str,
    requesting_org_id: str | None = None,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit agency_access.requested when an agency user requests access to a tenant."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.AGENCY_ACCESS_REQUESTED,
            resource_type=_AGENCY_ACCESS_RESOURCE_TYPE,
            resource_id=request_id,
            metadata={
                "request_id": request_id,
                "requesting_user_id": requesting_user_id,
                "tenant_id": tenant_id,
                "requested_role_slug": requested_role_slug,
                "requesting_org_id": requesting_org_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_agency_access_requested_failed",
            extra={"request_id": request_id, "tenant_id": tenant_id},
            exc_info=True,
        )


def emit_agency_access_approved(
    db: Session,
    tenant_id: str,
    request_id: str,
    requesting_user_id: str,
    reviewed_by: str,
    role_slug: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit agency_access.approved when a tenant admin approves a request."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.AGENCY_ACCESS_APPROVED,
            resource_type=_AGENCY_ACCESS_RESOURCE_TYPE,
            resource_id=request_id,
            metadata={
                "request_id": request_id,
                "requesting_user_id": requesting_user_id,
                "reviewed_by": reviewed_by,
                "role_slug": role_slug,
                "tenant_id": tenant_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_agency_access_approved_failed",
            extra={"request_id": request_id, "tenant_id": tenant_id},
            exc_info=True,
        )


def emit_agency_access_denied(
    db: Session,
    tenant_id: str,
    request_id: str,
    requesting_user_id: str,
    reviewed_by: str,
    review_note: str | None = None,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit agency_access.denied when a tenant admin denies a request."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.AGENCY_ACCESS_DENIED,
            resource_type=_AGENCY_ACCESS_RESOURCE_TYPE,
            resource_id=request_id,
            metadata={
                "request_id": request_id,
                "requesting_user_id": requesting_user_id,
                "reviewed_by": reviewed_by,
                "review_note": review_note or "",
                "tenant_id": tenant_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.DENIED,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_agency_access_denied_failed",
            extra={"request_id": request_id, "tenant_id": tenant_id},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# JWT refresh and tenant context audit event emitters (Story 5.5.3)
# ---------------------------------------------------------------------------


def emit_jwt_refresh(
    db: Session,
    tenant_id: str,
    user_id: str,
    previous_tenant_id: str | None = None,
    access_surface: str = "external_app",
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit auth.jwt_refresh when a JWT is refreshed for tenant switching."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.AUTH_JWT_REFRESH,
            resource_type="auth",
            metadata={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "previous_tenant_id": previous_tenant_id,
                "access_surface": access_surface,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_jwt_refresh_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )


def emit_tenant_context_switched(
    db: Session,
    tenant_id: str,
    user_id: str,
    previous_tenant_id: str | None = None,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit tenant.context_switched when a user switches active tenant."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.TENANT_CONTEXT_SWITCHED,
            resource_type="tenant",
            metadata={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "previous_tenant_id": previous_tenant_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_tenant_context_switched_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Grace-period revocation audit event emitters (Story 5.5.4)
# ---------------------------------------------------------------------------

_REVOCATION_RESOURCE_TYPE = "access_revocation"


def emit_agency_access_revoked(
    db: Session,
    tenant_id: str,
    user_id: str,
    revoked_by: str | None = None,
    expires_at: object | None = None,
    grace_period_hours: int = 24,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit agency_access.revoked when access revocation enters grace period."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.AGENCY_ACCESS_REVOKED,
            resource_type=_REVOCATION_RESOURCE_TYPE,
            metadata={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "revoked_by": revoked_by,
                "expires_at": expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at),
                "grace_period_hours": grace_period_hours,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_agency_access_revoked_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# RBAC enforcement audit event emitters (Story 5.5.5)
# ---------------------------------------------------------------------------

_RBAC_RESOURCE_TYPE = "rbac"


def emit_rbac_denied(
    db: Session,
    tenant_id: str,
    user_id: str,
    permission: str,
    endpoint: str,
    method: str = "",
    roles: list[str] | None = None,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit rbac.denied when a permission check blocks access to an endpoint."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id or "unknown",
            action=AuditAction.RBAC_DENIED,
            resource_type=_RBAC_RESOURCE_TYPE,
            metadata={
                "user_id": user_id or "unknown",
                "tenant_id": tenant_id or "unknown",
                "permission": permission,
                "endpoint": endpoint,
                "method": method,
                "roles": roles or [],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="api",
            outcome=AuditOutcome.DENIED,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_rbac_denied_failed",
            extra={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "permission": permission,
                "endpoint": endpoint,
            },
            exc_info=True,
        )


def emit_agency_access_expired(
    db: Session,
    tenant_id: str,
    user_id: str,
    revocation_id: str | None = None,
    *,
    correlation_id: str | None = None,
) -> None:
    """Emit agency_access.expired when grace period ends and access is enforced."""
    try:
        from src.platform.audit import (
            AuditAction,
            AuditOutcome,
            log_system_audit_event_sync,
        )

        log_system_audit_event_sync(
            db=db,
            tenant_id=tenant_id,
            action=AuditAction.AGENCY_ACCESS_EXPIRED,
            resource_type=_REVOCATION_RESOURCE_TYPE,
            resource_id=revocation_id,
            metadata={
                "user_id": user_id,
                "tenant_id": tenant_id,
                "revocation_id": revocation_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            correlation_id=correlation_id,
            source="worker",
            outcome=AuditOutcome.SUCCESS,
        )
    except Exception:
        logger.warning(
            "audit_logger.emit_agency_access_expired_failed",
            extra={"user_id": user_id, "tenant_id": tenant_id},
            exc_info=True,
        )
