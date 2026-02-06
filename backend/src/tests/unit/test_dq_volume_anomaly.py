"""
Unit tests for DQService volume anomaly detection (Story 4.1).

Tests cover:
- Rolling 7-day baseline comparison
- Plan-tier threshold enforcement (free/growth/enterprise)
- Anomaly score calculation
- Edge cases (zero baseline, insufficient data, spikes)
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

from src.api.dq.service import DQService
from src.models.dq_models import DQCheckType, DQSeverity


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-vol-001"


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = Mock()
    # Mock connector lookup
    mock_connector = Mock()
    mock_connector.connection_name = "Test Shopify"
    mock_connector.id = "conn-001"
    mock_connector.tenant_id = "test-tenant-vol-001"

    mock_query = Mock()
    mock_query.filter = Mock(return_value=mock_query)
    mock_query.first = Mock(return_value=mock_connector)
    session.query = Mock(return_value=mock_query)
    return session


@pytest.fixture
def dq_service(mock_db_session, tenant_id):
    """Create a DQService instance."""
    return DQService(mock_db_session, tenant_id)


class TestCheckVolumeAnomaly:
    """Tests for DQService.check_volume_anomaly."""

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_normal_range(self, mock_loader, dq_service):
        """10% deviation with 50% threshold returns is_anomaly=False."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=90,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert result.check_type == DQCheckType.VOLUME_ANOMALY
        assert result.observed_value == Decimal(90)
        assert result.expected_value == Decimal(100)
        assert result.metadata["anomaly_score"] == 0.2
        assert result.metadata["severity_label"] == "low"
        assert result.metadata["pct_change"] == 10.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_exceeds_threshold_drop(self, mock_loader, dq_service):
        """60% drop with 50% threshold returns is_anomaly=True."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=40,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.VOLUME_ANOMALY
        assert result.severity == DQSeverity.HIGH
        assert result.metadata["anomaly_score"] == 1.0
        assert result.metadata["severity_label"] == "high"
        assert result.metadata["pct_change"] == 60.0
        assert "dropped" in result.message

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_exceeds_threshold_spike(self, mock_loader, dq_service):
        """Volume spike beyond threshold is also flagged."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=200,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.metadata["pct_change"] == -100.0  # negative = spike
        assert "spiked" in result.message

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_free_tier_threshold(self, mock_loader, dq_service):
        """Free tier uses 50% threshold."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        # 45% drop - under 50% threshold
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=55,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert result.metadata["threshold_pct"] == 50.0
        assert result.metadata["billing_tier"] == "free"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_growth_tier_threshold(self, mock_loader, dq_service):
        """Growth tier uses 30% threshold - same drop triggers anomaly."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 30.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        # 45% drop - over 30% threshold
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=55,
            billing_tier="growth",
        )

        assert result.is_anomaly is True
        assert result.metadata["threshold_pct"] == 30.0
        assert result.metadata["billing_tier"] == "growth"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_enterprise_tier_threshold(self, mock_loader, dq_service):
        """Enterprise tier uses 15% threshold - even small drops trigger."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 15.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        # 20% drop - over 15% threshold
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=80,
            billing_tier="enterprise",
        )

        assert result.is_anomaly is True
        assert result.metadata["threshold_pct"] == 15.0
        assert result.metadata["billing_tier"] == "enterprise"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_zero_baseline(self, mock_loader, dq_service):
        """Zero rolling average returns is_anomaly=False (no comparison)."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        mock_loader.return_value = loader

        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[0, 0, 0, 0, 0, 0, 0],
            today_count=10,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert "zero" in result.message.lower() or "0" in result.message

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_insufficient_baseline(self, mock_loader, dq_service):
        """Less than 2 days of data returns is_anomaly=False."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        mock_loader.return_value = loader

        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100],
            today_count=50,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert "insufficient" in result.message.lower()

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_anomaly_score_calculation(self, mock_loader, dq_service):
        """Verify anomaly_score is correctly calculated in metadata."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "medium"
        mock_loader.return_value = loader

        # 25% drop → anomaly_score = 25/50 = 0.5
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=75,
            billing_tier="free",
        )

        assert result.metadata["anomaly_score"] == 0.5
        assert result.metadata["severity_label"] == "medium"
        assert result.metadata["rolling_avg"] == 100.0
        assert result.metadata["lookback_days"] == 7

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_anomaly_score_capped_at_one(self, mock_loader, dq_service):
        """Anomaly score is capped at 1.0 even for extreme deviations."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        # 90% drop → anomaly_score = min(90/50, 1.0) = 1.0
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=10,
            billing_tier="free",
        )

        assert result.metadata["anomaly_score"] == 1.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_severity_high_above_0_8(self, mock_loader, dq_service):
        """Anomaly score >= 0.8 maps to HIGH severity and 'high' label."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        # 50% drop → score = 50/50 = 1.0 → anomaly with high severity
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=50,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.severity == DQSeverity.HIGH
        assert result.metadata["severity_label"] == "high"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_severity_medium_mid_range(self, mock_loader, dq_service):
        """Anomaly score 0.5-0.8 maps to WARNING severity and 'medium' label."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 30.0
        loader.resolve_severity_label.return_value = "medium"
        mock_loader.return_value = loader

        # 20% drop with 30% threshold → score = 20/30 ≈ 0.667 → medium
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=80,
            billing_tier="growth",
        )

        assert result.severity == DQSeverity.WARNING
        assert result.metadata["severity_label"] == "medium"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_severity_low_small_deviation(self, mock_loader, dq_service):
        """Anomaly score < 0.5 maps to WARNING severity and 'low' label."""
        loader = Mock()
        loader.get_volume_anomaly_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        # 10% drop → score = 10/50 = 0.2 → low
        result = dq_service.check_volume_anomaly(
            connector_id="conn-001",
            daily_counts=[100, 100, 100, 100, 100, 100, 100],
            today_count=90,
            billing_tier="free",
        )

        assert result.severity == DQSeverity.WARNING
        assert result.metadata["severity_label"] == "low"
