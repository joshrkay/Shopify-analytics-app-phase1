"""
Unified Safety Guards for Superset Tenant Isolation.

This module centralizes ALL safety checks into a single import.
It validates configuration at startup and enforces invariants at runtime.

PRINCIPLE: Every check that could prevent data leakage belongs here.
If this module reports a failure, Superset should NOT serve data.

Startup checks (run once at boot):
- JWT secret configured
- Metadata DB reachable
- RLS rules applied to all datasets
- Performance limits frozen
- Feature flags correctly set

Runtime checks (run per request via jwt_auth.py):
- Valid JWT present
- Tenant context complete (tenant_id in allowed_tenants)
- Dataset has RLS

Story 5.1.8 - Failure & Misconfiguration Handling
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class GuardCheckResult(Enum):
    """Result of a safety guard check."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"


@dataclass(frozen=True)
class GuardResult:
    """Immutable result from a single guard check."""

    check_name: str
    result: GuardCheckResult
    message: str
    severity: str = "critical"  # critical, high, medium
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class StartupGuards:
    """Validates Superset configuration at startup.

    All critical checks MUST pass or Superset should not serve data.
    Non-critical checks log warnings but don't block startup.
    """

    @staticmethod
    def check_jwt_secret_configured() -> GuardResult:
        """CRITICAL: JWT secret must be configured."""
        current = os.getenv("SUPERSET_JWT_SECRET_CURRENT")
        if not current:
            return GuardResult(
                check_name="jwt_secret",
                result=GuardCheckResult.FAIL,
                message="SUPERSET_JWT_SECRET_CURRENT not set — all requests will be denied",
            )
        if len(current) < 32:
            return GuardResult(
                check_name="jwt_secret",
                result=GuardCheckResult.WARN,
                message="JWT secret is short (< 32 chars) — consider a stronger secret",
                severity="high",
            )
        return GuardResult(
            check_name="jwt_secret",
            result=GuardCheckResult.PASS,
            message="JWT secret configured",
        )

    @staticmethod
    def check_metadata_db_configured() -> GuardResult:
        """CRITICAL: Metadata database URI must be set."""
        db_uri = os.getenv("SUPERSET_METADATA_DB_URI")
        if not db_uri:
            return GuardResult(
                check_name="metadata_db",
                result=GuardCheckResult.FAIL,
                message="SUPERSET_METADATA_DB_URI not set",
            )
        return GuardResult(
            check_name="metadata_db",
            result=GuardCheckResult.PASS,
            message="Metadata DB configured",
        )

    @staticmethod
    def check_performance_limits_frozen() -> GuardResult:
        """Verify performance limits are immutable."""
        try:
            from performance_config import PERFORMANCE_LIMITS

            try:
                PERFORMANCE_LIMITS.row_limit = 999999  # type: ignore[misc]
                return GuardResult(
                    check_name="perf_limits",
                    result=GuardCheckResult.FAIL,
                    message="Performance limits are mutable — safety violation",
                )
            except (AttributeError, TypeError):
                pass

            return GuardResult(
                check_name="perf_limits",
                result=GuardCheckResult.PASS,
                message="Performance limits are frozen",
            )
        except ImportError:
            return GuardResult(
                check_name="perf_limits",
                result=GuardCheckResult.FAIL,
                message="performance_config module not found",
            )

    @staticmethod
    def check_feature_flags_safe() -> GuardResult:
        """Verify dangerous features are disabled."""
        try:
            from performance_config import SAFETY_FEATURE_FLAGS

            dangerous_enabled = [
                flag
                for flag, expected in SAFETY_FEATURE_FLAGS.items()
                if expected is not False
            ]
            if dangerous_enabled:
                return GuardResult(
                    check_name="feature_flags",
                    result=GuardCheckResult.FAIL,
                    message=f"Dangerous features enabled: {dangerous_enabled}",
                )
            return GuardResult(
                check_name="feature_flags",
                result=GuardCheckResult.PASS,
                message="All safety feature flags correctly set",
            )
        except ImportError:
            return GuardResult(
                check_name="feature_flags",
                result=GuardCheckResult.WARN,
                message="performance_config not available for flag validation",
                severity="high",
            )

    @staticmethod
    def check_dataset_sync_status() -> GuardResult:
        """
        Warn if last dataset sync was blocked or failed.

        Reads from SUPERSET_DATASET_SYNC_STATUS (set by CI/backend after sync).
        Values: ok, failed, blocked. If blocked or failed, logs WARN so
        operators know dashboards may be stale or incompatible.
        """
        status = os.getenv("SUPERSET_DATASET_SYNC_STATUS", "ok").lower().strip()
        if status in ("blocked", "failed"):
            return GuardResult(
                check_name="dataset_sync_status",
                result=GuardCheckResult.WARN,
                message=(
                    f"Last dataset sync status is '{status}' — "
                    "Superset datasets may be stale or incompatible; check sync pipeline"
                ),
                severity="high",
            )
        return GuardResult(
            check_name="dataset_sync_status",
            result=GuardCheckResult.PASS,
            message="Dataset sync status ok or not set",
        )

    @staticmethod
    def check_rls_enforcement(superset_client=None) -> GuardResult:
        """CRITICAL: All datasets must have RLS rules.

        If a Superset API client is provided, validates against live data.
        Otherwise checks the static registry.
        """
        try:
            from rls_rules import ALL_DATASETS_REQUIRING_RLS, DENY_BY_DEFAULT_CLAUSE

            if not ALL_DATASETS_REQUIRING_RLS:
                return GuardResult(
                    check_name="rls_enforcement",
                    result=GuardCheckResult.FAIL,
                    message="No datasets in RLS registry",
                )

            if DENY_BY_DEFAULT_CLAUSE != "1=0":
                return GuardResult(
                    check_name="rls_enforcement",
                    result=GuardCheckResult.FAIL,
                    message=f"DENY_BY_DEFAULT_CLAUSE is '{DENY_BY_DEFAULT_CLAUSE}', expected '1=0'",
                )

            if superset_client:
                from rls_rules import validate_all_datasets_have_rls, enforce_deny_by_default

                is_valid, unprotected = validate_all_datasets_have_rls(superset_client)
                if not is_valid:
                    enforce_deny_by_default(superset_client)
                    return GuardResult(
                        check_name="rls_enforcement",
                        result=GuardCheckResult.WARN,
                        message=f"Applied deny-by-default to unprotected datasets: {unprotected}",
                        severity="high",
                    )

            return GuardResult(
                check_name="rls_enforcement",
                result=GuardCheckResult.PASS,
                message=f"RLS registry has {len(ALL_DATASETS_REQUIRING_RLS)} protected datasets",
            )
        except ImportError:
            return GuardResult(
                check_name="rls_enforcement",
                result=GuardCheckResult.FAIL,
                message="rls_rules module not found",
            )

    @classmethod
    def run_all_startup_checks(
        cls, superset_client=None
    ) -> tuple[bool, list[GuardResult]]:
        """Run all startup checks.

        Returns:
            (all_critical_passed, list_of_results)
        """
        results = [
            cls.check_jwt_secret_configured(),
            cls.check_metadata_db_configured(),
            cls.check_performance_limits_frozen(),
            cls.check_feature_flags_safe(),
            cls.check_dataset_sync_status(),
            cls.check_rls_enforcement(superset_client),
        ]

        for r in results:
            if r.result == GuardCheckResult.PASS:
                logger.info("Guard [%s]: PASS — %s", r.check_name, r.message)
            elif r.result == GuardCheckResult.WARN:
                logger.warning("Guard [%s]: WARN — %s", r.check_name, r.message)
            else:
                logger.critical("Guard [%s]: FAIL — %s", r.check_name, r.message)

        all_critical_passed = all(
            r.result != GuardCheckResult.FAIL for r in results
        )
        return all_critical_passed, results


class RuntimeGuards:
    """Per-request safety checks called from jwt_auth.py."""

    @staticmethod
    def validate_tenant_context(
        tenant_id: Optional[str], allowed_tenants: Optional[list[str]]
    ) -> GuardResult:
        """Validate tenant context is complete and consistent.

        Called after JWT is decoded but before setting Flask globals.
        """
        if not tenant_id:
            return GuardResult(
                check_name="tenant_context",
                result=GuardCheckResult.FAIL,
                message="Missing tenant_id in JWT claims",
                severity="critical",
            )
        if not allowed_tenants:
            return GuardResult(
                check_name="tenant_context",
                result=GuardCheckResult.FAIL,
                message="Missing allowed_tenants in JWT claims",
                severity="critical",
            )
        if tenant_id not in allowed_tenants:
            return GuardResult(
                check_name="tenant_context",
                result=GuardCheckResult.FAIL,
                message=(
                    f"tenant_id '{tenant_id}' not in allowed_tenants — "
                    "possible cross-tenant attack"
                ),
                severity="critical",
            )
        return GuardResult(
            check_name="tenant_context",
            result=GuardCheckResult.PASS,
            message="Tenant context valid",
        )

    @staticmethod
    def validate_dataset_has_rls(dataset_name: str) -> GuardResult:
        """Check dataset is in the RLS-protected list."""
        try:
            from rls_rules import ALL_DATASETS_REQUIRING_RLS

            if dataset_name not in ALL_DATASETS_REQUIRING_RLS:
                return GuardResult(
                    check_name="dataset_rls",
                    result=GuardCheckResult.FAIL,
                    message=f"Dataset '{dataset_name}' not in RLS registry — access blocked",
                    severity="critical",
                )
            return GuardResult(
                check_name="dataset_rls",
                result=GuardCheckResult.PASS,
                message=f"Dataset '{dataset_name}' has RLS",
            )
        except ImportError:
            return GuardResult(
                check_name="dataset_rls",
                result=GuardCheckResult.FAIL,
                message="rls_rules module not available",
            )
