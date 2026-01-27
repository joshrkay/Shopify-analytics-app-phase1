"""
Tests for data quality threshold logic.

Tests:
- Freshness threshold calculations
- Severity escalation (warning -> high -> critical)
- Source-specific SLA verification
- Anomaly detection logic
- Row count drop detection
- Zero value detection
- Missing days detection
- Negative values detection
- Duplicate primary key detection

Run with: pytest tests/test_dq_thresholds.py -v
"""

import pytest
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.models.dq_models import (
    DQCheckType, DQSeverity, ConnectorSourceType,
    FRESHNESS_THRESHOLDS, get_freshness_threshold, is_critical_source,
)
from src.api.dq.service import DQService, DQEventType


class TestFreshnessThresholds:
    """Tests for freshness SLA thresholds."""

    def test_shopify_orders_2_hour_sla(self):
        """Shopify orders should have 2-hour SLA (120 minutes warning)."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.SHOPIFY_ORDERS,
            DQSeverity.WARNING
        )
        assert threshold == 120

    def test_shopify_refunds_2_hour_sla(self):
        """Shopify refunds should have 2-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.SHOPIFY_REFUNDS,
            DQSeverity.WARNING
        )
        assert threshold == 120

    def test_recharge_2_hour_sla(self):
        """Recharge should have 2-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.RECHARGE,
            DQSeverity.WARNING
        )
        assert threshold == 120

    def test_meta_ads_24_hour_sla(self):
        """Meta Ads should have 24-hour SLA (1440 minutes warning)."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.META_ADS,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_google_ads_24_hour_sla(self):
        """Google Ads should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.GOOGLE_ADS,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_tiktok_ads_24_hour_sla(self):
        """TikTok Ads should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.TIKTOK_ADS,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_pinterest_ads_24_hour_sla(self):
        """Pinterest Ads should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.PINTEREST_ADS,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_snap_ads_24_hour_sla(self):
        """Snap Ads should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.SNAP_ADS,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_amazon_ads_24_hour_sla(self):
        """Amazon Ads should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.AMAZON_ADS,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_klaviyo_24_hour_sla(self):
        """Klaviyo should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.KLAVIYO,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_postscript_24_hour_sla(self):
        """Postscript SMS should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.POSTSCRIPT,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_attentive_24_hour_sla(self):
        """Attentive SMS should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.ATTENTIVE,
            DQSeverity.WARNING
        )
        assert threshold == 1440

    def test_ga4_24_hour_sla(self):
        """GA4 should have 24-hour SLA."""
        threshold = get_freshness_threshold(
            ConnectorSourceType.GA4,
            DQSeverity.WARNING
        )
        assert threshold == 1440


class TestSeverityEscalation:
    """Tests for severity escalation (warning -> high -> critical)."""

    def test_shopify_severity_escalation(self):
        """Shopify should escalate warning (2h) -> high (4h) -> critical (8h)."""
        thresholds = FRESHNESS_THRESHOLDS[ConnectorSourceType.SHOPIFY_ORDERS]

        assert thresholds["warning"] == 120   # 2 hours
        assert thresholds["high"] == 240      # 4 hours (2x)
        assert thresholds["critical"] == 480  # 8 hours (4x)

    def test_ads_severity_escalation(self):
        """Ads should escalate warning (24h) -> high (48h) -> critical (96h)."""
        thresholds = FRESHNESS_THRESHOLDS[ConnectorSourceType.META_ADS]

        assert thresholds["warning"] == 1440   # 24 hours
        assert thresholds["high"] == 2880      # 48 hours (2x)
        assert thresholds["critical"] == 5760  # 96 hours (4x)

    def test_2x_multiplier_for_high(self):
        """High severity should be ~2x warning threshold."""
        for source_type, thresholds in FRESHNESS_THRESHOLDS.items():
            warning = thresholds["warning"]
            high = thresholds["high"]
            # High should be 2x warning
            assert high == warning * 2, f"{source_type}: high ({high}) != warning*2 ({warning*2})"

    def test_4x_multiplier_for_critical(self):
        """Critical severity should be ~4x warning threshold."""
        for source_type, thresholds in FRESHNESS_THRESHOLDS.items():
            warning = thresholds["warning"]
            critical = thresholds["critical"]
            # Critical should be 4x warning
            assert critical == warning * 4, f"{source_type}: critical ({critical}) != warning*4 ({warning*4})"


class TestCriticalSources:
    """Tests for critical source identification."""

    def test_shopify_orders_is_critical(self):
        """Shopify orders should be marked as critical."""
        assert is_critical_source(ConnectorSourceType.SHOPIFY_ORDERS) is True

    def test_shopify_refunds_is_critical(self):
        """Shopify refunds should be marked as critical."""
        assert is_critical_source(ConnectorSourceType.SHOPIFY_REFUNDS) is True

    def test_recharge_is_critical(self):
        """Recharge should be marked as critical."""
        assert is_critical_source(ConnectorSourceType.RECHARGE) is True

    def test_ads_not_critical(self):
        """Ads should not be marked as critical."""
        assert is_critical_source(ConnectorSourceType.META_ADS) is False
        assert is_critical_source(ConnectorSourceType.GOOGLE_ADS) is False
        assert is_critical_source(ConnectorSourceType.TIKTOK_ADS) is False

    def test_klaviyo_not_critical(self):
        """Klaviyo should not be marked as critical."""
        assert is_critical_source(ConnectorSourceType.KLAVIYO) is False

    def test_ga4_not_critical(self):
        """GA4 should not be marked as critical."""
        assert is_critical_source(ConnectorSourceType.GA4) is False


class TestDQServiceSeverityCalculation:
    """Tests for DQ service severity calculation."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def dq_service(self, mock_db_session):
        """Create a DQ service instance."""
        return DQService(mock_db_session, "test_tenant_123")

    def test_fresh_data_no_severity(self, dq_service):
        """Fresh data should have no severity."""
        severity = dq_service._calculate_freshness_severity(
            minutes_since_sync=60,  # 1 hour
            source_type=ConnectorSourceType.SHOPIFY_ORDERS,  # 2 hour SLA
        )
        assert severity is None

    def test_warning_severity_at_threshold(self, dq_service):
        """Data at warning threshold should have warning severity."""
        severity = dq_service._calculate_freshness_severity(
            minutes_since_sync=150,  # 2.5 hours (exceeds 2h warning)
            source_type=ConnectorSourceType.SHOPIFY_ORDERS,
        )
        assert severity == DQSeverity.WARNING

    def test_high_severity_at_2x_threshold(self, dq_service):
        """Data at 2x threshold should have high severity."""
        severity = dq_service._calculate_freshness_severity(
            minutes_since_sync=300,  # 5 hours (exceeds 4h high)
            source_type=ConnectorSourceType.SHOPIFY_ORDERS,
        )
        assert severity == DQSeverity.HIGH

    def test_critical_severity_at_4x_threshold(self, dq_service):
        """Data at 4x threshold should have critical severity."""
        severity = dq_service._calculate_freshness_severity(
            minutes_since_sync=600,  # 10 hours (exceeds 8h critical)
            source_type=ConnectorSourceType.SHOPIFY_ORDERS,
        )
        assert severity == DQSeverity.CRITICAL

    def test_ads_24h_threshold(self, dq_service):
        """Ads at 25 hours should have warning severity."""
        severity = dq_service._calculate_freshness_severity(
            minutes_since_sync=1500,  # 25 hours (exceeds 24h warning)
            source_type=ConnectorSourceType.META_ADS,
        )
        assert severity == DQSeverity.WARNING


class TestAnomalyDetection:
    """Tests for anomaly detection logic."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        session = MagicMock()
        # Mock query to return None for connector lookups
        session.query.return_value.filter.return_value.first.return_value = None
        return session

    @pytest.fixture
    def dq_service(self, mock_db_session):
        """Create a DQ service instance."""
        return DQService(mock_db_session, "test_tenant_123")

    def test_row_count_drop_50_percent(self, dq_service):
        """50% row count drop should trigger anomaly."""
        result = dq_service.check_row_count_drop(
            connector_id="conn_123",
            current_count=50,
            previous_count=100,
            threshold_percent=50.0,
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.ROW_COUNT_DROP
        assert result.severity == DQSeverity.WARNING

    def test_row_count_drop_75_percent_high_severity(self, dq_service):
        """75% row count drop should have high severity."""
        result = dq_service.check_row_count_drop(
            connector_id="conn_123",
            current_count=25,
            previous_count=100,
            threshold_percent=50.0,
        )

        assert result.is_anomaly is True
        assert result.severity == DQSeverity.HIGH

    def test_row_count_drop_below_threshold(self, dq_service):
        """30% row count drop should not trigger anomaly."""
        result = dq_service.check_row_count_drop(
            connector_id="conn_123",
            current_count=70,
            previous_count=100,
            threshold_percent=50.0,
        )

        assert result.is_anomaly is False

    def test_zero_spend_anomaly(self, dq_service):
        """Zero spend when previously non-zero should trigger anomaly."""
        result = dq_service.check_zero_spend(
            connector_id="conn_123",
            current_spend=Decimal("0"),
            previous_spend=Decimal("1000.00"),
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.ZERO_SPEND
        assert result.severity == DQSeverity.HIGH

    def test_zero_spend_when_already_zero(self, dq_service):
        """Zero spend when previously zero should not trigger anomaly."""
        result = dq_service.check_zero_spend(
            connector_id="conn_123",
            current_spend=Decimal("0"),
            previous_spend=Decimal("0"),
        )

        assert result.is_anomaly is False

    def test_non_zero_spend_no_anomaly(self, dq_service):
        """Non-zero spend should not trigger anomaly."""
        result = dq_service.check_zero_spend(
            connector_id="conn_123",
            current_spend=Decimal("500.00"),
            previous_spend=Decimal("1000.00"),
        )

        assert result.is_anomaly is False

    def test_zero_orders_anomaly(self, dq_service):
        """Zero orders when previously non-zero should trigger anomaly."""
        result = dq_service.check_zero_orders(
            connector_id="conn_123",
            current_orders=0,
            previous_orders=50,
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.ZERO_ORDERS
        assert result.severity == DQSeverity.CRITICAL  # Orders are critical

    def test_missing_days_detection(self, dq_service):
        """Missing days should trigger anomaly."""
        today = date.today()
        dates_present = [today - timedelta(days=i) for i in [0, 1, 3, 4, 5]]  # Missing day 2
        expected_dates = [today - timedelta(days=i) for i in range(6)]

        result = dq_service.check_missing_days(
            connector_id="conn_123",
            dates_present=dates_present,
            expected_dates=expected_dates,
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.MISSING_DAYS

    def test_no_missing_days(self, dq_service):
        """All days present should not trigger anomaly."""
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(7)]

        result = dq_service.check_missing_days(
            connector_id="conn_123",
            dates_present=dates,
            expected_dates=dates,
        )

        assert result.is_anomaly is False

    def test_negative_values_detection(self, dq_service):
        """Negative values should trigger anomaly."""
        result = dq_service.check_negative_values(
            connector_id="conn_123",
            field_name="revenue",
            negative_count=5,
            total_count=1000,
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.NEGATIVE_VALUES

    def test_no_negative_values(self, dq_service):
        """No negative values should not trigger anomaly."""
        result = dq_service.check_negative_values(
            connector_id="conn_123",
            field_name="revenue",
            negative_count=0,
            total_count=1000,
        )

        assert result.is_anomaly is False

    def test_duplicate_primary_keys_detection(self, dq_service):
        """Duplicate primary keys should trigger anomaly."""
        result = dq_service.check_duplicate_primary_keys(
            connector_id="conn_123",
            duplicate_count=10,
            total_count=1000,
        )

        assert result.is_anomaly is True
        assert result.check_type == DQCheckType.DUPLICATE_PRIMARY_KEY

    def test_no_duplicate_primary_keys(self, dq_service):
        """No duplicates should not trigger anomaly."""
        result = dq_service.check_duplicate_primary_keys(
            connector_id="conn_123",
            duplicate_count=0,
            total_count=1000,
        )

        assert result.is_anomaly is False


class TestStalenessTransitions:
    """Integration tests for staleness state transitions."""

    @pytest.fixture
    def mock_db_session(self):
        """Create a mock database session."""
        return MagicMock()

    def test_stale_shopify_warning_transition(self, mock_db_session):
        """Simulate Shopify stale > 2h => warning transition."""
        # Create mock connector
        mock_connector = MagicMock()
        mock_connector.id = "conn_123"
        mock_connector.connection_name = "Shopify"
        mock_connector.source_type = "shopify_orders"
        mock_connector.is_enabled = True
        mock_connector.status = "active"
        # 3 hours ago
        mock_connector.last_sync_at = datetime.now(timezone.utc) - timedelta(hours=3)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_connector

        service = DQService(mock_db_session, "test_tenant")
        result = service.check_freshness("conn_123")

        assert result.is_fresh is False
        assert result.severity == DQSeverity.WARNING

    def test_stale_shopify_high_transition(self, mock_db_session):
        """Simulate Shopify stale > 4h => high transition."""
        mock_connector = MagicMock()
        mock_connector.id = "conn_123"
        mock_connector.connection_name = "Shopify"
        mock_connector.source_type = "shopify_orders"
        mock_connector.is_enabled = True
        mock_connector.status = "active"
        # 5 hours ago
        mock_connector.last_sync_at = datetime.now(timezone.utc) - timedelta(hours=5)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_connector

        service = DQService(mock_db_session, "test_tenant")
        result = service.check_freshness("conn_123")

        assert result.is_fresh is False
        assert result.severity == DQSeverity.HIGH

    def test_stale_shopify_critical_transition(self, mock_db_session):
        """Simulate Shopify stale > 8h => critical transition."""
        mock_connector = MagicMock()
        mock_connector.id = "conn_123"
        mock_connector.connection_name = "Shopify"
        mock_connector.source_type = "shopify_orders"
        mock_connector.is_enabled = True
        mock_connector.status = "active"
        # 10 hours ago
        mock_connector.last_sync_at = datetime.now(timezone.utc) - timedelta(hours=10)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_connector

        service = DQService(mock_db_session, "test_tenant")
        result = service.check_freshness("conn_123")

        assert result.is_fresh is False
        assert result.severity == DQSeverity.CRITICAL


class TestRetentionCleanup:
    """Tests for retention cleanup job logic."""

    def test_retention_period_is_13_months(self):
        """Verify default retention period is 13 months."""
        from src.jobs.retention_cleanup import DQ_RETENTION_MONTHS
        assert DQ_RETENTION_MONTHS == 13


class TestTenantIsolation:
    """Tests for tenant isolation in DQ service."""

    def test_service_requires_tenant_id(self):
        """DQ service should require tenant_id."""
        mock_db = MagicMock()

        with pytest.raises(ValueError, match="tenant_id is required"):
            DQService(mock_db, "")

        with pytest.raises(ValueError, match="tenant_id is required"):
            DQService(mock_db, None)

    def test_service_stores_tenant_id(self):
        """DQ service should store tenant_id."""
        mock_db = MagicMock()
        service = DQService(mock_db, "tenant_123")

        assert service.tenant_id == "tenant_123"
