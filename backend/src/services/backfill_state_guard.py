"""
Backfill state guard — protects downstream analytics during active backfills.

When a historical backfill is running for a tenant + source system:
- Data availability is overridden to STALE (triggers existing middleware)
- AI insights are automatically disabled (AIAvailabilityCheck blocks on STALE)
- Dashboards show warning OR are locked (configurable via BACKFILL_DASHBOARD_MODE)

On completion:
- Freshness is recalculated for affected sources
- Entitlement cache is cleared so access decisions refresh

This service integrates with the existing DataAvailabilityService state machine.
Overriding to STALE (rather than UNAVAILABLE) means:
- Superset dashboards: allowed with warning (or blocked if mode=lock)
- API endpoints: allowed with warning attached to request.state
- AI insights: disabled (AIAvailabilityCheck blocks STALE)

Story 3.4 - Backfill Execution
"""

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from src.models.data_availability import AvailabilityState
from src.services.data_availability_service import (
    CONNECTION_SOURCE_TO_SLA_KEY,
    resolve_sla_key,
)

logger = logging.getLogger(__name__)

# Configurable dashboard behaviour during backfills:
#   "warn" = allow with warning (default, matches STALE behaviour)
#   "lock" = block dashboard queries entirely
BACKFILL_DASHBOARD_MODE = os.getenv("BACKFILL_DASHBOARD_MODE", "warn")


@dataclass
class BackfillGuardStatus:
    """Result of a backfill guard check for a tenant."""

    is_backfill_active: bool
    active_request_ids: List[str] = field(default_factory=list)
    affected_source_systems: List[str] = field(default_factory=list)
    affected_sla_keys: List[str] = field(default_factory=list)
    dashboard_mode: str = "warn"
    ai_insights_allowed: bool = True
    data_availability_override: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "is_backfill_active": self.is_backfill_active,
            "active_request_ids": self.active_request_ids,
            "affected_source_systems": self.affected_source_systems,
            "affected_sla_keys": self.affected_sla_keys,
            "dashboard_mode": self.dashboard_mode,
            "ai_insights_allowed": self.ai_insights_allowed,
            "data_availability_override": self.data_availability_override,
        }


class BackfillStateGuard:
    """
    Guards downstream analytics during active historical backfills.

    Queries HistoricalBackfillRequest for RUNNING backfills and provides:
    - Source-level backfill status for DataAvailabilityService integration
    - Full guard status for middleware consumers
    - Completion hooks for cache clearing and freshness recalculation
    """

    def __init__(self, db_session: Session, tenant_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self.db = db_session
        self.tenant_id = tenant_id

    # ------------------------------------------------------------------
    # Active backfill queries
    # ------------------------------------------------------------------

    def get_active_backfills(self):
        """Get RUNNING backfill requests for this tenant."""
        from src.models.historical_backfill import (
            HistoricalBackfillRequest,
            HistoricalBackfillStatus,
        )

        return (
            self.db.query(HistoricalBackfillRequest)
            .filter(
                HistoricalBackfillRequest.tenant_id == self.tenant_id,
                HistoricalBackfillRequest.status
                == HistoricalBackfillStatus.RUNNING,
            )
            .all()
        )

    def is_backfill_active(self) -> bool:
        """Check if any backfill is running for this tenant."""
        from src.models.historical_backfill import (
            HistoricalBackfillRequest,
            HistoricalBackfillStatus,
        )

        return (
            self.db.query(HistoricalBackfillRequest)
            .filter(
                HistoricalBackfillRequest.tenant_id == self.tenant_id,
                HistoricalBackfillRequest.status
                == HistoricalBackfillStatus.RUNNING,
            )
            .first()
            is not None
        )

    def is_source_being_backfilled(self, sla_source_key: str) -> bool:
        """
        Check if a specific SLA source is being backfilled.

        Maps backfill source_system (e.g. "shopify") to SLA key
        (e.g. "shopify_orders") and checks for RUNNING backfills.
        """
        active = self.get_active_backfills()
        for req in active:
            mapped_key = resolve_sla_key(req.source_system)
            if mapped_key == sla_source_key:
                return True
        return False

    # ------------------------------------------------------------------
    # Full guard status
    # ------------------------------------------------------------------

    def get_guard_status(self) -> BackfillGuardStatus:
        """
        Get comprehensive backfill guard status for this tenant.

        Returns a BackfillGuardStatus with:
        - Active backfill info
        - Affected sources (mapped to SLA keys)
        - Dashboard mode (warn/lock)
        - AI insights flag (always disabled during backfill)
        - Data availability override (STALE during backfill)
        """
        active = self.get_active_backfills()

        if not active:
            return BackfillGuardStatus(
                is_backfill_active=False,
                ai_insights_allowed=True,
                dashboard_mode=BACKFILL_DASHBOARD_MODE,
            )

        request_ids = [r.id for r in active]
        source_systems = list({r.source_system for r in active})
        sla_keys = list(
            {
                resolve_sla_key(s)
                for s in source_systems
                if resolve_sla_key(s)
            }
        )

        return BackfillGuardStatus(
            is_backfill_active=True,
            active_request_ids=request_ids,
            affected_source_systems=source_systems,
            affected_sla_keys=sla_keys,
            dashboard_mode=BACKFILL_DASHBOARD_MODE,
            ai_insights_allowed=False,
            data_availability_override=AvailabilityState.STALE.value,
        )

    # ------------------------------------------------------------------
    # Completion hooks
    # ------------------------------------------------------------------

    def on_backfill_completed(
        self,
        request_id: str,
        source_system: str,
    ) -> None:
        """
        Called when a backfill request completes (all chunks done).

        Triggers:
        1. Freshness recalculation for affected sources
        2. Entitlement cache invalidation
        3. Audit log entry
        """
        sla_key = resolve_sla_key(source_system)

        # 1. Recalculate freshness for the affected source
        self._recalculate_freshness(sla_key)

        # 2. Clear entitlement cache
        self._clear_caches()

        # NOTE: Audit events are now emitted by the executor via
        # services/audit_logger.py (backfill.completed / backfill.failed).

        logger.info(
            "backfill_state_guard.completion_processed",
            extra={
                "tenant_id": self.tenant_id,
                "request_id": request_id,
                "source_system": source_system,
                "sla_key": sla_key,
            },
        )

    def _recalculate_freshness(self, sla_key: Optional[str]) -> None:
        """Trigger freshness recalculation for affected source."""
        try:
            from src.services.data_availability_service import (
                DataAvailabilityService,
            )

            service = DataAvailabilityService(
                db_session=self.db,
                tenant_id=self.tenant_id,
            )

            if sla_key:
                service.get_data_availability(sla_key)
            else:
                service.evaluate_all()

        except Exception:
            logger.warning(
                "backfill_state_guard.freshness_recalc_failed",
                extra={"tenant_id": self.tenant_id, "sla_key": sla_key},
                exc_info=True,
            )

    def _clear_caches(self) -> None:
        """Clear entitlement and feature flag caches for this tenant."""
        try:
            from src.entitlements.cache import invalidate_tenant_entitlements

            invalidate_tenant_entitlements(
                self.tenant_id,
                reason="backfill_completed",
            )
        except Exception:
            logger.warning(
                "backfill_state_guard.cache_clear_failed",
                extra={"tenant_id": self.tenant_id},
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Static convenience
    # ------------------------------------------------------------------

    @staticmethod
    def check_backfill_active(
        db_session: Session,
        tenant_id: str,
    ) -> bool:
        """Static convenience for one-shot backfill check."""
        guard = BackfillStateGuard(db_session, tenant_id)
        return guard.is_backfill_active()

    @staticmethod
    def get_status(
        db_session: Session,
        tenant_id: str,
    ) -> BackfillGuardStatus:
        """Static convenience for one-shot guard status."""
        guard = BackfillStateGuard(db_session, tenant_id)
        return guard.get_guard_status()
