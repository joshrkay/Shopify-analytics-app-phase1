"""
Unit tests for DQService distribution drift and cardinality shift detection (Story 4.1).

Tests cover:
- Jensen-Shannon divergence calculation (pure Python)
- Distribution drift detection with plan-tier thresholds
- Cardinality shift detection (explosion/collapse)
- Edge cases (empty distributions, zero baseline, symmetry)
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

from src.api.dq.service import DQService
from src.models.dq_models import DQCheckType, DQSeverity


@pytest.fixture
def tenant_id():
    """Test tenant ID."""
    return "test-tenant-drift-001"


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = Mock()
    mock_connector = Mock()
    mock_connector.connection_name = "Test Shopify"
    mock_connector.id = "conn-001"
    mock_connector.tenant_id = "test-tenant-drift-001"

    mock_query = Mock()
    mock_query.filter = Mock(return_value=mock_query)
    mock_query.first = Mock(return_value=mock_connector)
    session.query = Mock(return_value=mock_query)
    return session


@pytest.fixture
def dq_service(mock_db_session, tenant_id):
    """Create a DQService instance."""
    return DQService(mock_db_session, tenant_id)


# ---------------------------------------------------------------------------
# Jensen-Shannon divergence
# ---------------------------------------------------------------------------

class TestJensenShannonDivergence:
    """Tests for DQService._jensen_shannon_divergence."""

    def test_identical_distributions(self):
        """Identical distributions → JSD ≈ 0."""
        p = {"a": 0.5, "b": 0.3, "c": 0.2}
        q = {"a": 0.5, "b": 0.3, "c": 0.2}
        jsd = DQService._jensen_shannon_divergence(p, q)
        assert jsd < 0.001

    def test_completely_different(self):
        """Non-overlapping distributions → JSD ≈ 1."""
        p = {"a": 1.0}
        q = {"b": 1.0}
        jsd = DQService._jensen_shannon_divergence(p, q)
        assert jsd > 0.9

    def test_slight_shift(self):
        """Small change → small JSD."""
        p = {"a": 0.5, "b": 0.3, "c": 0.2}
        q = {"a": 0.48, "b": 0.32, "c": 0.2}
        jsd = DQService._jensen_shannon_divergence(p, q)
        assert 0 < jsd < 0.01

    def test_empty_distributions(self):
        """Both empty → 0."""
        assert DQService._jensen_shannon_divergence({}, {}) == 0.0

    def test_one_empty_one_not(self):
        """One side empty with non-uniform p → measurable JSD."""
        p = {"a": 0.9, "b": 0.1}
        q = {}
        jsd = DQService._jensen_shannon_divergence(p, q)
        # Empty q normalizes to uniform after smoothing; non-uniform p diverges
        assert jsd > 0.05

    def test_symmetry(self):
        """JSD(p, q) == JSD(q, p)."""
        p = {"a": 0.7, "b": 0.2, "c": 0.1}
        q = {"a": 0.3, "b": 0.4, "c": 0.3}
        assert abs(
            DQService._jensen_shannon_divergence(p, q)
            - DQService._jensen_shannon_divergence(q, p)
        ) < 1e-10

    def test_new_category_appears(self):
        """Category in q not in p → positive JSD."""
        p = {"a": 0.6, "b": 0.4}
        q = {"a": 0.4, "b": 0.3, "c": 0.3}
        jsd = DQService._jensen_shannon_divergence(p, q)
        assert jsd > 0.05

    def test_category_disappears(self):
        """Category in p not in q → positive JSD."""
        p = {"a": 0.4, "b": 0.3, "c": 0.3}
        q = {"a": 0.6, "b": 0.4}
        jsd = DQService._jensen_shannon_divergence(p, q)
        assert jsd > 0.05


# ---------------------------------------------------------------------------
# Distribution drift detection
# ---------------------------------------------------------------------------

class TestCheckDistributionDrift:
    """Tests for DQService.check_distribution_drift."""

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_no_drift(self, mock_loader, dq_service):
        """Identical distributions → is_anomaly=False."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.15
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        dist = {"facebook": 0.5, "google": 0.3, "tiktok": 0.2}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=dist,
            current_dist=dist,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert result.check_type == DQCheckType.DISTRIBUTION_DRIFT
        assert result.metadata["jsd"] < 0.001
        assert result.metadata["dimension"] == "channel"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_drift_detected(self, mock_loader, dq_service):
        """Large shift → is_anomaly=True."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.15
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        baseline = {"facebook": 0.8, "google": 0.2}
        current = {"facebook": 0.2, "tiktok": 0.8}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=baseline,
            current_dist=current,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.DISTRIBUTION_DRIFT
        assert result.metadata["jsd"] > 0.15
        assert "drift" in result.message.lower()

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_free_tier_threshold(self, mock_loader, dq_service):
        """Free tier uses 0.15 JSD threshold."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.15
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        # Small shift below 0.15 threshold
        baseline = {"a": 0.5, "b": 0.3, "c": 0.2}
        current = {"a": 0.45, "b": 0.35, "c": 0.2}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=baseline,
            current_dist=current,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert result.metadata["threshold"] == 0.15
        assert result.metadata["billing_tier"] == "free"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_enterprise_tier_threshold(self, mock_loader, dq_service):
        """Enterprise tier uses 0.05 threshold — moderate shift triggers anomaly."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.05
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        # Larger shift that exceeds 0.05 JSD threshold
        baseline = {"a": 0.8, "b": 0.2}
        current = {"a": 0.4, "b": 0.6}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=baseline,
            current_dist=current,
            billing_tier="enterprise",
        )

        assert result.is_anomaly is True
        assert result.metadata["threshold"] == 0.05
        assert result.metadata["billing_tier"] == "enterprise"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_empty_distributions(self, mock_loader, dq_service):
        """Both empty → is_anomaly=False."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.15
        mock_loader.return_value = loader

        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist={},
            current_dist={},
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert result.metadata["jsd"] == 0.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_top_movers_in_metadata(self, mock_loader, dq_service):
        """Top 3 changed categories present in metadata."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.01
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        baseline = {"a": 0.4, "b": 0.3, "c": 0.2, "d": 0.1}
        current = {"a": 0.1, "b": 0.5, "c": 0.2, "d": 0.2}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=baseline,
            current_dist=current,
            billing_tier="free",
        )

        top_movers = result.metadata["top_movers"]
        assert len(top_movers) == 3
        categories = [m["category"] for m in top_movers]
        # 'a' dropped 0.3, 'b' gained 0.2 — both should be in top movers
        assert "a" in categories
        assert "b" in categories

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_severity_high_above_0_8(self, mock_loader, dq_service):
        """High anomaly_score → HIGH severity."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.15
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        baseline = {"a": 1.0}
        current = {"b": 1.0}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=baseline,
            current_dist=current,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.severity == DQSeverity.HIGH
        assert result.metadata["severity_label"] == "high"

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_severity_warning_below_0_8(self, mock_loader, dq_service):
        """Low anomaly_score → WARNING severity."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.15
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        baseline = {"a": 0.5, "b": 0.3, "c": 0.2}
        current = {"a": 0.5, "b": 0.3, "c": 0.2}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=baseline,
            current_dist=current,
            billing_tier="free",
        )

        assert result.severity == DQSeverity.WARNING

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_anomaly_score_capped_at_1(self, mock_loader, dq_service):
        """Extreme drift → anomaly_score capped at 1.0."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.05
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        baseline = {"a": 1.0}
        current = {"b": 1.0}
        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist=baseline,
            current_dist=current,
            billing_tier="enterprise",
        )

        assert result.metadata["anomaly_score"] == 1.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_metadata_fields(self, mock_loader, dq_service):
        """All expected metadata keys present."""
        loader = Mock()
        loader.get_distribution_drift_threshold.return_value = 0.15
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        result = dq_service.check_distribution_drift(
            connector_id="conn-001",
            dimension="channel",
            baseline_dist={"a": 0.5, "b": 0.5},
            current_dist={"a": 0.5, "b": 0.5},
            billing_tier="free",
        )

        expected_keys = {
            "jsd", "anomaly_score", "severity_label", "threshold",
            "billing_tier", "dimension", "top_movers",
        }
        assert expected_keys.issubset(set(result.metadata.keys()))


# ---------------------------------------------------------------------------
# Cardinality shift detection
# ---------------------------------------------------------------------------

class TestCheckCardinalityShift:
    """Tests for DQService.check_cardinality_shift."""

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_no_shift(self, mock_loader, dq_service):
        """Same count → is_anomaly=False."""
        loader = Mock()
        loader.get_cardinality_shift_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        result = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="campaign_id",
            baseline_count=100,
            current_count=100,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert result.check_type == DQCheckType.CARDINALITY_SHIFT
        assert result.metadata["pct_change"] == 0.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_explosion_detected(self, mock_loader, dq_service):
        """Count 100→200 with 50% threshold → anomaly, 'exploded'."""
        loader = Mock()
        loader.get_cardinality_shift_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        result = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="campaign_id",
            baseline_count=100,
            current_count=200,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.metadata["pct_change"] == 100.0
        assert "exploded" in result.message

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_collapse_detected(self, mock_loader, dq_service):
        """Count 100→30 → anomaly, 'collapsed'."""
        loader = Mock()
        loader.get_cardinality_shift_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        result = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="sku",
            baseline_count=100,
            current_count=30,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.metadata["pct_change"] == 70.0
        assert "collapsed" in result.message

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_zero_baseline(self, mock_loader, dq_service):
        """Baseline=0 → is_anomaly=False, no comparison."""
        loader = Mock()
        loader.get_cardinality_shift_threshold.return_value = 50.0
        mock_loader.return_value = loader

        result = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="campaign_id",
            baseline_count=0,
            current_count=50,
            billing_tier="free",
        )

        assert result.is_anomaly is False
        assert "baseline" in result.message.lower()

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_free_vs_enterprise_threshold(self, mock_loader, dq_service):
        """Same 40% shift: passes free (50%), fails enterprise (15%)."""
        loader = Mock()
        loader.get_cardinality_shift_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "low"
        mock_loader.return_value = loader

        result_free = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="campaign_id",
            baseline_count=100,
            current_count=140,
            billing_tier="free",
        )
        assert result_free.is_anomaly is False

        # Now with enterprise threshold
        loader.get_cardinality_shift_threshold.return_value = 15.0
        loader.resolve_severity_label.return_value = "high"

        result_ent = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="campaign_id",
            baseline_count=100,
            current_count=140,
            billing_tier="enterprise",
        )
        assert result_ent.is_anomaly is True

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_anomaly_score_calculation(self, mock_loader, dq_service):
        """Verify score = pct_change / threshold."""
        loader = Mock()
        loader.get_cardinality_shift_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "medium"
        mock_loader.return_value = loader

        # 25% change → score = 25/50 = 0.5
        result = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="campaign_id",
            baseline_count=100,
            current_count=125,
            billing_tier="free",
        )

        assert result.metadata["anomaly_score"] == 0.5
        assert result.metadata["pct_change"] == 25.0

    @patch("src.api.dq.service.get_quality_thresholds_loader")
    def test_severity_mapping(self, mock_loader, dq_service):
        """HIGH when score ≥ 0.8."""
        loader = Mock()
        loader.get_cardinality_shift_threshold.return_value = 50.0
        loader.resolve_severity_label.return_value = "high"
        mock_loader.return_value = loader

        # 50% change → score = 50/50 = 1.0 → high
        result = dq_service.check_cardinality_shift(
            connector_id="conn-001",
            dimension="campaign_id",
            baseline_count=100,
            current_count=150,
            billing_tier="free",
        )

        assert result.is_anomaly is True
        assert result.severity == DQSeverity.HIGH
        assert result.metadata["severity_label"] == "high"
