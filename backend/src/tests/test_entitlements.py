"""
Comprehensive tests for the entitlements enforcement system.

Target: ≥90% code coverage

Tests cover:
- EntitlementLoader: Plan loading and configuration
- AccessRules: Billing state access rules
- EntitlementCache: Redis/memory caching and invalidation
- EntitlementMiddleware: FastAPI middleware and decorators
- EntitlementAuditLogger: Audit logging for access denials
"""

import json
import os
import pytest
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from dataclasses import asdict

# Import test fixtures first
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def sample_plans_json():
    """Create a sample plans.json for testing."""
    return {
        "version": "1.0.0",
        "plans": [
            {
                "id": "plan_free",
                "name": "free",
                "display_name": "Free",
                "tier": 0,
                "pricing": {"monthly_cents": 0},
                "trial": {"enabled": False, "days": 0},
                "features": {
                    "dashboard_basic": True,
                    "dashboard_advanced": False,
                    "ai_insights": False,
                    "data_export_csv": "limited",
                    "api_access": False,
                },
                "limits": {
                    "max_dashboards": 2,
                    "max_users": 1,
                    "api_calls_per_month": 0,
                },
                "is_active": True,
            },
            {
                "id": "plan_growth",
                "name": "growth",
                "display_name": "Growth",
                "tier": 1,
                "pricing": {"monthly_cents": 2900},
                "trial": {"enabled": True, "days": 14},
                "features": {
                    "dashboard_basic": True,
                    "dashboard_advanced": True,
                    "ai_insights": True,
                    "data_export_csv": True,
                    "api_access": "limited",
                },
                "limits": {
                    "max_dashboards": 10,
                    "max_users": 5,
                    "api_calls_per_month": 10000,
                },
                "is_active": True,
            },
            {
                "id": "plan_pro",
                "name": "pro",
                "display_name": "Pro",
                "tier": 2,
                "pricing": {"monthly_cents": 7900},
                "trial": {"enabled": True, "days": 14},
                "features": {
                    "dashboard_basic": True,
                    "dashboard_advanced": True,
                    "dashboard_custom": True,
                    "ai_insights": True,
                    "ai_actions": True,
                    "data_export_csv": True,
                    "data_export_api": True,
                    "api_access": True,
                },
                "limits": {
                    "max_dashboards": 50,
                    "max_users": 20,
                    "api_calls_per_month": 100000,
                },
                "is_active": True,
            },
        ],
        "billing_config": {
            "grace_period_days": 3,
            "warning_notification_days_before": 3,
            "access_during_grace": "full",
        },
        "billing_rules": {
            "grace_period_days": 3,
            "retry_strategy": "exponential_backoff",
            "max_retries": 5,
        },
        "access_rules": {
            "active": {
                "access_level": "full",
                "restrictions": [],
                "warnings": [],
            },
            "past_due": {
                "access_level": "read_only",
                "restrictions": ["data_export", "ai_actions"],
                "warnings": ["payment_past_due"],
            },
            "grace_period": {
                "access_level": "full",
                "restrictions": [],
                "warnings": ["payment_grace_period"],
                "duration_days": 3,
            },
            "canceled": {
                "access_level": "full_until_period_end",
                "restrictions": [],
                "warnings": ["subscription_canceled"],
            },
            "expired": {
                "access_level": "read_only_analytics",
                "restrictions": ["data_export", "ai_actions", "ai_insights"],
                "warnings": ["subscription_expired"],
            },
            "frozen": {
                "access_level": "limited",
                "restrictions": ["data_export", "ai_actions"],
                "warnings": ["payment_failed_frozen"],
            },
        },
        "feature_descriptions": {
            "dashboard_basic": "Basic analytics dashboards",
            "ai_insights": "AI-powered business insights",
        },
    }


@pytest.fixture
def temp_plans_file(sample_plans_json):
    """Create a temporary plans.json file."""
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.json',
        delete=False,
    ) as f:
        json.dump(sample_plans_json, f)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def mock_subscription():
    """Create a mock subscription object."""
    sub = Mock()
    sub.tenant_id = "tenant_123"
    sub.plan_id = "plan_growth"
    sub.status = "active"
    sub.grace_period_ends_on = None
    sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
    return sub


@pytest.fixture
def mock_frozen_subscription():
    """Create a mock frozen subscription in grace period."""
    sub = Mock()
    sub.tenant_id = "tenant_456"
    sub.plan_id = "plan_growth"
    sub.status = "frozen"
    sub.grace_period_ends_on = datetime.now(timezone.utc) + timedelta(days=2)
    sub.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)
    return sub


@pytest.fixture
def mock_expired_subscription():
    """Create a mock expired subscription."""
    sub = Mock()
    sub.tenant_id = "tenant_789"
    sub.plan_id = "plan_free"
    sub.status = "expired"
    sub.grace_period_ends_on = datetime.now(timezone.utc) - timedelta(days=5)
    sub.current_period_end = datetime.now(timezone.utc) - timedelta(days=5)
    return sub


# =============================================================================
# EntitlementLoader Tests
# =============================================================================

class TestEntitlementLoader:
    """Test suite for EntitlementLoader."""

    def test_loader_loads_plans_from_file(self, temp_plans_file):
        """Test that loader successfully loads plans from JSON file."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        assert loader.get_plan("plan_free") is not None
        assert loader.get_plan("plan_growth") is not None
        assert loader.get_plan("plan_pro") is not None

        reset_entitlement_loader()

    def test_loader_plan_by_name(self, temp_plans_file):
        """Test getting plan by name instead of ID."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        plan = loader.get_plan("growth")
        assert plan is not None
        assert plan.plan_id == "plan_growth"

        reset_entitlement_loader()

    def test_loader_get_free_plan(self, temp_plans_file):
        """Test getting the free plan."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        plan = loader.get_free_plan()
        assert plan is not None
        assert plan.plan_id == "plan_free"
        assert plan.tier == 0

        reset_entitlement_loader()

    def test_loader_get_all_plans(self, temp_plans_file):
        """Test getting all active plans."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        plans = loader.get_all_plans()
        assert len(plans) == 3
        # Should be sorted by tier
        assert plans[0].tier == 0
        assert plans[1].tier == 1
        assert plans[2].tier == 2

        reset_entitlement_loader()

    def test_plan_has_feature(self, temp_plans_file):
        """Test checking if plan has a feature."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        free_plan = loader.get_plan("plan_free")
        growth_plan = loader.get_plan("plan_growth")

        assert free_plan.has_feature("dashboard_basic") is True
        assert free_plan.has_feature("ai_insights") is False
        assert growth_plan.has_feature("ai_insights") is True

        reset_entitlement_loader()

    def test_plan_limited_feature(self, temp_plans_file):
        """Test detecting limited features."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        free_plan = loader.get_plan("plan_free")

        # data_export_csv is "limited" for free plan
        assert free_plan.has_feature("data_export_csv") is True
        feat = free_plan.get_feature("data_export_csv")
        assert feat.is_limited() is True

        reset_entitlement_loader()

    def test_plan_get_enabled_features(self, temp_plans_file):
        """Test getting list of enabled features."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        growth_plan = loader.get_plan("plan_growth")
        enabled = growth_plan.get_enabled_features()

        assert "dashboard_basic" in enabled
        assert "ai_insights" in enabled
        assert "dashboard_custom" not in enabled

        reset_entitlement_loader()

    def test_plan_get_restricted_features(self, temp_plans_file):
        """Test getting list of restricted features."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        free_plan = loader.get_plan("plan_free")
        restricted = free_plan.get_restricted_features()

        assert "dashboard_advanced" in restricted
        assert "ai_insights" in restricted
        assert "api_access" in restricted

        reset_entitlement_loader()

    def test_plan_limits(self, temp_plans_file):
        """Test plan usage limits."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        free_plan = loader.get_plan("plan_free")
        growth_plan = loader.get_plan("plan_growth")

        assert free_plan.limits.max_dashboards == 2
        assert free_plan.limits.max_users == 1
        assert growth_plan.limits.max_dashboards == 10
        assert growth_plan.limits.api_calls_per_month == 10000

        reset_entitlement_loader()

    def test_compare_plans(self, temp_plans_file):
        """Test plan comparison."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        # free < growth
        assert loader.compare_plans("plan_free", "plan_growth") == -1
        # growth < pro
        assert loader.compare_plans("plan_growth", "plan_pro") == -1
        # pro > growth
        assert loader.compare_plans("plan_pro", "plan_growth") == 1
        # same plan
        assert loader.compare_plans("plan_growth", "plan_growth") == 0

        reset_entitlement_loader()

    def test_is_upgrade_downgrade(self, temp_plans_file):
        """Test upgrade/downgrade detection."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        assert loader.is_upgrade("plan_free", "plan_growth") is True
        assert loader.is_upgrade("plan_growth", "plan_free") is False
        assert loader.is_downgrade("plan_growth", "plan_free") is True
        assert loader.is_downgrade("plan_free", "plan_growth") is False

        reset_entitlement_loader()

    def test_get_features_lost_on_downgrade(self, temp_plans_file):
        """Test identifying features lost on downgrade."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        lost = loader.get_features_lost_on_downgrade("plan_growth", "plan_free")

        assert "dashboard_advanced" in lost
        assert "ai_insights" in lost

        reset_entitlement_loader()

    def test_billing_config(self, temp_plans_file):
        """Test billing configuration loading."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        config = loader.get_billing_config()
        assert config.grace_period_days == 3
        assert config.access_during_grace == "full"

        reset_entitlement_loader()

    def test_grace_period_days(self, temp_plans_file):
        """Test grace period configuration."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        grace_days = loader.get_grace_period_days()
        assert grace_days == 3

        reset_entitlement_loader()

    def test_access_rules(self, temp_plans_file):
        """Test access rules by billing state."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        active_rule = loader.get_access_rule("active")
        assert active_rule.access_level == "full"
        assert len(active_rule.restrictions) == 0

        expired_rule = loader.get_access_rule("expired")
        assert expired_rule.access_level == "read_only_analytics"
        assert "ai_insights" in expired_rule.restrictions

        reset_entitlement_loader()

    def test_loader_reload(self, temp_plans_file, sample_plans_json):
        """Test configuration reload."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader = EntitlementLoader(config_path=temp_plans_file)

        # Modify the file
        sample_plans_json["plans"][0]["display_name"] = "Updated Free"
        with open(temp_plans_file, 'w') as f:
            json.dump(sample_plans_json, f)

        loader.reload()

        plan = loader.get_plan("plan_free")
        assert plan.display_name == "Updated Free"

        reset_entitlement_loader()

    def test_singleton_pattern(self, temp_plans_file):
        """Test singleton pattern."""
        from src.entitlements.loader import EntitlementLoader, reset_entitlement_loader

        reset_entitlement_loader()
        loader1 = EntitlementLoader(config_path=temp_plans_file)
        loader2 = EntitlementLoader()  # Should return same instance

        assert loader1 is loader2

        reset_entitlement_loader()


# =============================================================================
# AccessRules Tests
# =============================================================================

class TestAccessRules:
    """Test suite for AccessRules."""

    def test_billing_state_from_subscription_status(self):
        """Test BillingState.from_subscription_status mapping."""
        from src.entitlements.rules import BillingState

        assert BillingState.from_subscription_status("active") == BillingState.ACTIVE
        assert BillingState.from_subscription_status("pending") == BillingState.PENDING
        assert BillingState.from_subscription_status("trialing") == BillingState.TRIALING
        assert BillingState.from_subscription_status("expired") == BillingState.EXPIRED
        assert BillingState.from_subscription_status("declined") == BillingState.EXPIRED

    def test_billing_state_frozen_with_grace(self):
        """Test frozen status with active grace period."""
        from src.entitlements.rules import BillingState

        grace_ends = datetime.now(timezone.utc) + timedelta(days=2)
        state = BillingState.from_subscription_status("frozen", grace_period_ends_on=grace_ends)

        assert state == BillingState.GRACE_PERIOD

    def test_billing_state_frozen_grace_expired(self):
        """Test frozen status with expired grace period."""
        from src.entitlements.rules import BillingState

        grace_ends = datetime.now(timezone.utc) - timedelta(days=1)
        state = BillingState.from_subscription_status("frozen", grace_period_ends_on=grace_ends)

        assert state == BillingState.FROZEN

    def test_billing_state_canceled_with_access(self):
        """Test canceled status with remaining access period."""
        from src.entitlements.rules import BillingState

        period_end = datetime.now(timezone.utc) + timedelta(days=10)
        state = BillingState.from_subscription_status("cancelled", current_period_end=period_end)

        assert state == BillingState.CANCELED

    def test_billing_state_canceled_expired(self):
        """Test canceled status with expired access period."""
        from src.entitlements.rules import BillingState

        period_end = datetime.now(timezone.utc) - timedelta(days=5)
        state = BillingState.from_subscription_status("cancelled", current_period_end=period_end)

        assert state == BillingState.EXPIRED

    def test_access_level_properties(self):
        """Test AccessLevel enum properties."""
        from src.entitlements.rules import AccessLevel

        assert AccessLevel.FULL.allows_writes() is True
        assert AccessLevel.READ_ONLY.allows_writes() is False
        assert AccessLevel.NONE.allows_writes() is False

        assert AccessLevel.FULL.allows_reads() is True
        assert AccessLevel.READ_ONLY.allows_reads() is True
        assert AccessLevel.NONE.allows_reads() is False

    def test_access_rules_active_state(self, temp_plans_file, mock_subscription):
        """Test access rules for active billing state."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_123",
            plan_id="plan_growth",
            billing_state=BillingState.ACTIVE,
        )

        # Should have full access
        decision = rules.check_feature_access("ai_insights")
        assert decision.allowed is True
        assert decision.billing_state == BillingState.ACTIVE

        reset_entitlement_loader()

    def test_access_rules_expired_state(self, temp_plans_file):
        """Test access rules for expired billing state."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_789",
            plan_id="plan_growth",
            billing_state=BillingState.EXPIRED,
        )

        # ai_insights should be restricted in expired state
        decision = rules.check_feature_access("ai_insights")
        assert decision.allowed is False
        assert "expired" in decision.reason.lower() or "restrict" in decision.reason.lower()

        reset_entitlement_loader()

    def test_access_rules_feature_not_in_plan(self, temp_plans_file):
        """Test access denied for feature not in plan."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_123",
            plan_id="plan_free",
            billing_state=BillingState.ACTIVE,
        )

        decision = rules.check_feature_access("ai_insights")
        assert decision.allowed is False
        assert decision.required_plan is not None

        reset_entitlement_loader()

    def test_access_rules_write_operation(self, temp_plans_file):
        """Test write operations in read-only state."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState, AccessLevel

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_456",
            plan_id="plan_growth",
            billing_state=BillingState.PAST_DUE,
        )

        # Write operations should be restricted in read_only state
        assert rules.get_access_level() == AccessLevel.READ_ONLY
        decision = rules.check_feature_access("dashboard_basic", operation="write")
        assert decision.allowed is False

        reset_entitlement_loader()

    def test_access_rules_check_limit(self, temp_plans_file):
        """Test usage limit checking."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_123",
            plan_id="plan_free",
            billing_state=BillingState.ACTIVE,
        )

        # Free plan has max_dashboards = 2
        assert rules.check_limit("max_dashboards", 1).allowed is True
        assert rules.check_limit("max_dashboards", 2).allowed is False  # At limit
        assert rules.check_limit("max_dashboards", 5).allowed is False  # Over limit

        reset_entitlement_loader()

    def test_access_rules_warnings(self, temp_plans_file):
        """Test billing state warnings."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_456",
            plan_id="plan_growth",
            billing_state=BillingState.GRACE_PERIOD,
        )

        warnings = rules.get_warnings()
        assert len(warnings) > 0
        assert any(w.code == "payment_grace_period" for w in warnings)

        reset_entitlement_loader()

    def test_access_rules_grace_period_days_remaining(self, temp_plans_file):
        """Test grace period days remaining calculation."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        grace_ends = datetime.now(timezone.utc) + timedelta(days=2, hours=12)

        rules = AccessRules(
            tenant_id="tenant_456",
            plan_id="plan_growth",
            billing_state=BillingState.GRACE_PERIOD,
            grace_period_ends_on=grace_ends,
        )

        days = rules.get_grace_period_days_remaining()
        assert days is not None
        assert days >= 2

        reset_entitlement_loader()

    def test_access_rules_feature_flag_override(self, temp_plans_file):
        """Test emergency feature flag override."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        # Free plan doesn't have ai_insights, but override enables it
        rules = AccessRules(
            tenant_id="tenant_123",
            plan_id="plan_free",
            billing_state=BillingState.ACTIVE,
            feature_flags_override={"ai_insights": True},
        )

        decision = rules.check_feature_access("ai_insights")
        assert decision.allowed is True

        reset_entitlement_loader()

    def test_access_decision_to_error_response(self, temp_plans_file):
        """Test AccessDecision.to_error_response()."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_123",
            plan_id="plan_free",
            billing_state=BillingState.ACTIVE,
        )

        decision = rules.check_feature_access("ai_insights")
        error = decision.to_error_response()

        assert error["error"] == "entitlement_required"
        assert error["feature"] == "ai_insights"
        assert error["current_plan"] == "Free"

        reset_entitlement_loader()

    def test_create_access_rules_from_subscription(self, temp_plans_file, mock_subscription):
        """Test factory function for creating AccessRules from subscription."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import create_access_rules_from_subscription, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = create_access_rules_from_subscription(
            tenant_id="tenant_123",
            subscription=mock_subscription,
        )

        assert rules.tenant_id == "tenant_123"
        assert rules.plan_id == "plan_growth"
        assert rules.billing_state == BillingState.ACTIVE

        reset_entitlement_loader()

    def test_create_access_rules_no_subscription(self, temp_plans_file):
        """Test factory function with no subscription."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import create_access_rules_from_subscription, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = create_access_rules_from_subscription(
            tenant_id="tenant_123",
            subscription=None,
        )

        assert rules.billing_state == BillingState.NONE
        assert rules.plan_id == "plan_free"

        reset_entitlement_loader()


# =============================================================================
# EntitlementCache Tests
# =============================================================================

class TestEntitlementCache:
    """Test suite for EntitlementCache."""

    def test_cached_entitlement_serialization(self):
        """Test CachedEntitlement serialization/deserialization."""
        from src.entitlements.cache import CachedEntitlement

        cached = CachedEntitlement(
            tenant_id="tenant_123",
            plan_id="plan_growth",
            plan_name="Growth",
            billing_state="active",
            access_level="full",
            enabled_features=["ai_insights", "dashboard_advanced"],
            restricted_features=["dashboard_custom"],
            limits={"max_dashboards": 10},
            warnings=[],
        )

        json_str = cached.to_json()
        restored = CachedEntitlement.from_json(json_str)

        assert restored.tenant_id == cached.tenant_id
        assert restored.plan_id == cached.plan_id
        assert restored.enabled_features == cached.enabled_features

    def test_cached_entitlement_expiration(self):
        """Test cache entry expiration check."""
        from src.entitlements.cache import CachedEntitlement

        cached = CachedEntitlement(
            tenant_id="tenant_123",
            plan_id="plan_growth",
            plan_name="Growth",
            billing_state="active",
            access_level="full",
            enabled_features=[],
            restricted_features=[],
            limits={},
            warnings=[],
            cached_at=(datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat(),
        )

        assert cached.is_expired(300) is True  # 5 minute TTL
        assert cached.is_expired(600) is False  # 10 minute TTL

    def test_in_memory_cache_basic(self):
        """Test in-memory cache basic operations."""
        from src.entitlements.cache import InMemoryCache

        cache = InMemoryCache(max_size=100)

        cache.set("key1", "value1")
        assert cache.get("key1", 300) == "value1"

        assert cache.delete("key1") is True
        assert cache.get("key1", 300) is None

    def test_in_memory_cache_ttl_expiration(self):
        """Test in-memory cache TTL expiration."""
        from src.entitlements.cache import InMemoryCache
        import time

        cache = InMemoryCache()
        cache.set("key1", "value1")

        # Should be available immediately
        assert cache.get("key1", 10) == "value1"

        # Simulate expiration by using very short TTL
        assert cache.get("key1", 0) is None

    def test_in_memory_cache_delete_pattern(self):
        """Test in-memory cache pattern deletion."""
        from src.entitlements.cache import InMemoryCache

        cache = InMemoryCache()
        cache.set("entitlement:tenant_1", "value1")
        cache.set("entitlement:tenant_2", "value2")
        cache.set("other:key", "value3")

        deleted = cache.delete_pattern("entitlement:*")
        assert deleted == 2
        assert cache.get("other:key", 300) == "value3"

    def test_entitlement_cache_get_set(self):
        """Test EntitlementCache get/set operations."""
        from src.entitlements.cache import EntitlementCache, CachedEntitlement

        cache = EntitlementCache()

        cached = CachedEntitlement(
            tenant_id="tenant_test",
            plan_id="plan_growth",
            plan_name="Growth",
            billing_state="active",
            access_level="full",
            enabled_features=["ai_insights"],
            restricted_features=[],
            limits={},
            warnings=[],
        )

        assert cache.set("tenant_test", cached) is True

        retrieved = cache.get("tenant_test")
        assert retrieved is not None
        assert retrieved.tenant_id == "tenant_test"

        # Clean up
        cache.invalidate("tenant_test")

    def test_entitlement_cache_invalidate(self):
        """Test cache invalidation."""
        from src.entitlements.cache import EntitlementCache, CachedEntitlement

        cache = EntitlementCache()

        cached = CachedEntitlement(
            tenant_id="tenant_inv",
            plan_id="plan_growth",
            plan_name="Growth",
            billing_state="active",
            access_level="full",
            enabled_features=[],
            restricted_features=[],
            limits={},
            warnings=[],
        )

        cache.set("tenant_inv", cached)
        assert cache.get("tenant_inv") is not None

        cache.invalidate("tenant_inv", reason="test")
        assert cache.get("tenant_inv") is None

    def test_on_billing_state_change(self):
        """Test billing state change handler."""
        from src.entitlements.cache import on_billing_state_change, get_entitlement_cache, CachedEntitlement

        cache = get_entitlement_cache()

        # Set up cached entry
        cached = CachedEntitlement(
            tenant_id="tenant_state_change",
            plan_id="plan_growth",
            plan_name="Growth",
            billing_state="active",
            access_level="full",
            enabled_features=[],
            restricted_features=[],
            limits={},
            warnings=[],
        )
        cache.set("tenant_state_change", cached)

        # Trigger state change
        on_billing_state_change(
            tenant_id="tenant_state_change",
            old_state="active",
            new_state="frozen",
        )

        # Cache should be invalidated
        assert cache.get("tenant_state_change") is None


# =============================================================================
# Audit Logger Tests
# =============================================================================

class TestAuditLogger:
    """Test suite for EntitlementAuditLogger."""

    def test_access_denial_event_creation(self):
        """Test AccessDenialEvent dataclass."""
        from src.entitlements.audit import AccessDenialEvent

        event = AccessDenialEvent(
            tenant_id="tenant_123",
            feature_name="ai_insights",
            billing_state="expired",
            plan_id="plan_free",
            reason="Feature requires Growth plan",
        )

        assert event.tenant_id == "tenant_123"
        assert event.feature_name == "ai_insights"
        assert event.event_id is not None
        assert event.timestamp is not None

    def test_access_denial_event_serialization(self):
        """Test AccessDenialEvent JSON serialization."""
        from src.entitlements.audit import AccessDenialEvent

        event = AccessDenialEvent(
            tenant_id="tenant_123",
            feature_name="ai_insights",
            billing_state="expired",
        )

        json_str = event.to_json()
        data = json.loads(json_str)

        assert data["tenant_id"] == "tenant_123"
        assert data["feature_name"] == "ai_insights"

    def test_audit_logger_log_denial(self):
        """Test logging an access denial."""
        from src.entitlements.audit import (
            EntitlementAuditLogger,
            AccessDenialEvent,
            reset_audit_logger,
        )

        reset_audit_logger()
        logger = EntitlementAuditLogger(enable_async=False, enable_database=False)

        event = AccessDenialEvent(
            tenant_id="tenant_audit",
            feature_name="data_export",
            billing_state="frozen",
            plan_id="plan_growth",
            reason="Feature restricted during payment failure",
        )

        # Should not raise
        logger.log_denial(event)

        reset_audit_logger()

    def test_log_access_denial_convenience(self):
        """Test convenience function for logging denials."""
        from src.entitlements.audit import log_access_denial, reset_audit_logger

        reset_audit_logger()

        # Should not raise
        log_access_denial(
            tenant_id="tenant_conv",
            feature_name="ai_actions",
            billing_state="past_due",
            plan_id="plan_growth",
            reason="Test denial",
        )

        reset_audit_logger()

    def test_audit_logger_aggregation(self):
        """Test event aggregation to prevent flooding."""
        from src.entitlements.audit import (
            EntitlementAuditLogger,
            AccessDenialEvent,
            reset_audit_logger,
        )

        reset_audit_logger()
        logger = EntitlementAuditLogger(enable_async=False)

        # First event should be logged
        event1 = AccessDenialEvent(
            tenant_id="tenant_agg",
            feature_name="ai_insights",
            billing_state="expired",
        )
        logger.log_denial(event1)

        # Second identical event within window should be aggregated (not logged)
        event2 = AccessDenialEvent(
            tenant_id="tenant_agg",
            feature_name="ai_insights",
            billing_state="expired",
        )
        # Internal aggregation check
        key = f"{event2.tenant_id}:{event2.feature_name}"
        should_log = logger._check_aggregation(key)
        assert should_log is False  # Aggregated

        reset_audit_logger()


# =============================================================================
# Middleware Tests
# =============================================================================

class TestEntitlementMiddleware:
    """Test suite for EntitlementMiddleware and decorators."""

    def test_payment_required_error(self):
        """Test PaymentRequiredError exception."""
        from src.entitlements.middleware import PaymentRequiredError

        error = PaymentRequiredError(
            detail="Feature requires upgrade",
            feature="ai_insights",
            billing_state="expired",
            current_plan="Free",
            required_plan="Growth",
        )

        assert error.status_code == 402
        assert error.detail["error"] == "entitlement_required"
        assert error.detail["feature"] == "ai_insights"

    def test_entitlement_context(self, temp_plans_file):
        """Test EntitlementContext class."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState
        from src.entitlements.middleware import EntitlementContext

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        rules = AccessRules(
            tenant_id="tenant_ctx",
            plan_id="plan_growth",
            billing_state=BillingState.ACTIVE,
        )

        ctx = EntitlementContext(
            tenant_id="tenant_ctx",
            access_rules=rules,
        )

        # Check feature caching
        decision1 = ctx.check_feature("ai_insights")
        decision2 = ctx.check_feature("ai_insights")

        # Should return same cached decision
        assert decision1 is decision2

        reset_entitlement_loader()

    @pytest.mark.asyncio
    async def test_require_entitlement_decorator_allowed(self, temp_plans_file):
        """Test require_entitlement decorator when access is allowed."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState
        from src.entitlements.middleware import require_entitlement, EntitlementContext
        from src.entitlements.audit import reset_audit_logger

        reset_entitlement_loader()
        reset_audit_logger()
        EntitlementLoader(config_path=temp_plans_file)

        # Create mock request
        request = Mock()
        rules = AccessRules(
            tenant_id="tenant_dec",
            plan_id="plan_growth",
            billing_state=BillingState.ACTIVE,
        )
        request.state.entitlements = EntitlementContext(
            tenant_id="tenant_dec",
            access_rules=rules,
        )
        request.url.path = "/api/test"
        request.method = "GET"

        @require_entitlement("ai_insights")
        async def test_endpoint(request):
            return {"success": True}

        result = await test_endpoint(request)
        assert result["success"] is True

        reset_entitlement_loader()
        reset_audit_logger()

    @pytest.mark.asyncio
    async def test_require_entitlement_decorator_denied(self, temp_plans_file):
        """Test require_entitlement decorator when access is denied."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState
        from src.entitlements.middleware import require_entitlement, EntitlementContext, PaymentRequiredError
        from src.entitlements.audit import reset_audit_logger

        reset_entitlement_loader()
        reset_audit_logger()
        EntitlementLoader(config_path=temp_plans_file)

        # Create mock request with free plan
        request = Mock()
        rules = AccessRules(
            tenant_id="tenant_dec_deny",
            plan_id="plan_free",
            billing_state=BillingState.ACTIVE,
        )
        request.state.entitlements = EntitlementContext(
            tenant_id="tenant_dec_deny",
            access_rules=rules,
        )
        request.url.path = "/api/test"
        request.method = "GET"

        @require_entitlement("ai_insights")
        async def test_endpoint(request):
            return {"success": True}

        with pytest.raises(PaymentRequiredError) as exc_info:
            await test_endpoint(request)

        assert exc_info.value.status_code == 402

        reset_entitlement_loader()
        reset_audit_logger()

    @pytest.mark.asyncio
    async def test_require_billing_state_decorator(self, temp_plans_file):
        """Test require_billing_state decorator."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState
        from src.entitlements.middleware import require_billing_state, EntitlementContext, PaymentRequiredError
        from src.entitlements.audit import reset_audit_logger

        reset_entitlement_loader()
        reset_audit_logger()
        EntitlementLoader(config_path=temp_plans_file)

        # Create mock request with expired state
        request = Mock()
        rules = AccessRules(
            tenant_id="tenant_state",
            plan_id="plan_growth",
            billing_state=BillingState.EXPIRED,
        )
        request.state.entitlements = EntitlementContext(
            tenant_id="tenant_state",
            access_rules=rules,
        )
        request.url.path = "/api/test"
        request.method = "POST"

        @require_billing_state([BillingState.ACTIVE, BillingState.TRIALING])
        async def test_endpoint(request):
            return {"success": True}

        with pytest.raises(PaymentRequiredError):
            await test_endpoint(request)

        reset_entitlement_loader()
        reset_audit_logger()

    def test_background_job_checker(self, temp_plans_file, mock_subscription):
        """Test BackgroundJobEntitlementChecker."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.middleware import BackgroundJobEntitlementChecker
        from src.entitlements.audit import reset_audit_logger
        from unittest.mock import MagicMock

        reset_entitlement_loader()
        reset_audit_logger()
        EntitlementLoader(config_path=temp_plans_file)

        # Mock DB session
        db_session = MagicMock()
        db_session.query.return_value.filter.return_value.first.return_value = mock_subscription

        checker = BackgroundJobEntitlementChecker(
            tenant_id="tenant_bg",
            db_session=db_session,
        )

        # Growth plan has ai_insights
        assert checker.can_execute("ai_insights", job_name="test_job") is True

        reset_entitlement_loader()
        reset_audit_logger()


# =============================================================================
# Integration Tests
# =============================================================================

class TestEntitlementIntegration:
    """Integration tests for the complete entitlement system."""

    def test_full_entitlement_flow(self, temp_plans_file):
        """Test complete entitlement flow from loading to enforcement."""
        from src.entitlements.loader import (
            EntitlementLoader,
            reset_entitlement_loader,
            get_entitlement_loader,
        )
        from src.entitlements.rules import (
            AccessRules,
            BillingState,
            create_access_rules_from_subscription,
        )
        from src.entitlements.cache import (
            EntitlementCache,
            CachedEntitlement,
            on_billing_state_change,
        )
        from src.entitlements.audit import reset_audit_logger

        reset_entitlement_loader()
        reset_audit_logger()

        # 1. Load entitlements
        loader = EntitlementLoader(config_path=temp_plans_file)

        # 2. Create mock subscription
        subscription = Mock()
        subscription.tenant_id = "tenant_int"
        subscription.plan_id = "plan_growth"
        subscription.status = "active"
        subscription.grace_period_ends_on = None
        subscription.current_period_end = datetime.now(timezone.utc) + timedelta(days=30)

        # 3. Create access rules
        rules = create_access_rules_from_subscription(
            tenant_id="tenant_int",
            subscription=subscription,
        )

        # 4. Check feature access
        assert rules.can_access_feature("ai_insights") is True
        assert rules.can_access_feature("dashboard_custom") is False  # Pro only

        # 5. Check limits
        assert rules.check_limit("max_dashboards", 5).allowed is True
        assert rules.check_limit("max_dashboards", 15).allowed is False  # Over limit

        # 6. Test cache
        cache = EntitlementCache()
        cached = CachedEntitlement(
            tenant_id="tenant_int",
            plan_id=rules.plan_id,
            plan_name="Growth",
            billing_state=rules.billing_state.value,
            access_level=rules.get_access_level().value,
            enabled_features=["ai_insights"],
            restricted_features=[],
            limits={"max_dashboards": 10},
            warnings=[],
        )
        cache.set("tenant_int", cached)
        assert cache.get("tenant_int") is not None

        # 7. Simulate billing state change
        on_billing_state_change(
            tenant_id="tenant_int",
            old_state="active",
            new_state="frozen",
        )

        # Cache should be invalidated
        assert cache.get("tenant_int") is None

        reset_entitlement_loader()
        reset_audit_logger()

    def test_grace_period_flow(self, temp_plans_file):
        """Test grace period handling."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState
        from src.entitlements.audit import reset_audit_logger

        reset_entitlement_loader()
        reset_audit_logger()
        EntitlementLoader(config_path=temp_plans_file)

        grace_ends = datetime.now(timezone.utc) + timedelta(days=2)

        rules = AccessRules(
            tenant_id="tenant_grace",
            plan_id="plan_growth",
            billing_state=BillingState.GRACE_PERIOD,
            grace_period_ends_on=grace_ends,
        )

        # Should still have access during grace period
        assert rules.is_in_grace_period() is True
        assert rules.can_access_feature("ai_insights") is True

        # Should have warnings
        warnings = rules.get_warnings()
        assert len(warnings) > 0

        # Should show days remaining
        days = rules.get_grace_period_days_remaining()
        assert days is not None
        assert days >= 1

        reset_entitlement_loader()
        reset_audit_logger()

    def test_downgrade_feature_loss(self, temp_plans_file):
        """Test feature access changes on downgrade."""
        from src.entitlements.loader import reset_entitlement_loader, EntitlementLoader
        from src.entitlements.rules import AccessRules, BillingState

        reset_entitlement_loader()
        EntitlementLoader(config_path=temp_plans_file)

        # Pro plan user
        pro_rules = AccessRules(
            tenant_id="tenant_pro",
            plan_id="plan_pro",
            billing_state=BillingState.ACTIVE,
        )

        assert pro_rules.can_access_feature("dashboard_custom") is True
        assert pro_rules.can_access_feature("ai_actions") is True

        # After downgrade to Growth
        growth_rules = AccessRules(
            tenant_id="tenant_pro",
            plan_id="plan_growth",
            billing_state=BillingState.ACTIVE,
        )

        assert growth_rules.can_access_feature("dashboard_custom") is False
        assert growth_rules.can_access_feature("ai_insights") is True

        # Check features lost
        loader = EntitlementLoader()
        lost = loader.get_features_lost_on_downgrade("plan_pro", "plan_growth")
        assert "dashboard_custom" in lost
        assert "ai_actions" in lost

        reset_entitlement_loader()


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--cov=src.entitlements", "--cov-report=term-missing"])
