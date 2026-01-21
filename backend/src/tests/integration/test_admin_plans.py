"""
Integration tests for Admin Plan Management functionality.

Tests cover:
- Plan CRUD operations (create, read, update, delete)
- Feature toggle functionality
- Plan validation
- Admin authorization
- Shopify sync validation
"""

import uuid
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch, AsyncMock

from fastapi import HTTPException


# Test fixtures


@pytest.fixture
def test_tenant_id():
    """Generate a unique tenant ID for testing."""
    return f"test-tenant-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def test_user_id():
    """Generate a unique user ID for testing."""
    return f"test-user-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.flush = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_plan():
    """Create a mock Plan."""
    plan = MagicMock()
    plan.id = "plan_growth"
    plan.name = "growth"
    plan.display_name = "Growth"
    plan.description = "For growing businesses"
    plan.price_monthly_cents = 2900
    plan.price_yearly_cents = 29000
    plan.shopify_plan_id = None
    plan.is_active = True
    plan.created_at = datetime.utcnow()
    plan.updated_at = datetime.utcnow()
    return plan


@pytest.fixture
def mock_plan_feature():
    """Create a mock PlanFeature."""
    feature = MagicMock()
    feature.id = str(uuid.uuid4())
    feature.plan_id = "plan_growth"
    feature.feature_key = "ai_insights"
    feature.is_enabled = True
    feature.limit_value = 50
    feature.limits = {"monthly": 50}
    return feature


@pytest.fixture
def mock_tenant_context(test_tenant_id, test_user_id):
    """Create a mock TenantContext with admin role."""
    context = MagicMock()
    context.tenant_id = test_tenant_id
    context.user_id = test_user_id
    context.roles = ["admin"]
    return context


@pytest.fixture
def mock_non_admin_context(test_tenant_id, test_user_id):
    """Create a mock TenantContext without admin role."""
    context = MagicMock()
    context.tenant_id = test_tenant_id
    context.user_id = test_user_id
    context.roles = ["user"]
    return context


class TestPlansRepository:
    """Tests for PlansRepository."""

    def test_create_plan(self, mock_db_session):
        """Test plan creation."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        # Mock no existing plan
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        plan = repo.create(
            name="test_plan",
            display_name="Test Plan",
            description="A test plan",
            price_monthly_cents=1999,
            price_yearly_cents=19990,
            is_active=True
        )

        assert plan is not None
        mock_db_session.add.assert_called()
        mock_db_session.flush.assert_called()

    def test_create_plan_duplicate_name(self, mock_db_session, mock_plan):
        """Test that creating a plan with duplicate name fails."""
        from src.repositories.plans_repo import PlansRepository, PlanAlreadyExistsError

        repo = PlansRepository(mock_db_session)

        # Mock existing plan found
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        with pytest.raises(PlanAlreadyExistsError, match="already exists"):
            repo.create(
                name=mock_plan.name,
                display_name="Another Plan",
                price_monthly_cents=999
            )

    def test_get_by_id(self, mock_db_session, mock_plan):
        """Test getting a plan by ID."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        result = repo.get_by_id(mock_plan.id)

        assert result == mock_plan
        assert result.id == mock_plan.id

    def test_get_by_id_not_found(self, mock_db_session):
        """Test getting a non-existent plan returns None."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        result = repo.get_by_id("non_existent_plan")

        assert result is None

    def test_get_all_active_only(self, mock_db_session, mock_plan):
        """Test getting all plans (active only by default)."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_plan]

        mock_db_session.query.return_value = mock_query

        result = repo.get_all(include_inactive=False)

        assert len(result) == 1
        assert result[0] == mock_plan

    def test_update_plan(self, mock_db_session, mock_plan):
        """Test updating a plan."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        updated_plan = repo.update(
            plan_id=mock_plan.id,
            display_name="Updated Growth",
            price_monthly_cents=3900
        )

        assert updated_plan.display_name == "Updated Growth"
        assert updated_plan.price_monthly_cents == 3900
        mock_db_session.flush.assert_called()

    def test_update_plan_not_found(self, mock_db_session):
        """Test updating a non-existent plan raises error."""
        from src.repositories.plans_repo import PlansRepository, PlanNotFoundError

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(PlanNotFoundError, match="not found"):
            repo.update(
                plan_id="non_existent",
                display_name="Updated"
            )

    def test_delete_plan(self, mock_db_session, mock_plan):
        """Test deleting a plan."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        result = repo.delete(mock_plan.id)

        assert result is True
        mock_db_session.delete.assert_called_with(mock_plan)
        mock_db_session.flush.assert_called()

    def test_delete_plan_not_found(self, mock_db_session):
        """Test deleting a non-existent plan returns False."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        result = repo.delete("non_existent")

        assert result is False

    def test_add_feature(self, mock_db_session, mock_plan):
        """Test adding a feature to a plan."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        # Mock plan found, feature not found
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_plan,  # Plan found
            None  # Feature not found
        ]

        feature = repo.add_feature(
            plan_id=mock_plan.id,
            feature_key="ai_insights",
            is_enabled=True,
            limit_value=100
        )

        assert feature is not None
        assert feature.feature_key == "ai_insights"
        mock_db_session.add.assert_called()

    def test_update_feature(self, mock_db_session, mock_plan_feature):
        """Test updating a feature."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan_feature

        result = repo.update_feature(
            plan_id=mock_plan_feature.plan_id,
            feature_key=mock_plan_feature.feature_key,
            is_enabled=False
        )

        assert result.is_enabled == False
        mock_db_session.flush.assert_called()

    def test_remove_feature(self, mock_db_session, mock_plan_feature):
        """Test removing a feature from a plan."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan_feature

        result = repo.remove_feature(
            plan_id=mock_plan_feature.plan_id,
            feature_key=mock_plan_feature.feature_key
        )

        assert result is True
        mock_db_session.delete.assert_called()


class TestPlanService:
    """Tests for PlanService."""

    def test_create_plan_success(self, mock_db_session):
        """Test successful plan creation via service."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        # Mock no existing plan
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        plan_info = service.create_plan(
            name="test",
            display_name="Test Plan",
            description="A test plan",
            price_monthly_cents=1999,
            is_active=True,
            features=[
                {"feature_key": "ai_insights", "is_enabled": True}
            ]
        )

        assert plan_info is not None
        assert plan_info.name == "test"
        mock_db_session.commit.assert_called()

    def test_create_plan_validation_error_empty_name(self, mock_db_session):
        """Test plan creation fails with empty name."""
        from src.services.plan_service import PlanService, PlanValidationError

        service = PlanService(mock_db_session)

        with pytest.raises(PlanValidationError, match="name is required"):
            service.create_plan(
                name="",
                display_name="Test Plan"
            )

    def test_create_plan_validation_error_invalid_name(self, mock_db_session):
        """Test plan creation fails with invalid name characters."""
        from src.services.plan_service import PlanService, PlanValidationError

        service = PlanService(mock_db_session)

        with pytest.raises(PlanValidationError, match="alphanumeric"):
            service.create_plan(
                name="test@plan!",
                display_name="Test Plan"
            )

    def test_create_plan_validation_error_negative_price(self, mock_db_session):
        """Test plan creation fails with negative price."""
        from src.services.plan_service import PlanService, PlanValidationError

        service = PlanService(mock_db_session)

        with pytest.raises(PlanValidationError, match="cannot be negative"):
            service.create_plan(
                name="test",
                display_name="Test Plan",
                price_monthly_cents=-100
            )

    def test_list_plans(self, mock_db_session, mock_plan, mock_plan_feature):
        """Test listing plans."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        mock_plan.features = [mock_plan_feature]

        # Mock query for plans
        mock_query = MagicMock()
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = [mock_plan]
        mock_query.count.return_value = 1

        mock_db_session.query.return_value = mock_query

        plans, total = service.list_plans()

        assert total == 1
        assert len(plans) == 1
        assert plans[0].name == mock_plan.name

    def test_update_plan_success(self, mock_db_session, mock_plan):
        """Test successful plan update."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        updated = service.update_plan(
            plan_id=mock_plan.id,
            price_monthly_cents=3999
        )

        assert updated.price_monthly_cents == 3999
        mock_db_session.commit.assert_called()

    def test_update_plan_not_found(self, mock_db_session):
        """Test updating non-existent plan raises error."""
        from src.services.plan_service import PlanService, PlanNotFoundServiceError

        service = PlanService(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(PlanNotFoundServiceError, match="not found"):
            service.update_plan(
                plan_id="non_existent",
                price_monthly_cents=1000
            )

    def test_toggle_feature(self, mock_db_session, mock_plan, mock_plan_feature):
        """Test toggling a feature."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan_feature

        result = service.toggle_feature(
            plan_id=mock_plan.id,
            feature_key="ai_insights",
            is_enabled=False
        )

        assert result["is_enabled"] == False
        mock_db_session.commit.assert_called()

    def test_delete_plan(self, mock_db_session, mock_plan):
        """Test plan deletion."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        result = service.delete_plan(mock_plan.id)

        assert result is True
        mock_db_session.commit.assert_called()


class TestAdminAuthorization:
    """Tests for admin role verification."""

    def test_admin_role_required(self, mock_non_admin_context):
        """Test that non-admin users are rejected."""
        from src.api.routes.admin_plans import verify_admin_role

        # Mock request with non-admin context
        mock_request = MagicMock()
        mock_request.state.tenant_context = mock_non_admin_context

        with patch(
            "src.api.routes.admin_plans.get_tenant_context",
            return_value=mock_non_admin_context
        ):
            with pytest.raises(HTTPException) as exc_info:
                verify_admin_role(mock_request)

            assert exc_info.value.status_code == 403
            assert "Admin role required" in str(exc_info.value.detail)

    def test_admin_role_allowed(self, mock_tenant_context):
        """Test that admin users are allowed."""
        from src.api.routes.admin_plans import verify_admin_role

        mock_request = MagicMock()
        mock_request.state.tenant_context = mock_tenant_context

        with patch(
            "src.api.routes.admin_plans.get_tenant_context",
            return_value=mock_tenant_context
        ):
            result = verify_admin_role(mock_request)

            assert result == mock_tenant_context

    def test_owner_role_allowed(self, test_tenant_id, test_user_id):
        """Test that owner role is treated as admin."""
        from src.api.routes.admin_plans import verify_admin_role

        owner_context = MagicMock()
        owner_context.tenant_id = test_tenant_id
        owner_context.user_id = test_user_id
        owner_context.roles = ["owner"]

        mock_request = MagicMock()

        with patch(
            "src.api.routes.admin_plans.get_tenant_context",
            return_value=owner_context
        ):
            result = verify_admin_role(mock_request)

            assert result == owner_context


class TestPlanValidation:
    """Tests for plan validation logic."""

    def test_valid_plan_name(self, mock_db_session):
        """Test valid plan names are accepted."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        # Mock no existing plan
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        valid_names = ["growth", "pro_tier", "enterprise-plan", "Plan123"]

        for name in valid_names:
            # Should not raise
            service._validate_plan_data(
                name=name,
                display_name="Test",
                price_monthly_cents=1000,
                price_yearly_cents=10000
            )

    def test_invalid_plan_names(self, mock_db_session):
        """Test invalid plan names are rejected."""
        from src.services.plan_service import PlanService, PlanValidationError

        service = PlanService(mock_db_session)

        invalid_names = [
            "",  # Empty
            "plan with spaces",  # Spaces
            "plan@name",  # Special chars
            "plan.name",  # Periods
        ]

        for name in invalid_names:
            with pytest.raises(PlanValidationError):
                service._validate_plan_data(
                    name=name,
                    display_name="Test",
                    price_monthly_cents=1000,
                    price_yearly_cents=10000
                )

    def test_price_validation(self, mock_db_session):
        """Test price validation."""
        from src.services.plan_service import PlanService, PlanValidationError

        service = PlanService(mock_db_session)

        # Negative prices should fail
        with pytest.raises(PlanValidationError, match="negative"):
            service._validate_plan_data(
                name="test",
                display_name="Test",
                price_monthly_cents=-100,
                price_yearly_cents=1000
            )

        # None prices should be allowed (for free/enterprise plans)
        service._validate_plan_data(
            name="test",
            display_name="Test",
            price_monthly_cents=None,
            price_yearly_cents=None
        )

        # Zero prices should be allowed
        service._validate_plan_data(
            name="test",
            display_name="Test",
            price_monthly_cents=0,
            price_yearly_cents=0
        )


class TestShopifyValidation:
    """Tests for Shopify plan validation."""

    @pytest.mark.asyncio
    async def test_validate_shopify_plan_success(self, mock_db_session, mock_plan):
        """Test successful Shopify plan validation."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        # Mock the billing client
        mock_subscription = MagicMock()
        mock_subscription.id = "gid://shopify/AppSubscription/123"
        mock_subscription.name = "Growth Plan"

        with patch(
            "src.services.plan_service.get_billing_client"
        ) as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get_active_subscriptions.return_value = [mock_subscription]
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_get_client.return_value = mock_client

            result = await service.validate_shopify_plan(
                shop_domain="test.myshopify.com",
                access_token="mock-token"
            )

            assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_validate_shopify_plan_free_plan(self, mock_db_session, mock_plan):
        """Test Shopify validation for free plan (no sync needed)."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        # Free plan has no prices
        mock_plan.price_monthly_cents = None
        mock_plan.price_yearly_cents = None

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        result = await service.sync_plan_to_shopify(
            plan_id=mock_plan.id,
            shop_domain="test.myshopify.com",
            access_token="mock-token"
        )

        # Free plans should validate as valid without Shopify API call
        assert result.is_valid is True
        assert result.price_amount == 0


class TestPlanFeatures:
    """Tests for plan feature management."""

    def test_add_feature_to_plan(self, mock_db_session, mock_plan):
        """Test adding a feature to a plan."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        # Mock plan found, feature not found
        mock_db_session.query.return_value.filter.return_value.first.side_effect = [
            mock_plan,  # Plan found
            None  # Feature not found
        ]

        feature = repo.add_feature(
            plan_id=mock_plan.id,
            feature_key="custom_reports",
            is_enabled=True,
            limit_value=25,
            limits={"monthly_reports": 25}
        )

        assert feature.feature_key == "custom_reports"
        assert feature.is_enabled is True
        assert feature.limit_value == 25

    def test_set_features_replaces_existing(self, mock_db_session, mock_plan):
        """Test that set_features replaces all existing features."""
        from src.repositories.plans_repo import PlansRepository

        repo = PlansRepository(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan
        mock_db_session.query.return_value.filter.return_value.delete.return_value = None

        new_features = [
            {"feature_key": "ai_insights", "is_enabled": True},
            {"feature_key": "export_data", "is_enabled": True, "limit_value": 100},
        ]

        result = repo.set_features(mock_plan.id, new_features)

        assert len(result) == 2
        # Verify delete was called to remove existing features
        mock_db_session.query.return_value.filter.return_value.delete.assert_called()


class TestInstantChanges:
    """Tests verifying changes apply instantly without deployment."""

    def test_price_change_applies_instantly(self, mock_db_session, mock_plan):
        """Test that price changes are immediately reflected."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan

        # Update price
        original_price = mock_plan.price_monthly_cents
        new_price = 4999

        updated = service.update_plan(
            plan_id=mock_plan.id,
            price_monthly_cents=new_price
        )

        # Verify price changed
        assert updated.price_monthly_cents == new_price
        assert updated.price_monthly_cents != original_price

        # Verify commit was called (changes persisted)
        mock_db_session.commit.assert_called()

    def test_feature_toggle_applies_instantly(self, mock_db_session, mock_plan, mock_plan_feature):
        """Test that feature toggles are immediately reflected."""
        from src.services.plan_service import PlanService

        service = PlanService(mock_db_session)

        mock_plan_feature.is_enabled = True
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_plan_feature

        # Toggle feature off
        result = service.toggle_feature(
            plan_id=mock_plan.id,
            feature_key="ai_insights",
            is_enabled=False
        )

        # Verify feature toggled
        assert result["is_enabled"] is False

        # Verify commit was called (changes persisted)
        mock_db_session.commit.assert_called()


# Run tests with: pytest -v src/tests/integration/test_admin_plans.py
