"""
Data freshness service for AI and dashboard consumers.

Bridges the existing DataHealthService infrastructure to provide:
1. Per-tenant, per-source freshness tracking (via TenantAirbyteConnection.last_sync_at)
2. Dashboard-ready freshness summaries
3. AI staleness gate — blocks AI jobs when underlying data is stale

SECURITY: All operations are tenant-scoped via tenant_id from JWT.

Usage:
    from src.services.freshness_service import FreshnessService

    # Dashboard usage
    service = FreshnessService(db_session=session, tenant_id=tenant_id)
    summary = service.get_freshness_summary()

    # AI gate (static convenience)
    gate = FreshnessService.check_ai_freshness_gate(
        db_session=session, tenant_id=tenant_id,
    )
    if not gate.is_allowed:
        skip_ai_job(reason=gate.reason)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ─── Thresholds ──────────────────────────────────────────────────────────────
# Re-export canonical thresholds from DataHealthService so consumers only
# import from one place.
DEFAULT_FRESHNESS_THRESHOLD_MINUTES = 120   # 2 hours — STALE boundary
DEFAULT_CRITICAL_THRESHOLD_MINUTES = 1440   # 24 hours — CRITICAL boundary
AI_STALENESS_BLOCK_THRESHOLD_MINUTES = 1440  # AI blocked when ANY source ≥ 24 h


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SourceFreshness:
    """Freshness snapshot for a single data source."""

    connection_id: str
    connection_name: str
    source_type: Optional[str]
    last_sync_at: Optional[datetime]
    last_sync_status: Optional[str]
    sync_frequency_minutes: int
    minutes_since_sync: Optional[int]
    freshness_status: str          # FreshnessStatus.value
    is_stale: bool
    is_healthy: bool
    warning_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "connection_id": self.connection_id,
            "connection_name": self.connection_name,
            "source_type": self.source_type,
            "last_sync_at": (
                self.last_sync_at.isoformat() if self.last_sync_at else None
            ),
            "last_sync_status": self.last_sync_status,
            "sync_frequency_minutes": self.sync_frequency_minutes,
            "minutes_since_sync": self.minutes_since_sync,
            "freshness_status": self.freshness_status,
            "is_stale": self.is_stale,
            "is_healthy": self.is_healthy,
            "warning_message": self.warning_message,
        }


@dataclass
class FreshnessSummary:
    """Aggregate freshness summary surfaced to dashboards."""

    tenant_id: str
    total_sources: int
    fresh_sources: int
    stale_sources: int
    critical_sources: int
    never_synced_sources: int
    overall_freshness_score: float   # 0–100
    has_stale_data: bool
    sources: List[SourceFreshness] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tenant_id": self.tenant_id,
            "total_sources": self.total_sources,
            "fresh_sources": self.fresh_sources,
            "stale_sources": self.stale_sources,
            "critical_sources": self.critical_sources,
            "never_synced_sources": self.never_synced_sources,
            "overall_freshness_score": self.overall_freshness_score,
            "has_stale_data": self.has_stale_data,
            "sources": [s.to_dict() for s in self.sources],
        }


@dataclass
class FreshnessGateResult:
    """Result of a freshness gate check for AI jobs."""

    is_allowed: bool
    reason: Optional[str] = None
    stale_sources: List[str] = field(default_factory=list)
    freshness_score: float = 100.0

    def to_dict(self) -> dict:
        return {
            "is_allowed": self.is_allowed,
            "reason": self.reason,
            "stale_sources": self.stale_sources,
            "freshness_score": self.freshness_score,
        }


# ─── Service ──────────────────────────────────────────────────────────────────

class FreshnessService:
    """
    Unified freshness layer consumed by dashboards and AI job runners.

    Delegates low-level freshness calculations to DataHealthService and
    adds the AI staleness gate on top.

    SECURITY: tenant_id must come from JWT (org_id), never client input.
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        ai_block_threshold_minutes: int = AI_STALENESS_BLOCK_THRESHOLD_MINUTES,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self.ai_block_threshold_minutes = ai_block_threshold_minutes

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_connections(self):
        """Return enabled TenantAirbyteConnections for this tenant."""
        from src.models.airbyte_connection import (
            TenantAirbyteConnection,
            ConnectionStatus,
        )

        stmt = (
            select(TenantAirbyteConnection)
            .where(TenantAirbyteConnection.tenant_id == self.tenant_id)
            .where(TenantAirbyteConnection.is_enabled.is_(True))
            .where(
                TenantAirbyteConnection.status.notin_([
                    ConnectionStatus.DELETED,
                ])
            )
        )
        return self.db.execute(stmt).scalars().all()

    @staticmethod
    def _parse_sync_frequency(raw: Optional[str]) -> int:
        if not raw:
            return 60
        try:
            return int(raw)
        except (ValueError, TypeError):
            return 60

    @staticmethod
    def _minutes_since(ts: Optional[datetime]) -> Optional[int]:
        if ts is None:
            return None
        now = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return int((now - ts).total_seconds() / 60)

    def _classify_freshness(
        self,
        last_sync_at: Optional[datetime],
        sync_freq_minutes: int,
    ) -> str:
        """Return a FreshnessStatus value string."""
        from src.services.data_health_service import FreshnessStatus

        if last_sync_at is None:
            return FreshnessStatus.NEVER_SYNCED.value

        minutes = self._minutes_since(last_sync_at)
        if minutes is None:
            return FreshnessStatus.UNKNOWN.value

        effective_threshold = max(
            sync_freq_minutes, DEFAULT_FRESHNESS_THRESHOLD_MINUTES
        )

        if minutes <= effective_threshold:
            return FreshnessStatus.FRESH.value
        elif minutes <= DEFAULT_CRITICAL_THRESHOLD_MINUTES:
            return FreshnessStatus.STALE.value
        else:
            return FreshnessStatus.CRITICAL.value

    def _build_source_freshness(self, conn) -> SourceFreshness:
        freq = self._parse_sync_frequency(conn.sync_frequency_minutes)
        status = self._classify_freshness(conn.last_sync_at, freq)
        minutes = self._minutes_since(conn.last_sync_at)

        is_stale = status in ("stale", "critical", "never_synced")
        conn_status = getattr(
            getattr(conn, "status", None), "value", str(conn.status)
        )
        is_healthy = (
            status == "fresh"
            and conn.is_enabled
            and conn_status == "active"
            and conn.last_sync_status != "failed"
        )

        warning = None
        if status == "never_synced":
            warning = "Data source has never been synced"
        elif status == "critical":
            hours = (minutes or 0) // 60
            warning = f"Data is critically stale: last synced {hours} hours ago"
        elif status == "stale":
            hours = (minutes or 0) // 60
            warning = f"Data is stale: last synced {hours} hours ago"

        return SourceFreshness(
            connection_id=conn.id,
            connection_name=conn.connection_name,
            source_type=conn.source_type,
            last_sync_at=conn.last_sync_at,
            last_sync_status=conn.last_sync_status,
            sync_frequency_minutes=freq,
            minutes_since_sync=minutes,
            freshness_status=status,
            is_stale=is_stale,
            is_healthy=is_healthy,
            warning_message=warning,
        )

    # ── Public: per-source freshness ──────────────────────────────────────

    def get_source_freshness(self, source_type: str) -> List[SourceFreshness]:
        """
        Get freshness info for all connections of a given source type.

        Args:
            source_type: e.g. "shopify", "meta", "google"

        Returns:
            List of SourceFreshness entries (may be empty)
        """
        connections = self._get_connections()
        return [
            self._build_source_freshness(c)
            for c in connections
            if c.source_type == source_type
        ]

    def get_all_source_freshness(self) -> List[SourceFreshness]:
        """Get freshness for every enabled source."""
        connections = self._get_connections()
        return [self._build_source_freshness(c) for c in connections]

    # ── Public: dashboard summary ─────────────────────────────────────────

    def get_freshness_summary(self) -> FreshnessSummary:
        """
        Build an aggregate freshness summary for the dashboard.

        Returns:
            FreshnessSummary with per-source detail and aggregate score.
        """
        sources = self.get_all_source_freshness()
        total = len(sources)
        fresh = sum(1 for s in sources if s.freshness_status == "fresh")
        stale = sum(1 for s in sources if s.freshness_status == "stale")
        critical = sum(1 for s in sources if s.freshness_status == "critical")
        never = sum(1 for s in sources if s.freshness_status == "never_synced")

        if total == 0:
            score = 100.0
        else:
            score_sum = sum(
                100 if s.freshness_status == "fresh"
                else 50 if s.freshness_status == "stale"
                else 25 if s.freshness_status == "never_synced"
                else 0
                for s in sources
            )
            score = round(score_sum / total, 1)

        has_stale = stale > 0 or critical > 0 or never > 0

        logger.info(
            "Freshness summary generated",
            extra={
                "tenant_id": self.tenant_id,
                "total": total,
                "fresh": fresh,
                "stale": stale,
                "critical": critical,
                "score": score,
            },
        )

        return FreshnessSummary(
            tenant_id=self.tenant_id,
            total_sources=total,
            fresh_sources=fresh,
            stale_sources=stale,
            critical_sources=critical,
            never_synced_sources=never,
            overall_freshness_score=score,
            has_stale_data=has_stale,
            sources=sources,
        )

    # ── Public: AI freshness gate ─────────────────────────────────────────

    def check_freshness_gate(
        self,
        required_sources: Optional[List[str]] = None,
    ) -> FreshnessGateResult:
        """
        Check whether tenant data is fresh enough for AI processing.

        Rules:
        - If no enabled sources exist, block (no data to analyse).
        - If *any* required source is CRITICAL (≥ 24h stale) or NEVER_SYNCED,
          block AI usage.
        - If required_sources is None, ALL enabled sources are checked.

        Args:
            required_sources: Optional list of source_types to check.
                              If None, checks all enabled sources.

        Returns:
            FreshnessGateResult indicating allow / block.
        """
        all_sources = self.get_all_source_freshness()

        if not all_sources:
            return FreshnessGateResult(
                is_allowed=False,
                reason="No enabled data sources found for tenant",
                freshness_score=0.0,
            )

        # Filter to required sources if specified
        if required_sources:
            sources = [
                s for s in all_sources if s.source_type in required_sources
            ]
            # If none of the required sources exist, block
            if not sources:
                return FreshnessGateResult(
                    is_allowed=False,
                    reason=(
                        f"Required sources not found: "
                        f"{', '.join(required_sources)}"
                    ),
                    freshness_score=0.0,
                )
        else:
            sources = all_sources

        # Identify sources that breach the AI block threshold
        blocked_sources = []
        for src in sources:
            if src.freshness_status == "never_synced":
                blocked_sources.append(
                    f"{src.source_type or src.connection_id} (never synced)"
                )
            elif src.freshness_status == "critical":
                blocked_sources.append(
                    f"{src.source_type or src.connection_id} "
                    f"({src.minutes_since_sync}min stale)"
                )
            elif (
                src.minutes_since_sync is not None
                and src.minutes_since_sync >= self.ai_block_threshold_minutes
            ):
                blocked_sources.append(
                    f"{src.source_type or src.connection_id} "
                    f"({src.minutes_since_sync}min stale)"
                )

        # Calculate score across checked sources
        total = len(sources)
        fresh_count = sum(
            1 for s in sources if s.freshness_status == "fresh"
        )
        score = round((fresh_count / total) * 100, 1) if total > 0 else 0.0

        if blocked_sources:
            self._log_ai_gate_blocked(blocked_sources)
            return FreshnessGateResult(
                is_allowed=False,
                reason=(
                    f"Data too stale for AI processing: "
                    f"{', '.join(blocked_sources)}"
                ),
                stale_sources=blocked_sources,
                freshness_score=score,
            )

        return FreshnessGateResult(
            is_allowed=True,
            freshness_score=score,
        )

    # ── Public: record sync ───────────────────────────────────────────────

    def record_successful_sync(
        self,
        connection_id: str,
        synced_at: Optional[datetime] = None,
    ) -> bool:
        """
        Record a successful sync for a connection.

        Updates TenantAirbyteConnection.last_sync_at and last_sync_status.
        Called by sync_executor after a successful ingestion run.

        Args:
            connection_id: Internal connection ID
            synced_at: Timestamp of sync completion (defaults to now)

        Returns:
            True if the connection was found and updated, False otherwise.
        """
        from src.models.airbyte_connection import TenantAirbyteConnection

        if synced_at is None:
            synced_at = datetime.now(timezone.utc)

        stmt = (
            update(TenantAirbyteConnection)
            .where(TenantAirbyteConnection.id == connection_id)
            .where(TenantAirbyteConnection.tenant_id == self.tenant_id)
            .values(
                last_sync_at=synced_at,
                last_sync_status="success",
            )
        )
        result = self.db.execute(stmt)
        self.db.flush()

        updated = result.rowcount > 0

        if updated:
            logger.info(
                "Recorded successful sync",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                    "synced_at": synced_at.isoformat(),
                },
            )
        else:
            logger.warning(
                "Connection not found for sync recording",
                extra={
                    "tenant_id": self.tenant_id,
                    "connection_id": connection_id,
                },
            )

        return updated

    # ── Static convenience for AI runners ─────────────────────────────────

    @staticmethod
    def check_ai_freshness_gate(
        db_session: Session,
        tenant_id: str,
        required_sources: Optional[List[str]] = None,
        ai_block_threshold_minutes: int = AI_STALENESS_BLOCK_THRESHOLD_MINUTES,
    ) -> FreshnessGateResult:
        """
        Static convenience for AI job runners to check freshness.

        Usage in job runners:
            gate = FreshnessService.check_ai_freshness_gate(
                db_session=self.db, tenant_id=job.tenant_id,
            )
            if not gate.is_allowed:
                job.mark_skipped(reason=gate.reason)
                return

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT
            required_sources: Optional source types to check
            ai_block_threshold_minutes: Override for block threshold

        Returns:
            FreshnessGateResult
        """
        service = FreshnessService(
            db_session=db_session,
            tenant_id=tenant_id,
            ai_block_threshold_minutes=ai_block_threshold_minutes,
        )
        return service.check_freshness_gate(
            required_sources=required_sources,
        )

    # ── Audit helpers ─────────────────────────────────────────────────────

    def _log_ai_gate_blocked(self, stale_sources: List[str]) -> None:
        """Log an audit event when AI is blocked due to stale data."""
        try:
            from src.platform.audit import (
                AuditAction,
                AuditOutcome,
                log_system_audit_event_sync,
            )

            log_system_audit_event_sync(
                db=self.db,
                tenant_id=self.tenant_id,
                action=AuditAction.AI_ACTION_BLOCKED,
                resource_type="freshness_gate",
                metadata={
                    "gate": "freshness",
                    "stale_sources": stale_sources,
                    "threshold_minutes": self.ai_block_threshold_minutes,
                },
                source="service",
                outcome=AuditOutcome.FAILURE,
            )
        except Exception as exc:
            logger.error(
                "Failed to log AI gate audit event",
                extra={
                    "tenant_id": self.tenant_id,
                    "error": str(exc),
                },
            )
