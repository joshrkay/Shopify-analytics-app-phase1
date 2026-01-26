"""
Unit tests for billing upgrade and downgrade functionality.

Tests cover:
- Upgrade validation
- Downgrade validation
- Plan tier comparison
- Scheduled downgrades
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock

from src.services.billing_service import (
    BillingService,
    BillingServiceError,
    PlanNotFoundError,
    SubscriptionError,
    CheckoutResult
)
from src.models.subscription import SubscriptionStatus


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    return session


@pytest.fixture
def test_tenant_id():
    """Generate a unique tenant ID."""
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def billing_service(mock_db_session, test_tenant_id):
    """Create a billing service instance."""
    return BillingService(mock_db_session, test_tenant_id)


@pytest.fixture
def mock_free_plan():
    """Create a mock free plan."""
    plan = MagicMock()
    plan.id = "plan_free"
    plan.name = "free"
    plan.display_name = "Free"
    plan.price_monthly_cents = 0
    plan.is_active = True
    return plan


@pytest.fixture
def mock_growth_plan():
    """Create a mock growth plan."""
    plan = MagicMock()
    plan.id = "plan_growth"
    plan.name = "growth"
    plan.display_name = "Growth"
    plan.price_monthly_cents = 2900
    plan.is_active = True
    return plan


@pytest.fixture
def mock_pro_plan():
    """Create a mock pro plan."""
    plan = MagicMock()
    plan.id = "plan_pro"
    plan.name = "pro"
    plan.display_name = "Pro"
    plan.price_monthly_cents = 7900
    plan.is_active = True
    return plan


@pytest.fixture
def mock_active_subscription(test_tenant_id, mock_growth_plan):
    """Create a mock active subscription on Growth plan."""
    subscription = MagicMock()
    subscription.id = str(uuid.uuid4())
    subscription.tenant_id = test_tenant_id
    subscription.plan_id = mock_growth_plan.id
    subscription.status = SubscriptionStatus.ACTIVE.value
    subscription.store_id = str(uuid.uuid4())
    subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=15)
    subscription.extra_metadata = None
    return subscription


@pytest.fixture
def mock_store(test_tenant_id):
    """Create a mock store."""
    store = MagicMock()
    store.id = str(uuid.uuid4())
    store.tenant_id = test_tenant_id
    store.shop_domain = "test-store.myshopify.com"
    store.access_token_encrypted = "mock-token"
    store.currency = "USD"
    store.status = "active"
    return store


class TestPlanTierComparison:
    """Tests for plan tier comparison."""

    def test_free_plan_is_tier_0(self, billing_service, mock_db_session, mock_free_plan):
        """Test free plan is tier 0."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_free_plan
        mock_db_session.query.return_value = mock_query

        tier = billing_service.get_plan_tier("plan_free")

        assert tier == 0

    def test_growth_plan_is_tier_1(self, billing_service, mock_db_session, mock_growth_plan):
        """Test growth plan is tier 1."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_growth_plan
        mock_db_session.query.return_value = mock_query

        tier = billing_service.get_plan_tier("plan_growth")

        assert tier == 1

    def test_pro_plan_is_tier_2(self, billing_service, mock_db_session, mock_pro_plan):
        """Test pro plan is tier 2."""
        mock_query = MagicMock()
        mock_query.filter.return_value.first.return_value = mock_pro_plan
        mock_db_session.query.return_value = mock_query

        tier = billing_service.get_plan_tier("plan_pro")

        assert tier == 2


class TestCanUpgradeTo:
    """Tests for can_upgrade_to method."""

    def test_can_upgrade_from_free_to_growth(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_free_plan,
        mock_growth_plan
    ):
        """Test upgrade from Free to Growth is allowed."""
        mock_active_subscription.plan_id = mock_free_plan.id

        # Mock queries
        def query_side_effect(model):
            mock_query = MagicMock()
            if hasattr(model, '__tablename__'):
                if model.__tablename__ == 'tenant_subscriptions':
                    mock_query.filter.return_value.first.return_value = mock_active_subscription
                elif model.__tablename__ == 'plans':
                    # Return appropriate plan based on filter
                    def plan_filter(*args, **kwargs):
                        result = MagicMock()
                        # Simplified - return growth plan for growth, free for free
                        if 'plan_growth' in str(args):
                            result.first.return_value = mock_growth_plan
                        else:
                            result.first.return_value = mock_free_plan
                        return result
                    mock_query.filter.side_effect = plan_filter
            return mock_query

        mock_db_session.query.side_effect = query_side_effect

        # Mock _get_plan to return correct plans
        with patch.object(billing_service, '_get_plan') as mock_get_plan:
            mock_get_plan.side_effect = lambda plan_id: mock_free_plan if plan_id == "plan_free" else mock_growth_plan
            with patch.object(billing_service, '_get_active_subscription', return_value=mock_active_subscription):
                result = billing_service.can_upgrade_to("plan_growth")

        assert result is True

    def test_cannot_upgrade_to_same_tier(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_growth_plan
    ):
        """Test cannot upgrade to same tier."""
        with patch.object(billing_service, '_get_plan', return_value=mock_growth_plan):
            with patch.object(billing_service, '_get_active_subscription', return_value=mock_active_subscription):
                result = billing_service.can_upgrade_to("plan_growth")

        assert result is False

    def test_can_upgrade_with_no_subscription(
        self,
        billing_service,
        mock_db_session,
        mock_growth_plan
    ):
        """Test can upgrade when no subscription exists."""
        with patch.object(billing_service, '_get_active_subscription', return_value=None):
            result = billing_service.can_upgrade_to("plan_growth")

        assert result is True  # Can "upgrade" to any paid plan


class TestCanDowngradeTo:
    """Tests for can_downgrade_to method."""

    def test_can_downgrade_from_pro_to_growth(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_pro_plan,
        mock_growth_plan
    ):
        """Test downgrade from Pro to Growth is allowed."""
        mock_active_subscription.plan_id = mock_pro_plan.id

        with patch.object(billing_service, '_get_plan') as mock_get_plan:
            mock_get_plan.side_effect = lambda plan_id: mock_pro_plan if plan_id == "plan_pro" else mock_growth_plan
            with patch.object(billing_service, '_get_active_subscription', return_value=mock_active_subscription):
                result = billing_service.can_downgrade_to("plan_growth")

        assert result is True

    def test_cannot_downgrade_without_subscription(
        self,
        billing_service,
        mock_db_session
    ):
        """Test cannot downgrade when no subscription exists."""
        with patch.object(billing_service, '_get_active_subscription', return_value=None):
            result = billing_service.can_downgrade_to("plan_free")

        assert result is False


class TestUpgradeSubscription:
    """Tests for upgrade_subscription method."""

    @pytest.mark.asyncio
    async def test_upgrade_requires_active_subscription(
        self,
        billing_service,
        mock_db_session
    ):
        """Test upgrade fails without active subscription."""
        with patch.object(billing_service, '_get_active_subscription', return_value=None):
            with pytest.raises(SubscriptionError, match="No active subscription"):
                await billing_service.upgrade_subscription("plan_pro")

    @pytest.mark.asyncio
    async def test_upgrade_validates_higher_tier(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_growth_plan,
        mock_free_plan
    ):
        """Test upgrade validates target is higher tier."""
        mock_active_subscription.plan_id = mock_growth_plan.id

        with patch.object(billing_service, '_get_active_subscription', return_value=mock_active_subscription):
            with patch.object(billing_service, '_get_plan') as mock_get_plan:
                mock_get_plan.side_effect = lambda plan_id: mock_growth_plan if plan_id == "plan_growth" else mock_free_plan
                with pytest.raises(SubscriptionError, match="Cannot upgrade"):
                    await billing_service.upgrade_subscription("plan_free")


class TestDowngradeSubscription:
    """Tests for downgrade_subscription method."""

    @pytest.mark.asyncio
    async def test_downgrade_requires_active_subscription(
        self,
        billing_service,
        mock_db_session
    ):
        """Test downgrade fails without active subscription."""
        with patch.object(billing_service, '_get_active_subscription', return_value=None):
            with pytest.raises(SubscriptionError, match="No active subscription"):
                await billing_service.downgrade_subscription("plan_free")

    @pytest.mark.asyncio
    async def test_downgrade_validates_lower_tier(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_growth_plan,
        mock_pro_plan
    ):
        """Test downgrade validates target is lower tier."""
        mock_active_subscription.plan_id = mock_growth_plan.id

        with patch.object(billing_service, '_get_active_subscription', return_value=mock_active_subscription):
            with patch.object(billing_service, '_get_plan') as mock_get_plan:
                mock_get_plan.side_effect = lambda plan_id: mock_growth_plan if plan_id == "plan_growth" else mock_pro_plan
                with pytest.raises(SubscriptionError, match="Cannot downgrade"):
                    await billing_service.downgrade_subscription("plan_pro")

    @pytest.mark.asyncio
    async def test_downgrade_to_free_schedules_change(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_growth_plan,
        mock_free_plan,
        mock_store
    ):
        """Test downgrade to free schedules change at period end."""
        mock_active_subscription.plan_id = mock_growth_plan.id
        mock_active_subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=15)

        with patch.object(billing_service, '_get_active_subscription', return_value=mock_active_subscription):
            with patch.object(billing_service, '_get_plan') as mock_get_plan:
                mock_get_plan.side_effect = lambda plan_id: mock_growth_plan if plan_id == "plan_growth" else mock_free_plan
                with patch.object(billing_service, '_get_store', return_value=mock_store):
                    with patch.object(billing_service, '_log_billing_event'):
                        result = await billing_service.downgrade_subscription("plan_free")

        assert result.success
        assert result.checkout_url == ""  # No checkout needed for free
        assert mock_active_subscription.extra_metadata is not None
        assert "scheduled_downgrade" in mock_active_subscription.extra_metadata


class TestSubscriptionInfo:
    """Tests for get_subscription_info method."""

    def test_subscription_info_active(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_growth_plan
    ):
        """Test subscription info for active subscription."""
        mock_sub_query = MagicMock()
        mock_sub_query.filter.return_value.first.return_value = mock_active_subscription
        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_growth_plan

        mock_db_session.query.side_effect = [mock_sub_query, mock_plan_query]

        info = billing_service.get_subscription_info()

        assert info.is_active
        assert info.can_access_features
        assert info.plan_id == mock_growth_plan.id

    def test_subscription_info_cancelled(
        self,
        billing_service,
        mock_db_session,
        mock_active_subscription,
        mock_growth_plan
    ):
        """Test subscription info for cancelled subscription."""
        mock_active_subscription.status = SubscriptionStatus.CANCELLED.value
        mock_active_subscription.cancelled_at = datetime.now(timezone.utc)

        # First query returns None (no active), second returns cancelled
        mock_active_query = MagicMock()
        mock_active_query.filter.return_value.first.return_value = None

        mock_cancelled_query = MagicMock()
        mock_cancelled_query.filter.return_value.order_by.return_value.first.return_value = mock_active_subscription

        mock_plan_query = MagicMock()
        mock_plan_query.filter.return_value.first.return_value = mock_growth_plan

        mock_db_session.query.side_effect = [mock_active_query, mock_cancelled_query, mock_plan_query]

        info = billing_service.get_subscription_info()

        assert not info.is_active
        assert not info.can_access_features
        assert info.downgraded_reason == "Subscription cancelled"
