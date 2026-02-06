"""
Superset quality hook for controlling dashboard query access based on DQ state.

Provides a backend service that Superset calls before executing queries.
Controls access based on the aggregated DataQualityState:

- FAIL -> Query BLOCKED (dashboards disabled)
- WARN -> Query ALLOWED with warning banner
- PASS -> Query ALLOWED

This complements the existing SupersetAvailabilityHook (which checks data
freshness/availability). Both hooks must pass for a query to execute.

Messages are human-readable and never expose internal details.

SECURITY: tenant_id must come from JWT (org_id), never from client input.

Usage:
    hook = SupersetQualityHook(db_session=session)
    result = hook.check_query_quality(
        tenant_id="tenant_123",
        freshness_results=freshness_results,
        anomaly_results=anomaly_results,
    )
    if not result.is_allowed:
        block_query(reason=result.blocked_reason)

    # Static convenience
    result = SupersetQualityHook.check_quality(
        tenant_id="tenant_123",
        verdict=verdict,
    )
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from src.api.dq.service import (
    AnomalyCheckResult,
    DQService,
    DataQualityVerdict,
    FreshnessCheckResult,
)
from src.models.dq_models import DataQualityState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Human-readable messages (never expose internal details)
# ---------------------------------------------------------------------------

_MSG_BLOCKED = (
    "Dashboards are temporarily paused while we resolve a data quality issue. "
    "This usually resolves within a few minutes."
)

_MSG_WARNING = (
    "Some data quality checks have warnings. "
    "Dashboard results are available but may require review."
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class QueryQualityResult:
    """
    Result of a Superset query quality check.

    Attributes:
        is_allowed:       Whether the query may proceed.
        warning_message:  Optional user-facing warning when quality is WARN.
        blocked_reason:   Optional user-facing reason when query is blocked.
        failing_checks:   List of check descriptions that failed.
        quality_state:    The aggregated quality state.
        evaluated_at:     Timestamp of the evaluation.
    """

    is_allowed: bool
    warning_message: Optional[str] = None
    blocked_reason: Optional[str] = None
    failing_checks: List[str] = field(default_factory=list)
    quality_state: Optional[str] = None
    evaluated_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "is_allowed": self.is_allowed,
            "warning_message": self.warning_message,
            "blocked_reason": self.blocked_reason,
            "failing_checks": self.failing_checks,
            "quality_state": self.quality_state,
        }


# ---------------------------------------------------------------------------
# Hook service
# ---------------------------------------------------------------------------

class SupersetQualityHook:
    """
    Backend service that Superset calls before executing queries to verify
    data quality.

    Evaluates the aggregated DataQualityState for the tenant and returns
    a :class:`QueryQualityResult` indicating whether the query may proceed,
    must be blocked, or should carry a warning.

    SECURITY: tenant_id must originate from JWT (org_id).
    """

    def __init__(self, db_session: Optional[Session] = None):
        """
        Args:
            db_session: SQLAlchemy database session (optional, not needed
                        when verdict is pre-computed).
        """
        self.db = db_session

    # ── Public API ────────────────────────────────────────────────────────

    def check_query_quality(
        self,
        tenant_id: str,
        freshness_results: Optional[List[FreshnessCheckResult]] = None,
        anomaly_results: Optional[List[AnomalyCheckResult]] = None,
        verdict: Optional[DataQualityVerdict] = None,
        dashboard_id: Optional[str] = None,
    ) -> QueryQualityResult:
        """
        Check whether a Superset query may execute based on data quality.

        Evaluation rules:
        1. FAIL -> BLOCKED (dashboards disabled)
        2. WARN -> ALLOWED with warning banner
        3. PASS -> ALLOWED

        Args:
            tenant_id:          Tenant ID from JWT.
            freshness_results:  Optional freshness check results.
            anomaly_results:    Optional anomaly check results.
            verdict:            Optional pre-computed DataQualityVerdict.
            dashboard_id:       Optional dashboard ID for logging.

        Returns:
            :class:`QueryQualityResult` with the access decision.
        """
        now = datetime.now(timezone.utc)

        if verdict is None:
            verdict = DQService.aggregate_quality_state(
                freshness_results=freshness_results or [],
                anomaly_results=anomaly_results or [],
            )

        # Decision: BLOCKED
        if verdict.state == DataQualityState.FAIL:
            logger.warning(
                "Superset query blocked: data quality FAIL",
                extra={
                    "tenant_id": tenant_id,
                    "dashboard_id": dashboard_id,
                    "failure_count": verdict.failure_count,
                    "failing_checks": verdict.failing_checks,
                },
            )
            return QueryQualityResult(
                is_allowed=False,
                blocked_reason=_MSG_BLOCKED,
                failing_checks=verdict.failing_checks,
                quality_state=verdict.state.value,
                evaluated_at=now,
            )

        # Decision: ALLOWED with warning
        if verdict.state == DataQualityState.WARN:
            logger.info(
                "Superset query allowed with quality warning",
                extra={
                    "tenant_id": tenant_id,
                    "dashboard_id": dashboard_id,
                    "warning_count": verdict.warning_count,
                },
            )
            return QueryQualityResult(
                is_allowed=True,
                warning_message=_MSG_WARNING,
                quality_state=verdict.state.value,
                evaluated_at=now,
            )

        # Decision: ALLOWED (all checks passed)
        logger.debug(
            "Superset query allowed: all quality checks passed",
            extra={
                "tenant_id": tenant_id,
                "dashboard_id": dashboard_id,
            },
        )
        return QueryQualityResult(
            is_allowed=True,
            quality_state=verdict.state.value,
            evaluated_at=now,
        )

    # ── Static convenience ────────────────────────────────────────────────

    @staticmethod
    def check_quality(
        tenant_id: str,
        freshness_results: Optional[List[FreshnessCheckResult]] = None,
        anomaly_results: Optional[List[AnomalyCheckResult]] = None,
        verdict: Optional[DataQualityVerdict] = None,
        dashboard_id: Optional[str] = None,
    ) -> QueryQualityResult:
        """
        Static convenience for one-shot query quality checks.

        Usage::

            result = SupersetQualityHook.check_quality(
                tenant_id="tenant_123",
                verdict=verdict,
            )
            if not result.is_allowed:
                return {"error": result.blocked_reason}
        """
        hook = SupersetQualityHook()
        return hook.check_query_quality(
            tenant_id=tenant_id,
            freshness_results=freshness_results,
            anomaly_results=anomaly_results,
            verdict=verdict,
            dashboard_id=dashboard_id,
        )
