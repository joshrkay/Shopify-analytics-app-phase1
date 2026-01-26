"""
Tests for job entitlement enforcement.

Covers all entitlement check paths and audit logging.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from sqlalchemy.orm import Session

from src.jobs.job_entitlements import (
    JobEntitlementChecker,
    JobEntitlementResult,
    JobEntitlementError,
    JobType,
)
from src.entitlements.policy import BillingState
from src.models.subscription import Subscription, SubscriptionStatus
from src.models.plan import PlanFeature


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    session = Mock(spec=Session)
    session.query = Mock()
    return session


@pytest.fixture
def mock_subscription_active():
    """Mock active subscription."""
    sub = Mock(spec=Subscription)
    sub.tenant_id = "tenant_123"
    sub.plan_id = "plan_growth"
    sub.status = SubscriptionStatus.ACTIVE.value
    sub.grace_period_ends_on = None
    sub.created_at = datetime.now(timezone.utc)
    return sub


@pytest.fixture
def mock_subscription_expired():
    """Mock expired subscription."""
    sub = Mock(spec=Subscription)
    sub.tenant_id = "tenant_123"
    sub.plan_id = "plan_growth"
    sub.status = SubscriptionStatus.EXPIRED.value
    sub.grace_period_ends_on = None
    sub.created_at = datetime.now(timezone.utc)
    return sub


@pytest.fixture
def mock_plan_feature_enabled():
    """Mock plan feature that is enabled."""
    pf = Mock(spec=PlanFeature)
    pf.plan_id = "plan_growth"
    pf.feature_key = "premium_analytics"
    pf.is_enabled = True
    return pf


class TestJobEntitlementChecker:
    """Tests for JobEntitlementChecker."""
    
    def test_check_job_entitlement_not_premium_gated(self, mock_db_session):
        """Test that non-premium jobs are always allowed."""
        checker = JobEntitlementChecker(mock_db_session)
        
        # Mock config with no premium_jobs section
        with patch.object(checker, '_load_config', return_value={"premium_jobs": {}}):
            result = checker.check_job_entitlement("tenant_123", JobType.SYNC)
        
        assert result.is_allowed is True
        assert result.job_type == "sync"
    
    def test_check_job_entitlement_expired_subscription(
        self, mock_db_session, mock_subscription_expired
    ):
        """Test that expired subscriptions block all premium jobs."""
        checker = JobEntitlementChecker(mock_db_session)
        
        # Mock config
        config = {
            "premium_jobs": {
                "sync": {"required_feature": "premium_analytics", "skip_on_deny": True}
            }
        }
        
        with patch.object(checker, '_load_config', return_value=config):
            result = checker.check_job_entitlement(
                "tenant_123",
                JobType.SYNC,
                subscription=mock_subscription_expired,
            )
        
        assert result.is_allowed is False
        assert result.billing_state == BillingState.EXPIRED
        assert "expired" in result.reason.lower()
    
    def test_check_job_entitlement_with_feature_check_allowed(
        self, mock_db_session, mock_subscription_active, mock_plan_feature_enabled
    ):
        """Test job entitlement check when feature is enabled."""
        checker = JobEntitlementChecker(mock_db_session)
        
        # Mock config
        config = {
            "premium_jobs": {
                "sync": {"required_feature": "premium_analytics", "skip_on_deny": True}
            }
        }
        
        # Mock policy check_feature_entitlement to return allowed
        with patch.object(checker, '_load_config', return_value=config):
            # Mock EntitlementPolicy
            with patch('src.jobs.job_entitlements.EntitlementPolicy') as mock_policy_class:
                mock_policy = Mock()
                mock_policy.get_billing_state.return_value = BillingState.ACTIVE
                
                # Mock feature entitlement check
                from src.entitlements.policy import EntitlementCheckResult
                mock_policy.check_feature_entitlement.return_value = EntitlementCheckResult(
                    is_entitled=True,
                    billing_state=BillingState.ACTIVE,
                    plan_id="plan_growth",
                    feature="premium_analytics",
                )
                
                mock_policy_class.return_value = mock_policy
                
                result = checker.check_job_entitlement(
                    "tenant_123",
                    JobType.SYNC,
                    subscription=mock_subscription_active,
                )
        
        assert result.is_allowed is True
        assert result.billing_state == BillingState.ACTIVE
    
    def test_check_job_entitlement_with_feature_check_denied(
        self, mock_db_session, mock_subscription_active
    ):
        """Test job entitlement check when feature is not enabled."""
        checker = JobEntitlementChecker(mock_db_session)
        
        # Mock config
        config = {
            "premium_jobs": {
                "sync": {"required_feature": "premium_analytics", "skip_on_deny": True}
            }
        }
        
        # Mock policy check_feature_entitlement to return denied
        with patch.object(checker, '_load_config', return_value=config):
            # Mock EntitlementPolicy
            with patch('src.jobs.job_entitlements.EntitlementPolicy') as mock_policy_class:
                mock_policy = Mock()
                mock_policy.get_billing_state.return_value = BillingState.ACTIVE
                
                # Mock feature entitlement check - denied
                from src.entitlements.policy import EntitlementCheckResult
                mock_policy.check_feature_entitlement.return_value = EntitlementCheckResult(
                    is_entitled=False,
                    billing_state=BillingState.ACTIVE,
                    plan_id="plan_free",
                    feature="premium_analytics",
                    reason="Feature requires a higher plan",
                )
                
                mock_policy_class.return_value = mock_policy
                
                result = checker.check_job_entitlement(
                    "tenant_123",
                    JobType.SYNC,
                    subscription=mock_subscription_active,
                )
        
        assert result.is_allowed is False
        assert "higher plan" in result.reason.lower()
    
    @pytest.mark.asyncio
    async def test_log_job_skipped_with_audit_db(self, mock_db_session):
        """Test logging skipped job with audit database."""
        checker = JobEntitlementChecker(mock_db_session)
        
        # Mock log_system_audit_event
        with patch('src.jobs.job_entitlements.log_system_audit_event', new_callable=AsyncMock) as mock_log:
            await checker.log_job_skipped(
                tenant_id="tenant_123",
                job_type="sync",
                reason="Subscription expired",
                billing_state=BillingState.EXPIRED,
                plan_id="plan_growth",
                audit_db=AsyncMock(),
            )
            
            # Verify audit log was called
            mock_log.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_log_job_skipped_without_audit_db(self, mock_db_session):
        """Test logging skipped job without audit database (fallback to logging)."""
        checker = JobEntitlementChecker(mock_db_session)
        
        with patch('src.jobs.job_entitlements.logger') as mock_logger:
            await checker.log_job_skipped(
                tenant_id="tenant_123",
                job_type="sync",
                reason="Subscription expired",
                billing_state=BillingState.EXPIRED,
                plan_id="plan_growth",
                audit_db=None,
            )
            
            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args
            assert "Job skipped due to entitlement" in call_args[0][0]
            assert call_args[1]["extra"]["tenant_id"] == "tenant_123"
            assert call_args[1]["extra"]["job_type"] == "sync"
    
    @pytest.mark.asyncio
    async def test_log_job_allowed(self, mock_db_session):
        """Test logging allowed job."""
        checker = JobEntitlementChecker(mock_db_session)
        
        # Mock log_system_audit_event
        with patch('src.jobs.job_entitlements.log_system_audit_event', new_callable=AsyncMock) as mock_log:
            await checker.log_job_allowed(
                tenant_id="tenant_123",
                job_type="sync",
                billing_state=BillingState.ACTIVE,
                plan_id="plan_growth",
                audit_db=AsyncMock(),
            )
            
            # Verify audit log was called
            mock_log.assert_called_once()


class TestRequireJobEntitlementDecorator:
    """Tests for @require_job_entitlement decorator."""
    
    @pytest.mark.asyncio
    async def test_decorator_allows_job_when_entitled(self, mock_db_session):
        """Test decorator allows job when entitlement check passes."""
        from src.jobs.job_entitlements import require_job_entitlement
        
        @require_job_entitlement(JobType.SYNC, skip_on_deny=True)
        async def test_job(tenant_id: str, db_session: Session):
            return {"status": "completed"}
        
        # Mock checker to return allowed
        with patch('src.jobs.job_entitlements.JobEntitlementChecker') as mock_checker_class:
            mock_checker = Mock()
            mock_checker.check_job_entitlement.return_value = JobEntitlementResult(
                is_allowed=True,
                billing_state=BillingState.ACTIVE,
                plan_id="plan_growth",
                job_type="sync",
            )
            mock_checker.log_job_allowed = AsyncMock()
            mock_checker.log_job_skipped = AsyncMock()
            mock_checker_class.return_value = mock_checker
            
            result = await test_job("tenant_123", db_session=mock_db_session)
        
        assert result == {"status": "completed"}
        mock_checker.log_job_allowed.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_decorator_skips_job_when_denied(self, mock_db_session):
        """Test decorator skips job when entitlement check fails."""
        from src.jobs.job_entitlements import require_job_entitlement
        
        @require_job_entitlement(JobType.SYNC, skip_on_deny=True)
        async def test_job(tenant_id: str, db_session: Session):
            return {"status": "completed"}
        
        # Mock checker to return denied
        with patch('src.jobs.job_entitlements.JobEntitlementChecker') as mock_checker_class:
            mock_checker = Mock()
            mock_checker.check_job_entitlement.return_value = JobEntitlementResult(
                is_allowed=False,
                billing_state=BillingState.EXPIRED,
                plan_id="plan_growth",
                job_type="sync",
                reason="Subscription expired",
            )
            mock_checker.log_job_allowed = AsyncMock()
            mock_checker.log_job_skipped = AsyncMock()
            mock_checker_class.return_value = mock_checker
            
            result = await test_job("tenant_123", db_session=mock_db_session)
        
        assert result is None  # Job was skipped
        mock_checker.log_job_skipped.assert_called_once()
        mock_checker.log_job_allowed.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_decorator_raises_exception_when_denied_and_skip_false(self, mock_db_session):
        """Test decorator raises exception when skip_on_deny is False."""
        from src.jobs.job_entitlements import require_job_entitlement, JobEntitlementError
        
        @require_job_entitlement(JobType.SYNC, skip_on_deny=False)
        async def test_job(tenant_id: str, db_session: Session):
            return {"status": "completed"}
        
        # Mock checker to return denied
        with patch('src.jobs.job_entitlements.JobEntitlementChecker') as mock_checker_class:
            mock_checker = Mock()
            mock_checker.check_job_entitlement.return_value = JobEntitlementResult(
                is_allowed=False,
                billing_state=BillingState.EXPIRED,
                plan_id="plan_growth",
                job_type="sync",
                reason="Subscription expired",
            )
            mock_checker.log_job_allowed = AsyncMock()
            mock_checker.log_job_skipped = AsyncMock()
            mock_checker_class.return_value = mock_checker
            
            with pytest.raises(JobEntitlementError) as exc_info:
                await test_job("tenant_123", db_session=mock_db_session)
            
            assert exc_info.value.tenant_id == "tenant_123"
            assert exc_info.value.job_type == "sync"
            mock_checker.log_job_skipped.assert_called_once()


class TestJobEntitlementError:
    """Tests for JobEntitlementError."""
    
    def test_error_creation(self):
        """Test JobEntitlementError creation."""
        error = JobEntitlementError(
            job_type="sync",
            tenant_id="tenant_123",
            billing_state=BillingState.EXPIRED,
            reason="Subscription expired",
        )
        
        assert error.job_type == "sync"
        assert error.tenant_id == "tenant_123"
        assert error.billing_state == BillingState.EXPIRED
        assert error.reason == "Subscription expired"
        assert "denied" in str(error).lower()
