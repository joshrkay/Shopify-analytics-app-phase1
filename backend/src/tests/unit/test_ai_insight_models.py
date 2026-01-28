"""
Unit tests for AI Insight models.

Tests cover:
- AIInsight model instantiation and properties
- InsightJob model instantiation and state transitions
- Enum value validation
- Model method behavior

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta

from src.models.ai_insight import (
    AIInsight,
    InsightType,
    InsightSeverity,
)
from src.models.insight_job import (
    InsightJob,
    InsightJobStatus,
    InsightJobCadence,
)


class TestInsightTypeEnum:
    """Tests for InsightType enumeration."""

    def test_all_insight_types_defined(self):
        """Verify all expected insight types exist."""
        expected_types = [
            "spend_anomaly",
            "roas_change",
            "revenue_vs_spend_divergence",
            "channel_mix_shift",
            "cac_anomaly",
            "aov_change",
        ]
        actual_types = [t.value for t in InsightType]
        assert sorted(actual_types) == sorted(expected_types)

    def test_insight_type_is_string_enum(self):
        """Verify InsightType inherits from str."""
        assert isinstance(InsightType.SPEND_ANOMALY, str)
        assert InsightType.SPEND_ANOMALY == "spend_anomaly"


class TestInsightSeverityEnum:
    """Tests for InsightSeverity enumeration."""

    def test_all_severities_defined(self):
        """Verify all expected severities exist."""
        expected = ["info", "warning", "critical"]
        actual = [s.value for s in InsightSeverity]
        assert sorted(actual) == sorted(expected)

    def test_severity_is_string_enum(self):
        """Verify InsightSeverity inherits from str."""
        assert isinstance(InsightSeverity.INFO, str)
        assert InsightSeverity.CRITICAL == "critical"


class TestAIInsightModel:
    """Tests for AIInsight model."""

    @pytest.fixture
    def sample_insight(self):
        """Create a sample AIInsight instance."""
        return AIInsight(
            id=str(uuid.uuid4()),
            tenant_id="test-tenant-123",
            insight_type=InsightType.SPEND_ANOMALY,
            severity=InsightSeverity.WARNING,
            summary="Marketing spend increased by 25% week-over-week.",
            supporting_metrics=[
                {
                    "metric": "spend",
                    "current_value": 1250.0,
                    "prior_value": 1000.0,
                    "delta": 250.0,
                    "delta_pct": 25.0,
                    "timeframe": "week_over_week",
                }
            ],
            confidence_score=0.85,
            period_type="weekly",
            period_start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            period_end=datetime(2024, 1, 7, tzinfo=timezone.utc),
            comparison_type="week_over_week",
            platform="meta_ads",
            currency="USD",
            content_hash="abc123def456",
            generated_at=datetime.now(timezone.utc),
            # Defaults (SQLAlchemy defaults only apply at DB level)
            is_read=0,
            is_dismissed=0,
        )

    def test_insight_instantiation(self, sample_insight):
        """Test AIInsight can be instantiated with required fields."""
        assert sample_insight.tenant_id == "test-tenant-123"
        assert sample_insight.insight_type == InsightType.SPEND_ANOMALY
        assert sample_insight.severity == InsightSeverity.WARNING
        assert sample_insight.confidence_score == 0.85

    def test_insight_is_unread_default(self, sample_insight):
        """Test new insights are unread by default."""
        assert sample_insight.is_read == 0
        assert sample_insight.is_unread is True

    def test_insight_is_active_default(self, sample_insight):
        """Test new insights are active (not dismissed) by default."""
        assert sample_insight.is_dismissed == 0
        assert sample_insight.is_active is True

    def test_mark_read(self, sample_insight):
        """Test marking insight as read."""
        assert sample_insight.is_unread is True
        sample_insight.mark_read()
        assert sample_insight.is_read == 1
        assert sample_insight.is_unread is False

    def test_mark_dismissed(self, sample_insight):
        """Test marking insight as dismissed."""
        assert sample_insight.is_active is True
        sample_insight.mark_dismissed()
        assert sample_insight.is_dismissed == 1
        assert sample_insight.is_active is False

    def test_supporting_metrics_structure(self, sample_insight):
        """Test supporting_metrics contains expected structure."""
        metrics = sample_insight.supporting_metrics
        assert isinstance(metrics, list)
        assert len(metrics) == 1

        metric = metrics[0]
        assert "metric" in metric
        assert "current_value" in metric
        assert "prior_value" in metric
        assert "delta" in metric
        assert "delta_pct" in metric
        assert "timeframe" in metric

    def test_repr(self, sample_insight):
        """Test __repr__ method."""
        repr_str = repr(sample_insight)
        assert "AIInsight" in repr_str
        assert "tenant_id=test-tenant-123" in repr_str
        assert "spend_anomaly" in repr_str
        assert "warning" in repr_str


class TestInsightJobStatusEnum:
    """Tests for InsightJobStatus enumeration."""

    def test_all_statuses_defined(self):
        """Verify all expected statuses exist."""
        expected = ["queued", "running", "failed", "success", "skipped"]
        actual = [s.value for s in InsightJobStatus]
        assert sorted(actual) == sorted(expected)


class TestInsightJobCadenceEnum:
    """Tests for InsightJobCadence enumeration."""

    def test_all_cadences_defined(self):
        """Verify daily and hourly cadences exist."""
        expected = ["daily", "hourly"]
        actual = [c.value for c in InsightJobCadence]
        assert sorted(actual) == sorted(expected)


class TestInsightJobModel:
    """Tests for InsightJob model."""

    @pytest.fixture
    def sample_job(self):
        """Create a sample InsightJob instance."""
        return InsightJob(
            job_id=str(uuid.uuid4()),
            tenant_id="test-tenant-123",
            cadence=InsightJobCadence.DAILY,
            status=InsightJobStatus.QUEUED,
            # Defaults (SQLAlchemy defaults only apply at DB level)
            insights_generated=0,
            job_metadata={},
        )

    def test_job_instantiation(self, sample_job):
        """Test InsightJob can be instantiated with required fields."""
        assert sample_job.tenant_id == "test-tenant-123"
        assert sample_job.cadence == InsightJobCadence.DAILY
        assert sample_job.status == InsightJobStatus.QUEUED

    def test_job_is_active_when_queued(self, sample_job):
        """Test job is active when status is QUEUED."""
        sample_job.status = InsightJobStatus.QUEUED
        assert sample_job.is_active is True
        assert sample_job.is_terminal is False

    def test_job_is_active_when_running(self, sample_job):
        """Test job is active when status is RUNNING."""
        sample_job.status = InsightJobStatus.RUNNING
        assert sample_job.is_active is True
        assert sample_job.is_terminal is False

    def test_job_is_terminal_when_success(self, sample_job):
        """Test job is terminal when status is SUCCESS."""
        sample_job.status = InsightJobStatus.SUCCESS
        assert sample_job.is_active is False
        assert sample_job.is_terminal is True

    def test_job_is_terminal_when_failed(self, sample_job):
        """Test job is terminal when status is FAILED."""
        sample_job.status = InsightJobStatus.FAILED
        assert sample_job.is_active is False
        assert sample_job.is_terminal is True

    def test_job_is_terminal_when_skipped(self, sample_job):
        """Test job is terminal when status is SKIPPED."""
        sample_job.status = InsightJobStatus.SKIPPED
        assert sample_job.is_active is False
        assert sample_job.is_terminal is True

    def test_mark_running(self, sample_job):
        """Test marking job as running sets status and timestamp."""
        assert sample_job.started_at is None
        sample_job.mark_running()
        assert sample_job.status == InsightJobStatus.RUNNING
        assert sample_job.started_at is not None

    def test_mark_success(self, sample_job):
        """Test marking job as successful sets results."""
        sample_job.mark_running()
        sample_job.mark_success(insights_generated=5)

        assert sample_job.status == InsightJobStatus.SUCCESS
        assert sample_job.insights_generated == 5
        assert sample_job.completed_at is not None

    def test_mark_success_with_metadata(self, sample_job):
        """Test marking job as successful with metadata."""
        sample_job.mark_running()
        sample_job.mark_success(
            insights_generated=3,
            metadata={"periods_analyzed": ["weekly", "monthly"]}
        )

        assert sample_job.status == InsightJobStatus.SUCCESS
        assert sample_job.insights_generated == 3
        assert sample_job.job_metadata.get("periods_analyzed") == ["weekly", "monthly"]

    def test_mark_failed(self, sample_job):
        """Test marking job as failed sets error message."""
        sample_job.mark_running()
        sample_job.mark_failed("Database connection timeout")

        assert sample_job.status == InsightJobStatus.FAILED
        assert sample_job.error_message == "Database connection timeout"
        assert sample_job.completed_at is not None

    def test_mark_failed_truncates_long_error(self, sample_job):
        """Test error message is truncated to 1000 chars."""
        sample_job.mark_running()
        long_error = "x" * 2000
        sample_job.mark_failed(long_error)

        assert len(sample_job.error_message) == 1000

    def test_mark_skipped(self, sample_job):
        """Test marking job as skipped with reason."""
        sample_job.mark_skipped("No data available for period")

        assert sample_job.status == InsightJobStatus.SKIPPED
        assert sample_job.job_metadata.get("skip_reason") == "No data available for period"
        assert sample_job.completed_at is not None

    def test_repr(self, sample_job):
        """Test __repr__ method."""
        repr_str = repr(sample_job)
        assert "InsightJob" in repr_str
        assert "tenant_id=test-tenant-123" in repr_str
        assert "queued" in repr_str

    def test_default_insights_generated_is_zero(self, sample_job):
        """Test insights_generated defaults to 0."""
        assert sample_job.insights_generated == 0
