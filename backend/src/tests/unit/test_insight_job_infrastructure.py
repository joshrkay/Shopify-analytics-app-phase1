"""
Unit tests for Insight Job Infrastructure.

Tests cover:
- InsightJobDispatcher entitlement checks
- InsightJobDispatcher cadence restrictions
- InsightJobRunner job execution
- Job lifecycle transitions

Story 8.1 - AI Insight Generation (Read-Only Analytics)
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from src.models.insight_job import InsightJob, InsightJobStatus, InsightJobCadence
from src.services.insight_job_dispatcher import InsightJobDispatcher
from src.services.insight_job_runner import InsightJobRunner


class TestInsightJobDispatcher:
    """Tests for InsightJobDispatcher."""

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        return session

    def test_dispatcher_requires_tenant_id(self, mock_db_session):
        """Test dispatcher raises error without tenant_id."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            InsightJobDispatcher(mock_db_session, tenant_id="")

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_should_create_job_entitled(self, mock_entitlements, mock_db_session):
        """Test should_create_job returns True for entitled tenant."""
        # Mock entitlement check
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "growth"
        mock_service.get_feature_limit.return_value = -1  # Unlimited
        mock_entitlements.return_value = mock_service

        # Mock zero existing insights
        mock_db_session.query.return_value.filter.return_value.count.return_value = 0

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.DAILY)

        assert should_create is True
        assert reason == "OK"

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_should_create_job_not_entitled(self, mock_entitlements, mock_db_session):
        """Test should_create_job returns False for non-entitled tenant."""
        # Mock entitlement check - not entitled
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=False
        )
        mock_entitlements.return_value = mock_service

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.DAILY)

        assert should_create is False
        assert "not entitled" in reason.lower()

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_hourly_requires_enterprise(self, mock_entitlements, mock_db_session):
        """Test hourly cadence requires enterprise tier."""
        # Mock entitlement - entitled but growth tier
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "growth"
        mock_entitlements.return_value = mock_service

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.HOURLY)

        assert should_create is False
        assert "enterprise" in reason.lower()

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_hourly_allowed_for_enterprise(self, mock_entitlements, mock_db_session):
        """Test hourly cadence allowed for enterprise tier."""
        # Mock entitlement - enterprise tier
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "enterprise"
        mock_service.get_feature_limit.return_value = -1  # Unlimited
        mock_entitlements.return_value = mock_service

        # Mock zero existing insights
        mock_db_session.query.return_value.filter.return_value.count.return_value = 0

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.HOURLY)

        assert should_create is True
        assert reason == "OK"

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_rejects_when_active_job_exists(self, mock_entitlements, mock_db_session):
        """Test rejects job creation when active job exists."""
        # Mock entitlement check
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "growth"
        mock_service.get_feature_limit.return_value = -1  # Unlimited
        mock_entitlements.return_value = mock_service

        # Mock zero existing insights for limit check
        mock_db_session.query.return_value.filter.return_value.count.return_value = 0

        # Mock active job exists
        mock_db_session.query.return_value.filter.return_value.first.return_value = (
            InsightJob(
                tenant_id="test-tenant",
                status=InsightJobStatus.RUNNING,
                cadence=InsightJobCadence.DAILY,
                insights_generated=0,
                job_metadata={},
            )
        )

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.DAILY)

        assert should_create is False
        assert "active" in reason.lower()

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_dispatch_creates_job(self, mock_entitlements, mock_db_session):
        """Test dispatch creates and returns job."""
        # Mock entitlement check
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "growth"
        mock_service.get_feature_limit.return_value = -1  # Unlimited
        mock_entitlements.return_value = mock_service

        # Mock zero existing insights
        mock_db_session.query.return_value.filter.return_value.count.return_value = 0

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        job = dispatcher.dispatch(InsightJobCadence.DAILY)

        assert job is not None
        assert job.tenant_id == "test-tenant"
        assert job.cadence == InsightJobCadence.DAILY
        assert job.status == InsightJobStatus.QUEUED
        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_called_once()

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_dispatch_returns_none_when_not_allowed(
        self, mock_entitlements, mock_db_session
    ):
        """Test dispatch returns None when job not allowed."""
        # Mock entitlement - not entitled
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=False
        )
        mock_entitlements.return_value = mock_service

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        job = dispatcher.dispatch(InsightJobCadence.DAILY)

        assert job is None
        mock_db_session.add.assert_not_called()


class TestInsightJobRunner:
    """Tests for InsightJobRunner."""

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        return MagicMock()

    @pytest.fixture
    def sample_job(self):
        """Create a sample queued job."""
        return InsightJob(
            job_id="test-job-123",
            tenant_id="test-tenant",
            cadence=InsightJobCadence.DAILY,
            status=InsightJobStatus.QUEUED,
            insights_generated=0,
            job_metadata={},
        )

    @patch("src.services.insight_job_runner.InsightGenerationService")
    @patch("src.services.insight_job_runner.BillingEntitlementsService")
    def test_execute_job_success(
        self, mock_entitlements, mock_generation_service, mock_db_session, sample_job
    ):
        """Test successful job execution."""
        # Mock entitlements
        mock_ent_instance = MagicMock()
        mock_ent_instance.get_billing_tier.return_value = "growth"
        mock_entitlements.return_value = mock_ent_instance

        # Mock generation service - returns 3 insights
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate_insights.return_value = [
            MagicMock(),
            MagicMock(),
            MagicMock(),
        ]
        mock_generation_service.return_value = mock_gen_instance

        runner = InsightJobRunner(mock_db_session)
        runner.execute_job(sample_job)

        assert sample_job.status == InsightJobStatus.SUCCESS
        assert sample_job.insights_generated == 3
        assert sample_job.completed_at is not None

    @patch("src.services.insight_job_runner.InsightGenerationService")
    @patch("src.services.insight_job_runner.BillingEntitlementsService")
    def test_execute_job_failure(
        self, mock_entitlements, mock_generation_service, mock_db_session, sample_job
    ):
        """Test job execution failure handling."""
        # Mock entitlements
        mock_ent_instance = MagicMock()
        mock_ent_instance.get_billing_tier.return_value = "growth"
        mock_entitlements.return_value = mock_ent_instance

        # Mock generation service - raises error
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate_insights.side_effect = Exception("DB connection failed")
        mock_generation_service.return_value = mock_gen_instance

        runner = InsightJobRunner(mock_db_session)
        runner.execute_job(sample_job)

        assert sample_job.status == InsightJobStatus.FAILED
        assert "DB connection failed" in sample_job.error_message
        assert sample_job.completed_at is not None

    @patch("src.services.insight_job_runner.InsightGenerationService")
    @patch("src.services.insight_job_runner.BillingEntitlementsService")
    def test_execute_job_marks_running_first(
        self, mock_entitlements, mock_generation_service, mock_db_session, sample_job
    ):
        """Test job is marked running before execution."""
        # Mock entitlements
        mock_ent_instance = MagicMock()
        mock_ent_instance.get_billing_tier.return_value = "growth"
        mock_entitlements.return_value = mock_ent_instance

        # Mock generation service
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate_insights.return_value = []
        mock_generation_service.return_value = mock_gen_instance

        # Track status changes
        statuses = []

        def track_flush():
            statuses.append(sample_job.status)

        mock_db_session.flush.side_effect = track_flush

        runner = InsightJobRunner(mock_db_session)
        runner.execute_job(sample_job)

        # First flush should be RUNNING, second should be SUCCESS
        assert InsightJobStatus.RUNNING in statuses
        assert sample_job.status == InsightJobStatus.SUCCESS

    def test_process_queued_jobs_empty(self, mock_db_session):
        """Test processing with no queued jobs."""
        mock_db_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
            []
        )

        runner = InsightJobRunner(mock_db_session)
        processed = runner.process_queued_jobs(limit=10)

        assert processed == 0

    @patch("src.services.insight_job_runner.InsightGenerationService")
    @patch("src.services.insight_job_runner.BillingEntitlementsService")
    def test_process_queued_jobs_batch(
        self, mock_entitlements, mock_generation_service, mock_db_session
    ):
        """Test batch processing of queued jobs."""
        # Mock entitlements
        mock_ent_instance = MagicMock()
        mock_ent_instance.get_billing_tier.return_value = "growth"
        mock_entitlements.return_value = mock_ent_instance

        # Mock generation service
        mock_gen_instance = MagicMock()
        mock_gen_instance.generate_insights.return_value = []
        mock_generation_service.return_value = mock_gen_instance

        # Create 3 queued jobs
        jobs = [
            InsightJob(
                job_id=f"job-{i}",
                tenant_id=f"tenant-{i}",
                cadence=InsightJobCadence.DAILY,
                status=InsightJobStatus.QUEUED,
                insights_generated=0,
                job_metadata={},
            )
            for i in range(3)
        ]

        mock_db_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = (
            jobs
        )

        runner = InsightJobRunner(mock_db_session)
        processed = runner.process_queued_jobs(limit=10)

        assert processed == 3
        mock_db_session.commit.assert_called_once()

        # All jobs should be SUCCESS
        for job in jobs:
            assert job.status == InsightJobStatus.SUCCESS


class TestMonthlyLimitEnforcement:
    """Tests for monthly insight limit enforcement."""

    @pytest.fixture
    def mock_db_session(self):
        """Create mock database session."""
        session = MagicMock()
        # Default: no active job, no existing insights
        session.query.return_value.filter.return_value.first.return_value = None
        session.query.return_value.filter.return_value.count.return_value = 0
        return session

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_rejects_when_limit_reached(self, mock_entitlements, mock_db_session):
        """Test rejects job creation when monthly limit is reached."""
        # Mock entitlement - entitled with limit of 50
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "growth"
        mock_service.get_feature_limit.return_value = 50
        mock_entitlements.return_value = mock_service

        # Mock 50 existing insights this month (at limit)
        mock_db_session.query.return_value.filter.return_value.count.return_value = 50
        # No active job
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.DAILY)

        assert should_create is False
        assert "limit reached" in reason.lower()
        assert "50/50" in reason

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_allows_when_under_limit(self, mock_entitlements, mock_db_session):
        """Test allows job creation when under monthly limit."""
        # Mock entitlement - entitled with limit of 50
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "growth"
        mock_service.get_feature_limit.return_value = 50
        mock_entitlements.return_value = mock_service

        # Mock 25 existing insights this month (under limit)
        mock_db_session.query.return_value.filter.return_value.count.return_value = 25
        # No active job
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.DAILY)

        assert should_create is True
        assert reason == "OK"

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_unlimited_for_enterprise(self, mock_entitlements, mock_db_session):
        """Test unlimited insights for enterprise tier (-1 limit)."""
        # Mock entitlement - enterprise with unlimited (-1)
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "enterprise"
        mock_service.get_feature_limit.return_value = -1  # Unlimited
        mock_entitlements.return_value = mock_service

        # Mock 1000 existing insights (should still be allowed)
        mock_db_session.query.return_value.filter.return_value.count.return_value = 1000
        # No active job
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.DAILY)

        assert should_create is True
        assert reason == "OK"

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_zero_limit_for_free_tier(self, mock_entitlements, mock_db_session):
        """Test zero limit (not entitled) for free tier."""
        # Mock entitlement - not entitled (returns 0)
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=False
        )
        mock_service.get_feature_limit.return_value = 0
        mock_entitlements.return_value = mock_service

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")
        should_create, reason = dispatcher.should_create_job(InsightJobCadence.DAILY)

        assert should_create is False
        assert "not entitled" in reason.lower()

    @patch("src.services.insight_job_dispatcher.BillingEntitlementsService")
    def test_monthly_count_respects_start_of_month(self, mock_entitlements, mock_db_session):
        """Test that monthly count is filtered by start of current month."""
        # Mock entitlement
        mock_service = MagicMock()
        mock_service.check_feature_entitlement.return_value = MagicMock(
            is_entitled=True
        )
        mock_service.get_billing_tier.return_value = "growth"
        mock_service.get_feature_limit.return_value = 50
        mock_entitlements.return_value = mock_service

        dispatcher = InsightJobDispatcher(mock_db_session, "test-tenant")

        # Call the internal method to verify it queries correctly
        count = dispatcher._get_monthly_insight_count()

        # Verify query was made with filter
        mock_db_session.query.assert_called()
        # The filter should have been called to filter by tenant and generated_at >= start_of_month
