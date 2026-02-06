"""
Unit tests for DQService quality state aggregation (Story 4.1).

Tests cover:
- PASS/WARN/FAIL state transitions
- Freshness + anomaly result aggregation
- Failure dominance over warnings
- Diagnostics (failing_checks, counts, message)
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

from src.api.dq.service import (
    DQService,
    FreshnessCheckResult,
    AnomalyCheckResult,
    DataQualityVerdict,
)
from src.models.dq_models import (
    DQCheckType,
    DQSeverity,
    DataQualityState,
    ConnectorSourceType,
)


def _freshness(is_fresh: bool, severity=None) -> FreshnessCheckResult:
    """Helper to build a FreshnessCheckResult."""
    return FreshnessCheckResult(
        connector_id="conn-001",
        connector_name="Test Shopify",
        source_type=ConnectorSourceType.SHOPIFY_ORDERS,
        is_fresh=is_fresh,
        severity=severity,
        minutes_since_sync=10 if is_fresh else 300,
        threshold_minutes=120,
        last_sync_at=datetime.now(timezone.utc),
        message="Fresh" if is_fresh else "Stale",
        merchant_message="Data is current" if is_fresh else "Data is delayed",
        support_details="",
    )


def _anomaly(is_anomaly: bool, severity=DQSeverity.WARNING) -> AnomalyCheckResult:
    """Helper to build an AnomalyCheckResult."""
    return AnomalyCheckResult(
        connector_id="conn-001",
        connector_name="Test Shopify",
        check_type=DQCheckType.VOLUME_ANOMALY,
        is_anomaly=is_anomaly,
        severity=severity,
        observed_value=Decimal("50"),
        expected_value=Decimal("100"),
        message="Volume dropped" if is_anomaly else "Volume normal",
        merchant_message="",
        support_details="",
        metadata={},
    )


class TestAggregateQualityState:
    """Tests for DQService.aggregate_quality_state."""

    def test_all_checks_pass(self):
        """All fresh + no anomalies → PASS."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[_freshness(is_fresh=True)],
            anomaly_results=[_anomaly(is_anomaly=False)],
        )
        assert verdict.state == DataQualityState.PASS_STATE
        assert verdict.failure_count == 0
        assert verdict.warning_count == 0
        assert verdict.passed_count == 2
        assert verdict.total_checks == 2

    def test_empty_lists(self):
        """No checks at all → PASS."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[],
            anomaly_results=[],
        )
        assert verdict.state == DataQualityState.PASS_STATE
        assert verdict.total_checks == 0
        assert verdict.message == "PASS: all 0 checks passed"

    def test_single_freshness_warning(self):
        """One stale connector with WARNING severity → WARN."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[_freshness(is_fresh=False, severity=DQSeverity.WARNING)],
            anomaly_results=[],
        )
        assert verdict.state == DataQualityState.WARN
        assert verdict.warning_count == 1
        assert verdict.failure_count == 0

    def test_single_anomaly_warning(self):
        """One anomaly with WARNING severity → WARN."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[],
            anomaly_results=[_anomaly(is_anomaly=True, severity=DQSeverity.WARNING)],
        )
        assert verdict.state == DataQualityState.WARN
        assert verdict.warning_count == 1

    def test_multiple_warnings(self):
        """Multiple warnings → WARN."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[
                _freshness(is_fresh=False, severity=DQSeverity.WARNING),
                _freshness(is_fresh=False, severity=DQSeverity.WARNING),
            ],
            anomaly_results=[_anomaly(is_anomaly=True, severity=DQSeverity.WARNING)],
        )
        assert verdict.state == DataQualityState.WARN
        assert verdict.warning_count == 3
        assert verdict.failure_count == 0

    def test_single_freshness_critical_failure(self):
        """One CRITICAL freshness failure → FAIL."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[
                _freshness(is_fresh=False, severity=DQSeverity.CRITICAL),
            ],
            anomaly_results=[],
        )
        assert verdict.state == DataQualityState.FAIL
        assert verdict.failure_count == 1
        assert len(verdict.failing_checks) == 1
        assert "Freshness" in verdict.failing_checks[0]

    def test_single_anomaly_high_failure(self):
        """One HIGH anomaly → FAIL."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[],
            anomaly_results=[_anomaly(is_anomaly=True, severity=DQSeverity.HIGH)],
        )
        assert verdict.state == DataQualityState.FAIL
        assert verdict.failure_count == 1
        assert "volume_anomaly" in verdict.failing_checks[0]

    def test_failure_dominates_warnings(self):
        """Mix of warnings + one failure → FAIL."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[
                _freshness(is_fresh=False, severity=DQSeverity.WARNING),
                _freshness(is_fresh=True),
            ],
            anomaly_results=[
                _anomaly(is_anomaly=True, severity=DQSeverity.HIGH),
                _anomaly(is_anomaly=True, severity=DQSeverity.WARNING),
            ],
        )
        assert verdict.state == DataQualityState.FAIL
        assert verdict.failure_count == 1
        assert verdict.warning_count == 2
        assert verdict.passed_count == 1

    def test_failing_checks_populated(self):
        """failing_checks lists descriptions of failed checks."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[
                _freshness(is_fresh=False, severity=DQSeverity.CRITICAL),
            ],
            anomaly_results=[
                _anomaly(is_anomaly=True, severity=DQSeverity.HIGH),
            ],
        )
        assert len(verdict.failing_checks) == 2
        assert any("Freshness" in c for c in verdict.failing_checks)
        assert any("volume_anomaly" in c for c in verdict.failing_checks)

    def test_total_checks_arithmetic(self):
        """total_checks = passed + warning + failure."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[
                _freshness(is_fresh=True),
                _freshness(is_fresh=False, severity=DQSeverity.WARNING),
                _freshness(is_fresh=False, severity=DQSeverity.HIGH),
            ],
            anomaly_results=[
                _anomaly(is_anomaly=False),
                _anomaly(is_anomaly=True, severity=DQSeverity.WARNING),
            ],
        )
        assert verdict.total_checks == 5
        assert verdict.passed_count == 2
        assert verdict.warning_count == 2
        assert verdict.failure_count == 1
        assert verdict.total_checks == verdict.passed_count + verdict.warning_count + verdict.failure_count

    def test_freshness_only_all_pass(self):
        """Freshness only (no anomalies), all fresh → PASS."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[
                _freshness(is_fresh=True),
                _freshness(is_fresh=True),
            ],
            anomaly_results=[],
        )
        assert verdict.state == DataQualityState.PASS_STATE
        assert verdict.total_checks == 2
        assert verdict.passed_count == 2

    def test_anomalies_only_with_failure(self):
        """Anomalies only (no freshness), one failure → FAIL."""
        verdict = DQService.aggregate_quality_state(
            freshness_results=[],
            anomaly_results=[
                _anomaly(is_anomaly=False),
                _anomaly(is_anomaly=True, severity=DQSeverity.CRITICAL),
            ],
        )
        assert verdict.state == DataQualityState.FAIL
        assert verdict.failure_count == 1
        assert verdict.passed_count == 1
