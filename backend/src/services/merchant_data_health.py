"""
Merchant-facing data health service.

Combines internal data availability (Epic 3) and data quality (Epic 4.1)
states into a unified merchant trust layer with three states:

    HEALTHY     — FRESH + PASS     → All features enabled
    DELAYED     — STALE or WARN    → AI disabled, dashboards allowed
    UNAVAILABLE — UNAVAILABLE or FAIL → Dashboards blocked

This service is the single source of truth for merchant-facing health
and drives feature gating, UI indicators, and merchant messaging.

SECURITY:
- tenant_id must come from JWT (org_id), never from client input.
- Never exposes internal state names, SLA thresholds, or error codes.
- All messages are merchant-safe plain English.

Story 4.3 - Merchant Data Health Trust Layer
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.models.data_availability import AvailabilityState
from src.models.dq_models import DataQualityState
from src.models.merchant_data_health import (
    FEATURE_FLAGS,
    MerchantHealthState,
    get_merchant_message,
)

logger = logging.getLogger(__name__)


@dataclass
class MerchantDataHealthResult:
    """Result of a merchant data health evaluation."""
    state: MerchantHealthState
    message: str
    ai_insights_enabled: bool
    dashboards_enabled: bool
    exports_enabled: bool
    evaluated_at: datetime
    previous_state: Optional[MerchantHealthState] = None


class MerchantDataHealthService:
    """
    Evaluates and returns the merchant-facing data health state.

    Combines availability and quality signals into a single trust
    decision for the merchant.

    SECURITY: tenant_id must originate from JWT (org_id).
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        billing_tier: str = "free",
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self.billing_tier = billing_tier

    def evaluate(self) -> MerchantDataHealthResult:
        """
        Evaluate the merchant data health state.

        Combines:
        1. Data availability from DataAvailabilityService
        2. Data quality from DQService (via sync health summary)

        Returns:
            MerchantDataHealthResult with the unified health state.
        """
        now = datetime.now(timezone.utc)

        availability_aggregate = self._get_availability_aggregate()
        quality_aggregate = self._get_quality_aggregate()

        state = self._map_to_merchant_state(
            availability_aggregate, quality_aggregate,
        )

        flags = FEATURE_FLAGS[state]
        message = get_merchant_message(state)

        result = MerchantDataHealthResult(
            state=state,
            message=message,
            ai_insights_enabled=flags["ai_insights_enabled"],
            dashboards_enabled=flags["dashboards_enabled"],
            exports_enabled=flags["exports_enabled"],
            evaluated_at=now,
        )

        logger.info(
            "Merchant data health evaluated",
            extra={
                "tenant_id": self.tenant_id,
                "merchant_state": state.value,
                "availability_aggregate": availability_aggregate,
                "quality_aggregate": quality_aggregate,
            },
        )

        return result

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_availability_aggregate(self) -> str:
        """
        Get the worst-case availability state across all sources.

        Returns one of: "fresh", "stale", "unavailable".
        """
        try:
            from src.services.data_availability_service import (
                DataAvailabilityService,
            )

            service = DataAvailabilityService(
                db_session=self.db,
                tenant_id=self.tenant_id,
                billing_tier=self.billing_tier,
            )
            results = service.evaluate_all()

            if not results:
                return AvailabilityState.FRESH.value

            has_unavailable = any(
                r.state == AvailabilityState.UNAVAILABLE.value
                for r in results
            )
            if has_unavailable:
                return AvailabilityState.UNAVAILABLE.value

            has_stale = any(
                r.state == AvailabilityState.STALE.value
                for r in results
            )
            if has_stale:
                return AvailabilityState.STALE.value

            return AvailabilityState.FRESH.value

        except Exception as exc:
            logger.error(
                "Failed to evaluate data availability",
                extra={
                    "tenant_id": self.tenant_id,
                    "error": str(exc),
                },
            )
            return AvailabilityState.FRESH.value

    def _get_quality_aggregate(self) -> str:
        """
        Get the aggregate data quality state for the tenant.

        Uses the sync health summary to derive quality from
        existing DQ checks without re-running them.

        Returns one of: "pass", "warn", "fail".
        """
        try:
            from src.api.dq.service import DQService

            service = DQService(
                db_session=self.db,
                tenant_id=self.tenant_id,
            )
            summary = service.get_sync_health_summary()

            if summary.has_blocking_issues or summary.error_count > 0:
                return DataQualityState.FAIL.value

            if summary.delayed_count > 0:
                return DataQualityState.WARN.value

            return DataQualityState.PASS_STATE.value

        except Exception as exc:
            logger.error(
                "Failed to evaluate data quality",
                extra={
                    "tenant_id": self.tenant_id,
                    "error": str(exc),
                },
            )
            return DataQualityState.PASS_STATE.value

    @staticmethod
    def _map_to_merchant_state(
        availability: str,
        quality: str,
    ) -> MerchantHealthState:
        """
        Map internal availability + quality states to a merchant state.

        Rules (evaluated in priority order):
            1. UNAVAILABLE or FAIL  → UNAVAILABLE
            2. STALE or WARN        → DELAYED
            3. FRESH + PASS         → HEALTHY
        """
        if (
            availability == AvailabilityState.UNAVAILABLE.value
            or quality == DataQualityState.FAIL.value
        ):
            return MerchantHealthState.UNAVAILABLE

        if (
            availability == AvailabilityState.STALE.value
            or quality == DataQualityState.WARN.value
        ):
            return MerchantHealthState.DELAYED

        return MerchantHealthState.HEALTHY
