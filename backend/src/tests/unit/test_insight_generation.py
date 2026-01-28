"""
Unit tests for AI Insight Generation Service.

Tests cover:
- Threshold configuration
- Template rendering
- Detection logic (spend, ROAS, CAC, AOV, divergence)
- Confidence scoring
- Content hash deduplication

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.models.ai_insight import InsightType, InsightSeverity
from src.services.insight_thresholds import (
    InsightThresholds,
    DEFAULT_THRESHOLDS,
    ENTERPRISE_THRESHOLDS,
    get_thresholds_for_tier,
)
from src.services.insight_generation_service import (
    InsightGenerationService,
    MetricChange,
    DetectedInsight,
)
from src.services.insight_templates import (
    render_insight_summary,
    render_why_it_matters,
    get_metric_display_name,
    format_timeframe_human,
    CURRENCY_SYMBOLS,
    METRIC_DISPLAY_NAMES,
    WHY_IT_MATTERS_TEMPLATES,
    _format_timeframe,
)


class TestInsightThresholds:
    """Tests for threshold configuration."""

    def test_default_thresholds_values(self):
        """Test default threshold values."""
        t = DEFAULT_THRESHOLDS
        assert t.spend_anomaly_pct == 15.0
        assert t.spend_critical_pct == 30.0
        assert t.roas_change_pct == 15.0
        assert t.divergence_pct == 10.0
        assert t.min_spend_for_analysis == 100.0

    def test_enterprise_thresholds_more_sensitive(self):
        """Test enterprise thresholds are more sensitive."""
        assert ENTERPRISE_THRESHOLDS.spend_anomaly_pct < DEFAULT_THRESHOLDS.spend_anomaly_pct
        assert ENTERPRISE_THRESHOLDS.roas_change_pct < DEFAULT_THRESHOLDS.roas_change_pct

    def test_get_thresholds_for_tier_enterprise(self):
        """Test getting thresholds for enterprise tier."""
        t = get_thresholds_for_tier("enterprise")
        assert t == ENTERPRISE_THRESHOLDS

    def test_get_thresholds_for_tier_default(self):
        """Test getting thresholds for non-enterprise tier."""
        assert get_thresholds_for_tier("free") == DEFAULT_THRESHOLDS
        assert get_thresholds_for_tier("growth") == DEFAULT_THRESHOLDS
        assert get_thresholds_for_tier("pro") == DEFAULT_THRESHOLDS

    def test_thresholds_immutable(self):
        """Test thresholds are frozen (immutable)."""
        with pytest.raises(Exception):
            DEFAULT_THRESHOLDS.spend_anomaly_pct = 99.0


class TestMetricChange:
    """Tests for MetricChange dataclass."""

    def test_to_dict(self):
        """Test MetricChange serialization."""
        mc = MetricChange(
            metric_name="spend",
            current_value=Decimal("1500"),
            prior_value=Decimal("1000"),
            delta=Decimal("500"),
            delta_pct=50.0,
            timeframe="week_over_week",
        )

        d = mc.to_dict()
        assert d["metric"] == "spend"
        assert d["current_value"] == 1500.0
        assert d["prior_value"] == 1000.0
        assert d["delta"] == 500.0
        assert d["delta_pct"] == 50.0
        assert d["timeframe"] == "week_over_week"


class TestTemplateRendering:
    """Tests for template-based summary generation."""

    def test_format_timeframe(self):
        """Test timeframe formatting."""
        assert _format_timeframe("week_over_week") == "week-over-week"
        assert _format_timeframe("month_over_month") == "month-over-month"
        assert _format_timeframe("unknown_type") == "unknown type"

    def test_currency_symbols(self):
        """Test currency symbol mapping."""
        assert CURRENCY_SYMBOLS["USD"] == "$"
        assert CURRENCY_SYMBOLS["EUR"] == "\u20ac"
        assert CURRENCY_SYMBOLS["GBP"] == "\u00a3"

    def test_render_spend_increase_warning(self):
        """Test spend increase warning summary."""
        detected = DetectedInsight(
            insight_type=InsightType.SPEND_ANOMALY,
            severity=InsightSeverity.WARNING,
            metrics=[
                MetricChange(
                    metric_name="spend",
                    current_value=Decimal("1500"),
                    prior_value=Decimal("1000"),
                    delta=Decimal("500"),
                    delta_pct=50.0,
                    timeframe="week_over_week",
                )
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            platform="meta_ads",
            currency="USD",
            confidence_score=0.85,
        )

        summary = render_insight_summary(detected)

        assert "50.0%" in summary
        assert "increased" in summary.lower()
        assert "$1,500" in summary
        assert "Meta Ads" in summary

    def test_render_roas_decline_critical(self):
        """Test ROAS decline critical summary."""
        detected = DetectedInsight(
            insight_type=InsightType.ROAS_CHANGE,
            severity=InsightSeverity.CRITICAL,
            metrics=[
                MetricChange(
                    metric_name="gross_roas",
                    current_value=Decimal("1.5"),
                    prior_value=Decimal("3.0"),
                    delta=Decimal("-1.5"),
                    delta_pct=-50.0,
                    timeframe="week_over_week",
                )
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            currency="USD",
            confidence_score=0.9,
        )

        summary = render_insight_summary(detected)

        assert "50.0%" in summary
        assert "1.50x" in summary
        assert "declined" in summary.lower() or "ROAS" in summary

    def test_render_divergence_insight(self):
        """Test revenue vs spend divergence summary."""
        detected = DetectedInsight(
            insight_type=InsightType.REVENUE_VS_SPEND_DIVERGENCE,
            severity=InsightSeverity.WARNING,
            metrics=[
                MetricChange(
                    metric_name="net_revenue",
                    current_value=Decimal("8000"),
                    prior_value=Decimal("10000"),
                    delta=Decimal("-2000"),
                    delta_pct=-20.0,
                    timeframe="week_over_week",
                ),
                MetricChange(
                    metric_name="spend",
                    current_value=Decimal("1500"),
                    prior_value=Decimal("1000"),
                    delta=Decimal("500"),
                    delta_pct=50.0,
                    timeframe="week_over_week",
                ),
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            currency="USD",
            confidence_score=0.85,
        )

        summary = render_insight_summary(detected)

        assert "revenue" in summary.lower()
        assert "spend" in summary.lower()

    def test_render_fallback_for_empty_metrics(self):
        """Test fallback when no metrics provided."""
        detected = DetectedInsight(
            insight_type=InsightType.SPEND_ANOMALY,
            severity=InsightSeverity.WARNING,
            metrics=[],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            confidence_score=0.5,
        )

        summary = render_insight_summary(detected)

        assert "spend anomaly" in summary.lower()


class TestInsightGenerationService:
    """Tests for InsightGenerationService."""

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        return MagicMock()

    @pytest.fixture
    def service(self, mock_db_session):
        """Create service instance."""
        return InsightGenerationService(
            db_session=mock_db_session,
            tenant_id="test-tenant-123",
            thresholds=InsightThresholds(spend_anomaly_pct=15.0),
        )

    def test_service_requires_tenant_id(self, mock_db_session):
        """Test service raises error without tenant_id."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            InsightGenerationService(mock_db_session, tenant_id="")

    def test_calculate_severity_info(self, service):
        """Test severity calculation returns INFO below threshold."""
        severity = service._calculate_severity(10.0, 15.0, 30.0)
        assert severity == InsightSeverity.INFO

    def test_calculate_severity_warning(self, service):
        """Test severity calculation returns WARNING at threshold."""
        severity = service._calculate_severity(20.0, 15.0, 30.0)
        assert severity == InsightSeverity.WARNING

    def test_calculate_severity_critical(self, service):
        """Test severity calculation returns CRITICAL above critical threshold."""
        severity = service._calculate_severity(35.0, 15.0, 30.0)
        assert severity == InsightSeverity.CRITICAL

    def test_calculate_confidence_low_values(self, service):
        """Test low confidence for small values."""
        confidence = service._calculate_confidence(20.0, 50, 40)
        assert confidence == 0.5

    def test_calculate_confidence_high_change(self, service):
        """Test high confidence for large changes."""
        confidence = service._calculate_confidence(60.0, 10000, 6000)
        assert confidence == 0.95

    def test_calculate_confidence_moderate(self, service):
        """Test moderate confidence for medium changes."""
        confidence = service._calculate_confidence(20.0, 5000, 4000)
        assert confidence == 0.75

    def test_generate_content_hash_deterministic(self, service):
        """Test same inputs produce same hash."""
        detected = DetectedInsight(
            insight_type=InsightType.SPEND_ANOMALY,
            severity=InsightSeverity.WARNING,
            metrics=[
                MetricChange(
                    metric_name="spend",
                    current_value=Decimal("1500"),
                    prior_value=Decimal("1000"),
                    delta=Decimal("500"),
                    delta_pct=50.0,
                    timeframe="week_over_week",
                )
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            platform="meta_ads",
            currency="USD",
            confidence_score=0.85,
        )

        hash1 = service._generate_content_hash(detected)
        hash2 = service._generate_content_hash(detected)

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_generate_content_hash_different_for_different_inputs(self, service):
        """Test different inputs produce different hashes."""
        detected1 = DetectedInsight(
            insight_type=InsightType.SPEND_ANOMALY,
            severity=InsightSeverity.WARNING,
            metrics=[
                MetricChange(
                    metric_name="spend",
                    current_value=Decimal("1500"),
                    prior_value=Decimal("1000"),
                    delta=Decimal("500"),
                    delta_pct=50.0,
                    timeframe="week_over_week",
                )
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            platform="meta_ads",
            currency="USD",
            confidence_score=0.85,
        )

        detected2 = DetectedInsight(
            insight_type=InsightType.ROAS_CHANGE,  # Different type
            severity=InsightSeverity.WARNING,
            metrics=[
                MetricChange(
                    metric_name="roas",
                    current_value=Decimal("2.5"),
                    prior_value=Decimal("2.0"),
                    delta=Decimal("0.5"),
                    delta_pct=25.0,
                    timeframe="week_over_week",
                )
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            platform="meta_ads",
            currency="USD",
            confidence_score=0.85,
        )

        hash1 = service._generate_content_hash(detected1)
        hash2 = service._generate_content_hash(detected2)

        assert hash1 != hash2


class TestSpendAnomalyDetection:
    """Tests for spend anomaly detection."""

    @pytest.fixture
    def service(self):
        """Create service with mock session."""
        return InsightGenerationService(
            db_session=MagicMock(),
            tenant_id="test-tenant",
            thresholds=InsightThresholds(
                spend_anomaly_pct=15.0,
                spend_critical_pct=30.0,
                min_spend_for_analysis=100.0,
            ),
        )

    def test_detects_spend_increase_above_threshold(self, service):
        """Test spend increase above threshold is detected."""
        marketing_data = [
            {
                "platform": "meta_ads",
                "currency": "USD",
                "campaign_id": None,
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
                "spend": 1500,
                "prior_spend": 1000,
                "spend_change": 500,
                "spend_change_pct": 50.0,
            }
        ]

        insights = service._detect_spend_anomalies(marketing_data, "weekly")

        assert len(insights) == 1
        assert insights[0].insight_type == InsightType.SPEND_ANOMALY
        assert insights[0].severity == InsightSeverity.CRITICAL  # 50% > 30%

    def test_no_detection_below_threshold(self, service):
        """Test changes below threshold are not detected."""
        marketing_data = [
            {
                "platform": "meta_ads",
                "currency": "USD",
                "campaign_id": None,
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
                "spend": 1100,
                "prior_spend": 1000,
                "spend_change": 100,
                "spend_change_pct": 10.0,  # Below 15%
            }
        ]

        insights = service._detect_spend_anomalies(marketing_data, "weekly")

        assert len(insights) == 0

    def test_skips_small_spend_values(self, service):
        """Test small spend values are skipped."""
        marketing_data = [
            {
                "platform": "meta_ads",
                "currency": "USD",
                "campaign_id": None,
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
                "spend": 50,  # Below min_spend_for_analysis
                "prior_spend": 25,
                "spend_change": 25,
                "spend_change_pct": 100.0,
            }
        ]

        insights = service._detect_spend_anomalies(marketing_data, "weekly")

        assert len(insights) == 0


class TestROASDetection:
    """Tests for ROAS change detection."""

    @pytest.fixture
    def service(self):
        """Create service with mock session."""
        return InsightGenerationService(
            db_session=MagicMock(),
            tenant_id="test-tenant",
            thresholds=InsightThresholds(
                roas_change_pct=15.0,
                roas_critical_pct=25.0,
            ),
        )

    def test_detects_roas_decline(self, service):
        """Test ROAS decline is detected."""
        marketing_data = [
            {
                "platform": "google_ads",
                "currency": "USD",
                "campaign_id": "camp-123",
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
                "gross_roas": 2.0,
                "prior_gross_roas": 3.0,
                "gross_roas_change": -1.0,
                "gross_roas_change_pct": -33.3,
            }
        ]

        insights = service._detect_roas_changes(marketing_data, "weekly")

        assert len(insights) == 1
        assert insights[0].insight_type == InsightType.ROAS_CHANGE
        assert insights[0].metrics[0].delta_pct == -33.3

    def test_skips_zero_roas(self, service):
        """Test zero ROAS values are skipped."""
        marketing_data = [
            {
                "platform": "google_ads",
                "currency": "USD",
                "campaign_id": None,
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
                "gross_roas": 0,
                "prior_gross_roas": 0,
                "gross_roas_change": 0,
                "gross_roas_change_pct": 0,
            }
        ]

        insights = service._detect_roas_changes(marketing_data, "weekly")

        assert len(insights) == 0


class TestDivergenceDetection:
    """Tests for revenue vs spend divergence detection."""

    @pytest.fixture
    def service(self):
        """Create service with mock session."""
        return InsightGenerationService(
            db_session=MagicMock(),
            tenant_id="test-tenant",
            thresholds=InsightThresholds(
                divergence_pct=10.0,
                min_revenue_for_analysis=100.0,
            ),
        )

    def test_detects_divergence_revenue_down_spend_up(self, service):
        """Test divergence when revenue decreases while spend increases."""
        marketing_data = [
            {
                "currency": "USD",
                "spend": 1500,
                "prior_spend": 1000,
                "spend_change_pct": 50.0,
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
            }
        ]

        revenue_data = [
            {
                "currency": "USD",
                "net_revenue": 8000,
                "prior_net_revenue": 10000,
                "net_revenue_change": -2000,
                "net_revenue_change_pct": -20.0,
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
            }
        ]

        insights = service._detect_revenue_spend_divergence(
            marketing_data, revenue_data, "weekly"
        )

        assert len(insights) == 1
        assert insights[0].insight_type == InsightType.REVENUE_VS_SPEND_DIVERGENCE
        assert len(insights[0].metrics) == 2

    def test_no_divergence_same_direction(self, service):
        """Test no divergence when both move same direction."""
        marketing_data = [
            {
                "currency": "USD",
                "spend": 1500,
                "prior_spend": 1000,
                "spend_change_pct": 50.0,
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
            }
        ]

        revenue_data = [
            {
                "currency": "USD",
                "net_revenue": 12000,
                "prior_net_revenue": 10000,
                "net_revenue_change": 2000,
                "net_revenue_change_pct": 20.0,  # Both increasing
                "period_start": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "period_end": datetime(2024, 1, 7, tzinfo=timezone.utc),
                "comparison_type": "week_over_week",
            }
        ]

        insights = service._detect_revenue_spend_divergence(
            marketing_data, revenue_data, "weekly"
        )

        assert len(insights) == 0


# =============================================================================
# Story 8.2 - Explainability Tests
# =============================================================================


class TestWhyItMattersRendering:
    """Tests for why_it_matters template rendering (Story 8.2)."""

    def test_render_spend_increase_warning(self):
        """Test why_it_matters for spend increase warning."""
        detected = DetectedInsight(
            insight_type=InsightType.SPEND_ANOMALY,
            severity=InsightSeverity.WARNING,
            metrics=[
                MetricChange(
                    metric_name="spend",
                    current_value=Decimal("1500"),
                    prior_value=Decimal("1000"),
                    delta=Decimal("500"),
                    delta_pct=50.0,
                    timeframe="week_over_week",
                )
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            confidence_score=0.85,
        )

        result = render_why_it_matters(detected)

        assert result is not None
        assert len(result) > 0
        assert "spend" in result.lower()

    def test_render_roas_decline_critical(self):
        """Test why_it_matters for ROAS decline critical."""
        detected = DetectedInsight(
            insight_type=InsightType.ROAS_CHANGE,
            severity=InsightSeverity.CRITICAL,
            metrics=[
                MetricChange(
                    metric_name="gross_roas",
                    current_value=Decimal("1.5"),
                    prior_value=Decimal("3.0"),
                    delta=Decimal("-1.5"),
                    delta_pct=-50.0,
                    timeframe="week_over_week",
                )
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            confidence_score=0.9,
        )

        result = render_why_it_matters(detected)

        assert "ROAS" in result or "revenue" in result.lower()
        assert "profitability" in result.lower() or "dollar" in result.lower()

    def test_render_divergence_warning(self):
        """Test why_it_matters for revenue vs spend divergence."""
        detected = DetectedInsight(
            insight_type=InsightType.REVENUE_VS_SPEND_DIVERGENCE,
            severity=InsightSeverity.WARNING,
            metrics=[
                MetricChange(
                    metric_name="net_revenue",
                    current_value=Decimal("8000"),
                    prior_value=Decimal("10000"),
                    delta=Decimal("-2000"),
                    delta_pct=-20.0,
                    timeframe="week_over_week",
                ),
            ],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            confidence_score=0.85,
        )

        result = render_why_it_matters(detected)

        assert "revenue" in result.lower() or "spend" in result.lower()

    def test_render_fallback_for_empty_metrics(self):
        """Test fallback why_it_matters when no metrics."""
        detected = DetectedInsight(
            insight_type=InsightType.SPEND_ANOMALY,
            severity=InsightSeverity.INFO,
            metrics=[],
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            confidence_score=0.5,
        )

        result = render_why_it_matters(detected)

        # Should return a valid fallback message
        assert result is not None
        assert len(result) > 0

    def test_all_insight_types_have_why_it_matters_templates(self):
        """Test every insight type has why_it_matters templates."""
        for insight_type in InsightType:
            assert insight_type in WHY_IT_MATTERS_TEMPLATES, \
                f"Missing why_it_matters templates for {insight_type}"


class TestMetricDisplayNames:
    """Tests for metric display name mapping (Story 8.2)."""

    def test_known_metric_names(self):
        """Test known metrics return business-friendly names."""
        assert get_metric_display_name("gross_roas") == "Return on Ad Spend (ROAS)"
        assert get_metric_display_name("cac") == "Customer Acquisition Cost (CAC)"
        assert get_metric_display_name("aov") == "Average Order Value (AOV)"
        assert get_metric_display_name("spend") == "Marketing Spend"
        assert get_metric_display_name("net_revenue") == "Net Revenue"

    def test_unknown_metric_fallback(self):
        """Test unknown metrics get title-cased fallback."""
        assert get_metric_display_name("unknown_metric") == "Unknown Metric"
        assert get_metric_display_name("some_new_metric") == "Some New Metric"

    def test_all_metrics_defined(self):
        """Test all expected metrics have display names."""
        expected = ["spend", "gross_roas", "net_roas", "cac", "aov", "net_revenue"]
        for metric in expected:
            assert metric in METRIC_DISPLAY_NAMES


class TestTimeframeFormatting:
    """Tests for human-readable timeframe formatting (Story 8.2)."""

    def test_known_period_types(self):
        """Test known period types return human-readable strings."""
        assert format_timeframe_human("last_7_days") == "Last 7 days"
        assert format_timeframe_human("last_14_days") == "Last 14 days"
        assert format_timeframe_human("last_30_days") == "Last 30 days"
        assert format_timeframe_human("weekly") == "Last 7 days"
        assert format_timeframe_human("monthly") == "Last 30 days"

    def test_unknown_period_type_fallback(self):
        """Test unknown period types get title-cased fallback."""
        assert format_timeframe_human("custom_period") == "Custom Period"
