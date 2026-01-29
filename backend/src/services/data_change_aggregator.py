"""
Data Change Aggregator service for Story 9.8.

Aggregates data from various sources into merchant-safe summaries
for the "What Changed?" debug panel.

SECURITY:
- Never exposes raw logs, credentials, or stack traces
- Aggregates into human-readable summaries
- tenant_id from JWT only
- Read-only operations
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, desc

from src.models.data_change_event import DataChangeEvent, DataChangeEventType
from src.models.dq_models import (
    SyncRun, SyncRunStatus, DQIncident, DQIncidentStatus,
    BackfillJob, BackfillJobStatus
)
from src.models.airbyte_connection import TenantAirbyteConnection, ConnectionStatus
from src.models.action_approval_audit import ActionApprovalAudit, AuditAction
from src.models.action_proposal import ActionProposal


logger = logging.getLogger(__name__)


# Metrics affected by different event types
SYNC_AFFECTED_METRICS = ["revenue", "orders", "sessions", "ad_spend"]
AI_ACTION_AFFECTED_METRICS = ["ad_spend", "roas", "cac"]


class DataChangeAggregator:
    """
    Service for aggregating data changes into merchant-safe events.

    Aggregates from:
    - SyncRun (sync completions, failures)
    - DQIncident (data quality events)
    - ActionApprovalAudit (AI action approvals/executions)
    - TenantAirbyteConnection (connector status changes)

    SECURITY:
    - Never exposes raw logs
    - Never exposes credentials
    - Aggregates into human-readable summaries
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize data change aggregator.

        Args:
            db_session: Database session
            tenant_id: Tenant identifier (from JWT)
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    # =========================================================================
    # Event Aggregation Methods (called by sync/action services)
    # =========================================================================

    def record_sync_completed(
        self,
        sync_run: SyncRun,
        connector_name: str,
    ) -> DataChangeEvent:
        """
        Record a sync completion event.

        Args:
            sync_run: The completed SyncRun
            connector_name: Human-readable connector name

        Returns:
            Created DataChangeEvent
        """
        rows_info = f"{sync_run.rows_synced:,} rows" if sync_run.rows_synced else "data"
        duration_info = f" in {sync_run.duration_seconds:.0f}s" if sync_run.duration_seconds else ""

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.SYNC_COMPLETED.value,
            title=f"{connector_name} sync completed",
            description=f"Successfully synced {rows_info}{duration_info}.",
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=sync_run.connector_id,
            affected_connector_name=connector_name,
            impact_summary=f"Data updated with {rows_info} from {connector_name}.",
            source_entity_type="sync_run",
            source_entity_id=sync_run.run_id,
            occurred_at=sync_run.completed_at or datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        logger.info(
            "Recorded sync completed event",
            extra={
                "tenant_id": self.tenant_id,
                "event_id": event.id,
                "connector_id": sync_run.connector_id,
            },
        )

        return event

    def record_sync_failed(
        self,
        sync_run: SyncRun,
        connector_name: str,
    ) -> DataChangeEvent:
        """
        Record a sync failure event.

        Args:
            sync_run: The failed SyncRun
            connector_name: Human-readable connector name

        Returns:
            Created DataChangeEvent
        """
        # Sanitize error message - remove sensitive details
        error_summary = self._sanitize_error_message(sync_run.error_message)

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.SYNC_FAILED.value,
            title=f"{connector_name} sync failed",
            description=f"Sync failed: {error_summary}",
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=sync_run.connector_id,
            affected_connector_name=connector_name,
            impact_summary=f"Data from {connector_name} may be stale until sync is restored.",
            source_entity_type="sync_run",
            source_entity_id=sync_run.run_id,
            occurred_at=sync_run.completed_at or datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        logger.info(
            "Recorded sync failed event",
            extra={
                "tenant_id": self.tenant_id,
                "event_id": event.id,
                "connector_id": sync_run.connector_id,
            },
        )

        return event

    def record_backfill_completed(
        self,
        backfill: BackfillJob,
        connector_name: str,
    ) -> DataChangeEvent:
        """
        Record a backfill completion event.

        Args:
            backfill: The completed BackfillJob
            connector_name: Human-readable connector name

        Returns:
            Created DataChangeEvent
        """
        rows_info = f"{backfill.rows_backfilled:,} rows" if backfill.rows_backfilled else "data"

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.BACKFILL_COMPLETED.value,
            title=f"{connector_name} backfill completed",
            description=f"Historical data backfill completed with {rows_info}.",
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=backfill.connector_id,
            affected_connector_name=connector_name,
            impact_summary=f"Historical data from {connector_name} has been updated.",
            affected_date_start=backfill.start_date,
            affected_date_end=backfill.end_date,
            source_entity_type="backfill_job",
            source_entity_id=backfill.id,
            occurred_at=backfill.completed_at or datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        return event

    def record_ai_action_approved(
        self,
        audit: ActionApprovalAudit,
        action_type: str,
        target_name: str,
    ) -> DataChangeEvent:
        """
        Record an AI action approval event.

        Args:
            audit: The ActionApprovalAudit record
            action_type: Type of action (e.g., "pause_ad")
            target_name: Sanitized target name

        Returns:
            Created DataChangeEvent
        """
        performed_by = "Admin user" if audit.performed_by_user_id else "System"

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.AI_ACTION_APPROVED.value,
            title=f"AI action approved: {action_type}",
            description=f"{performed_by} approved {action_type} for {target_name}.",
            affected_metrics=AI_ACTION_AFFECTED_METRICS,
            impact_summary=f"Action will be executed, which may affect metrics.",
            source_entity_type="action_approval_audit",
            source_entity_id=audit.id,
            occurred_at=audit.performed_at,
        )

        self.db.add(event)
        self.db.flush()

        return event

    def record_ai_action_executed(
        self,
        action_proposal: ActionProposal,
        action_type: str,
        target_name: str,
    ) -> DataChangeEvent:
        """
        Record an AI action execution event.

        Args:
            action_proposal: The executed ActionProposal
            action_type: Type of action
            target_name: Sanitized target name

        Returns:
            Created DataChangeEvent
        """
        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.AI_ACTION_EXECUTED.value,
            title=f"AI action executed: {action_type}",
            description=f"Executed {action_type} for {target_name}.",
            affected_metrics=AI_ACTION_AFFECTED_METRICS,
            impact_summary=f"This action may cause changes in ad performance metrics.",
            source_entity_type="action_proposal",
            source_entity_id=action_proposal.id,
            occurred_at=datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        return event

    def record_ai_action_rejected(
        self,
        audit: ActionApprovalAudit,
        action_type: str,
        target_name: str,
        reason: Optional[str] = None,
    ) -> DataChangeEvent:
        """
        Record an AI action rejection event.

        Args:
            audit: The ActionApprovalAudit record
            action_type: Type of action
            target_name: Sanitized target name
            reason: Optional rejection reason

        Returns:
            Created DataChangeEvent
        """
        performed_by = "Admin user" if audit.performed_by_user_id else "System"
        reason_text = f" Reason: {reason}" if reason else ""

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.AI_ACTION_REJECTED.value,
            title=f"AI action rejected: {action_type}",
            description=f"{performed_by} rejected {action_type} for {target_name}.{reason_text}",
            affected_metrics=[],  # No metrics affected since action wasn't executed
            impact_summary="No changes were made.",
            source_entity_type="action_approval_audit",
            source_entity_id=audit.id,
            occurred_at=audit.performed_at,
        )

        self.db.add(event)
        self.db.flush()

        return event

    def record_connector_status_changed(
        self,
        connector: TenantAirbyteConnection,
        previous_status: ConnectionStatus,
        reason: Optional[str] = None,
    ) -> DataChangeEvent:
        """
        Record a connector status change event.

        Args:
            connector: The TenantAirbyteConnection
            previous_status: Previous connection status
            reason: Optional reason for the change

        Returns:
            Created DataChangeEvent
        """
        reason_text = f" ({reason})" if reason else ""

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.CONNECTOR_STATUS_CHANGED.value,
            title=f"{connector.connection_name} status changed",
            description=(
                f"Status changed from {previous_status.value} to {connector.status.value}"
                f"{reason_text}."
            ),
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=connector.id,
            affected_connector_name=connector.connection_name,
            impact_summary=self._get_status_change_impact(previous_status, connector.status),
            source_entity_type="tenant_airbyte_connection",
            source_entity_id=connector.id,
            occurred_at=datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        return event

    def record_dq_incident_opened(
        self,
        incident: DQIncident,
        connector_name: str,
    ) -> DataChangeEvent:
        """
        Record a data quality incident event.

        Args:
            incident: The DQIncident
            connector_name: Human-readable connector name

        Returns:
            Created DataChangeEvent
        """
        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.DATA_QUALITY_INCIDENT.value,
            title=f"Data quality issue: {incident.title}",
            description=incident.merchant_message or incident.description or "A data quality issue was detected.",
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=incident.connector_id,
            affected_connector_name=connector_name,
            impact_summary=f"Data accuracy may be affected. Severity: {incident.severity}",
            source_entity_type="dq_incident",
            source_entity_id=incident.id,
            occurred_at=incident.opened_at,
        )

        self.db.add(event)
        self.db.flush()

        return event

    def record_dq_incident_resolved(
        self,
        incident: DQIncident,
        connector_name: str,
    ) -> DataChangeEvent:
        """
        Record a data quality incident resolution event.

        Args:
            incident: The resolved DQIncident
            connector_name: Human-readable connector name

        Returns:
            Created DataChangeEvent
        """
        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.DATA_QUALITY_RESOLVED.value,
            title=f"Data quality issue resolved: {incident.title}",
            description=incident.resolution_notes or "The data quality issue has been resolved.",
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=incident.connector_id,
            affected_connector_name=connector_name,
            impact_summary="Data quality has been restored.",
            source_entity_type="dq_incident",
            source_entity_id=incident.id,
            occurred_at=incident.resolved_at or datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        return event

    # =========================================================================
    # Query Methods (for the debug panel API)
    # =========================================================================

    def get_change_events(
        self,
        event_type: Optional[str] = None,
        connector_id: Optional[str] = None,
        metric: Optional[str] = None,
        days: int = 7,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[DataChangeEvent], int]:
        """
        Get recent change events with filtering.

        Args:
            event_type: Filter by event type (optional)
            connector_id: Filter by connector (optional)
            metric: Filter by affected metric (optional)
            days: Number of days to look back
            limit: Maximum results
            offset: Pagination offset

        Returns:
            Tuple of (events, total_count)
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        query = self.db.query(DataChangeEvent).filter(
            DataChangeEvent.tenant_id == self.tenant_id,
            DataChangeEvent.occurred_at >= since,
        )

        if event_type:
            query = query.filter(DataChangeEvent.event_type == event_type)

        if connector_id:
            query = query.filter(DataChangeEvent.affected_connector_id == connector_id)

        if metric:
            query = query.filter(DataChangeEvent.affected_metrics.contains([metric]))

        total = query.count()

        events = (
            query
            .order_by(DataChangeEvent.occurred_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return events, total

    def get_freshness_status(self) -> dict:
        """
        Get overall data freshness status.

        Returns:
            Dict with freshness information
        """
        # Get all active connectors
        connectors = (
            self.db.query(TenantAirbyteConnection)
            .filter(
                TenantAirbyteConnection.tenant_id == self.tenant_id,
                TenantAirbyteConnection.is_enabled == True,
                TenantAirbyteConnection.status.in_([
                    ConnectionStatus.ACTIVE,
                    ConnectionStatus.PENDING,
                ]),
            )
            .all()
        )

        now = datetime.now(timezone.utc)
        connector_statuses = []
        overall_status = "fresh"
        last_sync_at = None

        for connector in connectors:
            minutes_since = None
            status = "fresh"

            if connector.last_sync_at:
                if last_sync_at is None or connector.last_sync_at > last_sync_at:
                    last_sync_at = connector.last_sync_at

                delta = now - connector.last_sync_at
                minutes_since = int(delta.total_seconds() / 60)

                # Determine freshness based on source type
                if minutes_since > 1440:  # > 24 hours
                    status = "critical"
                    overall_status = "critical"
                elif minutes_since > 120:  # > 2 hours
                    status = "stale"
                    if overall_status != "critical":
                        overall_status = "stale"
            else:
                status = "unknown"

            if connector.status == ConnectionStatus.FAILED:
                status = "error"
                overall_status = "critical"

            connector_statuses.append({
                "connector_id": connector.id,
                "connector_name": connector.connection_name,
                "status": status,
                "last_sync_at": connector.last_sync_at,
                "minutes_since_sync": minutes_since,
                "source_type": connector.source_type,
            })

        hours_since = None
        if last_sync_at:
            delta = now - last_sync_at
            hours_since = int(delta.total_seconds() / 3600)

        return {
            "overall_status": overall_status,
            "last_sync_at": last_sync_at,
            "hours_since_sync": hours_since,
            "connectors": connector_statuses,
        }

    def get_recent_syncs(self, days: int = 7, limit: int = 20) -> List[dict]:
        """
        Get recent sync activity.

        Args:
            days: Number of days to look back
            limit: Maximum results

        Returns:
            List of recent sync information
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        syncs = (
            self.db.query(SyncRun)
            .filter(
                SyncRun.tenant_id == self.tenant_id,
                SyncRun.started_at >= since,
            )
            .order_by(SyncRun.started_at.desc())
            .limit(limit)
            .all()
        )

        # Get connector names
        connector_ids = list(set(s.connector_id for s in syncs))
        connectors = {}
        if connector_ids:
            for conn in self.db.query(TenantAirbyteConnection).filter(
                TenantAirbyteConnection.id.in_(connector_ids)
            ).all():
                connectors[conn.id] = conn.connection_name

        result = []
        for sync in syncs:
            result.append({
                "sync_id": sync.run_id,
                "connector_id": sync.connector_id,
                "connector_name": connectors.get(sync.connector_id, "Unknown"),
                "source_type": sync.source_type,
                "status": sync.status,
                "started_at": sync.started_at,
                "completed_at": sync.completed_at,
                "rows_synced": sync.rows_synced,
                "duration_seconds": float(sync.duration_seconds) if sync.duration_seconds else None,
                "error_message": self._sanitize_error_message(sync.error_message),
            })

        return result

    def get_ai_actions_summary(self, days: int = 7, limit: int = 20) -> List[dict]:
        """
        Get recent AI action activity.

        Args:
            days: Number of days to look back
            limit: Maximum results

        Returns:
            List of AI action summaries
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        audits = (
            self.db.query(ActionApprovalAudit)
            .filter(
                ActionApprovalAudit.tenant_id == self.tenant_id,
                ActionApprovalAudit.performed_at >= since,
                ActionApprovalAudit.action.in_([
                    AuditAction.APPROVED,
                    AuditAction.REJECTED,
                ]),
            )
            .order_by(ActionApprovalAudit.performed_at.desc())
            .limit(limit)
            .all()
        )

        # Get proposal details
        proposal_ids = list(set(a.action_proposal_id for a in audits))
        proposals = {}
        if proposal_ids:
            for prop in self.db.query(ActionProposal).filter(
                ActionProposal.id.in_(proposal_ids)
            ).all():
                proposals[prop.id] = prop

        result = []
        for audit in audits:
            proposal = proposals.get(audit.action_proposal_id)
            action_type = proposal.action_type if proposal else "unknown"
            target_name = self._sanitize_target_name(
                proposal.target_entity_name if proposal else "Unknown"
            )

            result.append({
                "action_id": audit.action_proposal_id,
                "action_type": action_type,
                "status": audit.action.value,
                "target_name": target_name,
                "target_platform": proposal.target_platform if proposal else None,
                "performed_at": audit.performed_at,
                "performed_by": "Admin user" if audit.performed_by_user_id else "System",
            })

        return result

    def get_connector_status_changes(self, days: int = 7) -> List[dict]:
        """
        Get recent connector status changes from events.

        Args:
            days: Number of days to look back

        Returns:
            List of connector status changes
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        events = (
            self.db.query(DataChangeEvent)
            .filter(
                DataChangeEvent.tenant_id == self.tenant_id,
                DataChangeEvent.event_type == DataChangeEventType.CONNECTOR_STATUS_CHANGED.value,
                DataChangeEvent.occurred_at >= since,
            )
            .order_by(DataChangeEvent.occurred_at.desc())
            .all()
        )

        result = []
        for event in events:
            # Parse status change from description
            desc = event.description
            prev_status = "unknown"
            new_status = "unknown"

            if "from" in desc and "to" in desc:
                try:
                    parts = desc.split("from")[1].split("to")
                    prev_status = parts[0].strip()
                    new_status = parts[1].split(".")[0].strip()
                except (IndexError, AttributeError):
                    pass

            result.append({
                "connector_id": event.affected_connector_id,
                "connector_name": event.affected_connector_name,
                "previous_status": prev_status,
                "new_status": new_status,
                "changed_at": event.occurred_at,
                "reason": event.impact_summary,
            })

        return result

    def get_summary(self, days: int = 7) -> dict:
        """
        Get summary for the debug panel header.

        Args:
            days: Number of days to look back

        Returns:
            Summary dict with counts and freshness
        """
        since = datetime.now(timezone.utc) - timedelta(days=days)

        # Get freshness status
        freshness = self.get_freshness_status()

        # Count recent syncs
        syncs_count = (
            self.db.query(func.count(SyncRun.run_id))
            .filter(
                SyncRun.tenant_id == self.tenant_id,
                SyncRun.started_at >= since,
            )
            .scalar()
        ) or 0

        # Count recent AI actions
        ai_actions_count = (
            self.db.query(func.count(ActionApprovalAudit.id))
            .filter(
                ActionApprovalAudit.tenant_id == self.tenant_id,
                ActionApprovalAudit.performed_at >= since,
                ActionApprovalAudit.action.in_([
                    AuditAction.APPROVED,
                    AuditAction.REJECTED,
                ]),
            )
            .scalar()
        ) or 0

        # Count open incidents
        open_incidents_count = (
            self.db.query(func.count(DQIncident.id))
            .filter(
                DQIncident.tenant_id == self.tenant_id,
                DQIncident.status.in_([
                    DQIncidentStatus.OPEN.value,
                    DQIncidentStatus.ACKNOWLEDGED.value,
                ]),
            )
            .scalar()
        ) or 0

        # Count metric-affecting change events
        metric_changes_count = (
            self.db.query(func.count(DataChangeEvent.id))
            .filter(
                DataChangeEvent.tenant_id == self.tenant_id,
                DataChangeEvent.occurred_at >= since,
                DataChangeEvent.event_type.in_([
                    DataChangeEventType.SYNC_COMPLETED.value,
                    DataChangeEventType.BACKFILL_COMPLETED.value,
                    DataChangeEventType.AI_ACTION_EXECUTED.value,
                ]),
            )
            .scalar()
        ) or 0

        return {
            "data_freshness": freshness,
            "recent_syncs_count": syncs_count,
            "recent_ai_actions_count": ai_actions_count,
            "open_incidents_count": open_incidents_count,
            "metric_changes_count": metric_changes_count,
            "last_updated": datetime.now(timezone.utc),
        }

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _sanitize_error_message(self, message: Optional[str]) -> Optional[str]:
        """
        Sanitize error message to remove sensitive data.

        Args:
            message: Raw error message

        Returns:
            Sanitized message safe for display
        """
        if not message:
            return None

        # List of patterns to redact
        sensitive_patterns = [
            # API keys and tokens
            (r'api[_-]?key["\']?\s*[:=]\s*["\']?[\w-]+', 'api_key=***'),
            (r'token["\']?\s*[:=]\s*["\']?[\w.-]+', 'token=***'),
            (r'bearer\s+[\w.-]+', 'Bearer ***'),
            (r'authorization["\']?\s*[:=]\s*["\']?[\w.-]+', 'authorization=***'),
            # Passwords
            (r'password["\']?\s*[:=]\s*["\']?[^\s"\']+', 'password=***'),
            # Connection strings
            (r'postgresql://[^\s]+', 'postgresql://***'),
            (r'mysql://[^\s]+', 'mysql://***'),
            (r'mongodb://[^\s]+', 'mongodb://***'),
            # File paths
            (r'/home/[^\s]+', '/***'),
            (r'/var/[^\s]+', '/***'),
            (r'/etc/[^\s]+', '/***'),
            # IP addresses (internal)
            (r'10\.\d+\.\d+\.\d+', '***'),
            (r'172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+', '***'),
            (r'192\.168\.\d+\.\d+', '***'),
            # Email addresses
            (r'[\w.-]+@[\w.-]+\.\w+', '***@***.***'),
        ]

        import re
        sanitized = message
        for pattern, replacement in sensitive_patterns:
            sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

        # Truncate if too long
        if len(sanitized) > 500:
            sanitized = sanitized[:497] + "..."

        return sanitized

    def _sanitize_target_name(self, target_name: Optional[str]) -> str:
        """
        Sanitize target name for display.

        Args:
            target_name: Raw target name

        Returns:
            Sanitized name
        """
        if not target_name:
            return "Unknown target"

        # Remove any potential sensitive data patterns
        import re
        sanitized = re.sub(r'[\w.-]+@[\w.-]+\.\w+', '***', target_name)
        sanitized = re.sub(r'\b\d{10,}\b', '***', sanitized)  # Long numbers

        return sanitized

    def _get_status_change_impact(
        self,
        previous: ConnectionStatus,
        current: ConnectionStatus,
    ) -> str:
        """
        Get impact description for status change.

        Args:
            previous: Previous status
            current: Current status

        Returns:
            Impact description
        """
        if current == ConnectionStatus.ACTIVE:
            return "Data syncing has resumed normally."
        elif current == ConnectionStatus.FAILED:
            return "Data may become stale until the issue is resolved."
        elif current == ConnectionStatus.INACTIVE:
            return "Syncing is paused. Data will not be updated."
        elif current == ConnectionStatus.DELETED:
            return "Connector has been removed. Historical data is preserved."
        else:
            return "Connection status has changed."

    # =========================================================================
    # Simplified Recording Methods (for services without SyncRun objects)
    # =========================================================================

    def record_sync_completed_simple(
        self,
        connection_id: str,
        connector_name: str,
        rows_synced: Optional[int] = None,
        duration_seconds: Optional[float] = None,
        job_id: Optional[str] = None,
    ) -> DataChangeEvent:
        """
        Record a sync completion event without a SyncRun object.

        Used by the sync orchestrator when SyncRun tracking is not enabled.

        Args:
            connection_id: Internal connection ID
            connector_name: Human-readable connector name
            rows_synced: Number of rows synced (optional)
            duration_seconds: Duration in seconds (optional)
            job_id: External job ID (optional)

        Returns:
            Created DataChangeEvent
        """
        rows_info = f"{rows_synced:,} rows" if rows_synced else "data"
        duration_info = f" in {duration_seconds:.0f}s" if duration_seconds else ""

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.SYNC_COMPLETED.value,
            title=f"{connector_name} sync completed",
            description=f"Successfully synced {rows_info}{duration_info}.",
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=connection_id,
            affected_connector_name=connector_name,
            impact_summary=f"Data updated with {rows_info} from {connector_name}.",
            source_entity_type="sync_job",
            source_entity_id=job_id,
            occurred_at=datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        logger.info(
            "Recorded sync completed event (simple)",
            extra={
                "tenant_id": self.tenant_id,
                "event_id": event.id,
                "connector_id": connection_id,
                "rows_synced": rows_synced,
            },
        )

        return event

    def record_sync_failed_simple(
        self,
        connection_id: str,
        connector_name: str,
        error_message: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> DataChangeEvent:
        """
        Record a sync failure event without a SyncRun object.

        Used by the sync orchestrator when SyncRun tracking is not enabled.

        Args:
            connection_id: Internal connection ID
            connector_name: Human-readable connector name
            error_message: Error message (will be sanitized)
            job_id: External job ID (optional)

        Returns:
            Created DataChangeEvent
        """
        error_summary = self._sanitize_error_message(error_message) or "Unknown error"

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.SYNC_FAILED.value,
            title=f"{connector_name} sync failed",
            description=f"Sync failed: {error_summary}",
            affected_metrics=SYNC_AFFECTED_METRICS,
            affected_connector_id=connection_id,
            affected_connector_name=connector_name,
            impact_summary=f"Data from {connector_name} may be stale until sync is restored.",
            source_entity_type="sync_job",
            source_entity_id=job_id,
            occurred_at=datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        logger.info(
            "Recorded sync failed event (simple)",
            extra={
                "tenant_id": self.tenant_id,
                "event_id": event.id,
                "connector_id": connection_id,
            },
        )

        return event

    def record_ai_action_executed_simple(
        self,
        action_id: str,
        action_type: str,
        target_name: str,
        platform: Optional[str] = None,
        before_state: Optional[dict] = None,
        after_state: Optional[dict] = None,
    ) -> DataChangeEvent:
        """
        Record an AI action execution event without an ActionProposal object.

        Used by the action execution service.

        Args:
            action_id: Action ID
            action_type: Type of action (e.g., "pause_campaign")
            target_name: Target entity name (will be sanitized)
            platform: Target platform (optional)
            before_state: State before execution (optional)
            after_state: State after execution (optional)

        Returns:
            Created DataChangeEvent
        """
        sanitized_target = self._sanitize_target_name(target_name)
        platform_info = f" on {platform}" if platform else ""

        # Generate a simple change summary if states are provided
        impact = "This action may cause changes in ad performance metrics."
        if before_state and after_state:
            changes = self._compute_state_diff(before_state, after_state)
            if changes:
                impact = f"Changed: {changes}. Metrics may be affected."

        event = DataChangeEvent(
            tenant_id=self.tenant_id,
            event_type=DataChangeEventType.AI_ACTION_EXECUTED.value,
            title=f"AI action executed: {action_type}",
            description=f"Executed {action_type} for {sanitized_target}{platform_info}.",
            affected_metrics=AI_ACTION_AFFECTED_METRICS,
            impact_summary=impact,
            source_entity_type="ai_action",
            source_entity_id=action_id,
            occurred_at=datetime.now(timezone.utc),
        )

        self.db.add(event)
        self.db.flush()

        logger.info(
            "Recorded AI action executed event (simple)",
            extra={
                "tenant_id": self.tenant_id,
                "event_id": event.id,
                "action_id": action_id,
                "action_type": action_type,
            },
        )

        return event

    def _compute_state_diff(
        self,
        before: dict,
        after: dict,
    ) -> Optional[str]:
        """
        Compute a human-readable diff between before and after states.

        Args:
            before: State before change
            after: State after change

        Returns:
            Human-readable diff string, or None if no changes
        """
        changes = []

        # Only compare top-level keys for simplicity
        all_keys = set(before.keys()) | set(after.keys())

        for key in all_keys:
            before_val = before.get(key)
            after_val = after.get(key)

            if before_val != after_val:
                # Format the key for display
                display_key = key.replace("_", " ").title()

                if before_val is None:
                    changes.append(f"{display_key} set to {after_val}")
                elif after_val is None:
                    changes.append(f"{display_key} removed")
                else:
                    changes.append(f"{display_key}: {before_val} -> {after_val}")

        if not changes:
            return None

        # Limit to first 3 changes for brevity
        if len(changes) > 3:
            return ", ".join(changes[:3]) + f" (+{len(changes) - 3} more)"

        return ", ".join(changes)
