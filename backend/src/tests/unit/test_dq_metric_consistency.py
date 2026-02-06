"""
Unit tests for DQService metric consistency checks (Story 4.1).

Tests cover:
- Ratio constraint validation (ROAS = revenue / spend)
- Sum match constraint validation (revenue ≈ sum of components)
- Non-negative constraint validation
- Tolerance band enforcement
- Violation context emission
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

from src.api.dq.service import DQService
from src.models.dq_models import DQCheckType, DQSeverity


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-mc-001"


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = Mock()
    mock_query = Mock()
    mock_query.filter = Mock(return_value=mock_query)
    mock_query.first = Mock(return_value=None)
    session.query = Mock(return_value=mock_query)
    return session


@pytest.fixture
def dq_service(mock_db_session, tenant_id):
    """Create a DQService instance."""
    return DQService(mock_db_session, tenant_id)


class TestCheckMetricConsistencyRatio:
    """Tests for ratio-type metric consistency checks."""

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_roas_within_tolerance(self, mock_loader, dq_service):
        """ROAS matches expected value within 1% tolerance."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "roas_equals_revenue_over_spend": {
                "type": "ratio",
                "description": "ROAS = revenue / spend",
                "tolerance_pct": 1.0,
            }
        }
        mock_loader.return_value = loader

        # Expected ROAS = 4.0, observed ROAS = 4.02 (0.5% off)
        result = dq_service.check_metric_consistency(
            constraint_name="roas_equals_revenue_over_spend",
            observed_value=Decimal("4.02"),
            expected_value=Decimal("4.00"),
        )

        assert result.is_anomaly is False
        assert result.check_type == DQCheckType.METRIC_INCONSISTENCY
        assert result.metadata["deviation_pct"] == 0.5

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_roas_exceeds_tolerance(self, mock_loader, dq_service):
        """ROAS deviates beyond 1% tolerance triggers violation."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "roas_equals_revenue_over_spend": {
                "type": "ratio",
                "description": "ROAS = revenue / spend",
                "tolerance_pct": 1.0,
            }
        }
        mock_loader.return_value = loader

        # Expected ROAS = 4.0, observed ROAS = 4.10 (2.5% off)
        result = dq_service.check_metric_consistency(
            constraint_name="roas_equals_revenue_over_spend",
            observed_value=Decimal("4.10"),
            expected_value=Decimal("4.00"),
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.METRIC_INCONSISTENCY
        assert "violation" in result.message.lower()
        assert result.metadata["deviation_pct"] == 2.5
        assert result.metadata["tolerance_pct"] == 1.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_cac_within_tolerance(self, mock_loader, dq_service):
        """CAC = spend / new_customers within tolerance."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "cac_equals_spend_over_new_customers": {
                "type": "ratio",
                "description": "CAC = spend / new_customers",
                "tolerance_pct": 1.0,
            }
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="cac_equals_spend_over_new_customers",
            observed_value=Decimal("25.00"),
            expected_value=Decimal("25.10"),
        )

        assert result.is_anomaly is False
        assert result.metadata["deviation_pct"] < 1.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_custom_tolerance_override(self, mock_loader, dq_service):
        """Caller can override tolerance_pct."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "custom_check": {
                "type": "ratio",
                "description": "Custom check",
                "tolerance_pct": 1.0,
            }
        }
        mock_loader.return_value = loader

        # 3% deviation, default tolerance is 1% but override with 5%
        result = dq_service.check_metric_consistency(
            constraint_name="custom_check",
            observed_value=Decimal("103"),
            expected_value=Decimal("100"),
            tolerance_pct=5.0,
        )

        assert result.is_anomaly is False
        assert result.metadata["tolerance_pct"] == 5.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_both_zero_passes(self, mock_loader, dq_service):
        """Both observed and expected at zero passes (no division error)."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "roas_check": {"type": "ratio", "description": "ROAS", "tolerance_pct": 1.0}
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="roas_check",
            observed_value=Decimal("0"),
            expected_value=Decimal("0"),
        )

        assert result.is_anomaly is False

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_expected_zero_observed_nonzero(self, mock_loader, dq_service):
        """Expected 0 but observed non-zero is a 100% deviation."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "test_check": {"type": "ratio", "description": "Test", "tolerance_pct": 1.0}
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="test_check",
            observed_value=Decimal("100"),
            expected_value=Decimal("0"),
        )

        assert result.is_anomaly is True
        assert result.metadata["deviation_pct"] == 100.0


class TestCheckMetricConsistencyNonNegative:
    """Tests for non_negative constraint type."""

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_positive_value_passes(self, mock_loader, dq_service):
        """Positive value passes non-negative check."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "spend_non_negative": {
                "type": "non_negative",
                "description": "Spend must not be negative",
            }
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="spend_non_negative",
            observed_value=Decimal("100.50"),
            expected_value=Decimal("0"),
        )

        assert result.is_anomaly is False

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_zero_value_passes(self, mock_loader, dq_service):
        """Zero value passes non-negative check."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "spend_non_negative": {
                "type": "non_negative",
                "description": "Spend must not be negative",
            }
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="spend_non_negative",
            observed_value=Decimal("0"),
            expected_value=Decimal("0"),
        )

        assert result.is_anomaly is False

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_negative_value_fails(self, mock_loader, dq_service):
        """Negative value triggers non-negative violation."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "spend_non_negative": {
                "type": "non_negative",
                "description": "Spend must not be negative",
            }
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="spend_non_negative",
            observed_value=Decimal("-5.00"),
            expected_value=Decimal("0"),
        )

        assert result.is_anomaly is True
        assert result.severity == DQSeverity.HIGH
        assert "negative" in result.message.lower()


class TestCheckMetricConsistencySumMatch:
    """Tests for sum_match constraint type."""

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_sum_within_tolerance(self, mock_loader, dq_service):
        """Revenue sum matches aggregate within 0.5% tolerance."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "revenue_sum_match": {
                "type": "sum_match",
                "description": "Total revenue ≈ sum(order line revenue)",
                "tolerance_pct": 0.5,
            }
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="revenue_sum_match",
            observed_value=Decimal("10000.00"),
            expected_value=Decimal("10020.00"),
        )

        assert result.is_anomaly is False
        assert result.metadata["deviation_pct"] < 0.5

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_sum_exceeds_tolerance(self, mock_loader, dq_service):
        """Revenue sum diverges beyond tolerance."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "revenue_sum_match": {
                "type": "sum_match",
                "description": "Total revenue ≈ sum(order line revenue)",
                "tolerance_pct": 0.5,
            }
        }
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="revenue_sum_match",
            observed_value=Decimal("10000.00"),
            expected_value=Decimal("10100.00"),
        )

        assert result.is_anomaly is True
        assert result.metadata["deviation_pct"] > 0.5


class TestCheckMetricConsistencyContext:
    """Tests for context emission on violations."""

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_context_included_in_metadata(self, mock_loader, dq_service):
        """Additional context is included in violation metadata."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "test_check": {"type": "ratio", "description": "Test", "tolerance_pct": 1.0}
        }
        mock_loader.return_value = loader

        ctx = {"tenant_id": "t-123", "date_range": "2026-01-01 to 2026-01-31"}
        result = dq_service.check_metric_consistency(
            constraint_name="test_check",
            observed_value=Decimal("110"),
            expected_value=Decimal("100"),
            context=ctx,
        )

        assert result.is_anomaly is True
        assert result.metadata["context"] == ctx

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_unknown_constraint_uses_defaults(self, mock_loader, dq_service):
        """Unknown constraint name gracefully falls back to defaults."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {}
        mock_loader.return_value = loader

        result = dq_service.check_metric_consistency(
            constraint_name="nonexistent_constraint",
            observed_value=Decimal("100"),
            expected_value=Decimal("100"),
        )

        assert result.is_anomaly is False
        assert result.metadata["constraint_name"] == "nonexistent_constraint"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_severity_escalation_large_deviation(self, mock_loader, dq_service):
        """Deviation > 5x tolerance escalates to HIGH severity."""
        loader = Mock()
        loader.get_metric_constraints.return_value = {
            "test_check": {"type": "ratio", "description": "Test", "tolerance_pct": 1.0}
        }
        mock_loader.return_value = loader

        # 10% deviation with 1% tolerance → 10x tolerance → HIGH
        result = dq_service.check_metric_consistency(
            constraint_name="test_check",
            observed_value=Decimal("110"),
            expected_value=Decimal("100"),
        )

        assert result.is_anomaly is True
        assert result.severity == DQSeverity.HIGH
