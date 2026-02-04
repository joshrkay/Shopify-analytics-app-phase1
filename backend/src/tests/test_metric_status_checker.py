"""
Tests for MetricStatusChecker (Story 2.3 - Dashboard Safeguards).

Tests cover:
- MetricStatusChecker.check_dashboard_metric():
  - "current" binding always returns show=False
  - Active metric with no newer version returns show=False
  - Active metric with newer version returns info banner
  - Deprecated metric returns warning banner with countdown
  - Sunset metric raises MetricSunsetError (hard-fail)
  - Missing metric version raises MetricVersionNotFoundError
- MetricStatusChecker.check_all_dashboard_metrics():
  - Collects banners for all metrics on a dashboard
  - Raises immediately for sunset metrics
- MetricStatusChecker.validate_all_bindings():
  - Reports sunset, deprecated, and missing version issues
  - Skips "current" bindings
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.governance.metric_versioning import MetricVersionResolver
from src.services.dashboard_metric_binding_service import (
    DashboardMetricBindingService,
)
from src.services.metric_status_checker import (
    MetricStatusChecker,
    MetricSunsetError,
    MetricVersionNotFoundError,
    BannerData,
)


# ============================================================================
# Test Fixtures (uses shared temp_config_dir and make_yaml_config from conftest)
# ============================================================================


@pytest.fixture
def consumers_config(make_yaml_config):
    """Create test consumers.yaml for status checker tests."""
    return make_yaml_config("consumers.yaml", {
        "dashboards": {
            "merchant_overview": {
                "description": "Primary merchant dashboard",
                "metrics": {
                    "roas": "current",
                    "revenue": "current",
                },
            },
            "campaign_performance": {
                "description": "Campaign dashboard",
                "metrics": {
                    "roas": "current",
                },
            },
        },
        "governance": {
            "repoint_roles": ["super_admin", "analytics_admin"],
            "require_reason": True,
            "emit_audit_event": True,
            "block_if_version_sunset": True,
        },
    })


@pytest.fixture
def metrics_config(make_yaml_config):
    """Create test metrics config with varied statuses for status checker."""
    future_sunset = (datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d")
    past_sunset = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")

    return make_yaml_config("metrics_versions.yaml", {
        "deprecation_enforcement": {
            "warn_on_query": True,
            "warn_days_before_sunset": 30,
            "block_on_sunset": True,
            "merchant_visibility": ["dashboard_banner"],
        },
        "metrics": {
            "roas": {
                "current_version": "v2",
                "v1": {
                    "dbt_model": "metric_roas_v1",
                    "definition": "attributed_revenue / ad_spend",
                    "status": "active",
                    "released_date": "2025-06-01",
                },
                "v2": {
                    "dbt_model": "metric_roas_v2",
                    "definition": "(attributed + organic revenue) / ad_spend",
                    "status": "active",
                    "released_date": "2026-02-01",
                },
            },
            "revenue": {
                "current_version": "v2",
                "v2": {
                    "dbt_model": "fact_orders",
                    "definition": "SUM(revenue)",
                    "status": "active",
                    "released_date": "2026-01-15",
                },
                "v1": {
                    "dbt_model": "fact_orders_legacy",
                    "definition": "SUM(revenue) WHERE refund_status != returned",
                    "status": "deprecated",
                    "deprecated_date": "2026-01-15",
                    "sunset_date": future_sunset,
                    "migration_guide": "docs/migrate.md",
                },
            },
            "old_metric": {
                "current_version": "v2",
                "v2": {
                    "dbt_model": "new_model",
                    "definition": "new definition",
                    "status": "active",
                    "released_date": "2026-01-01",
                },
                "v1": {
                    "dbt_model": "old_model",
                    "definition": "old definition",
                    "status": "sunset",
                    "sunset_date": past_sunset,
                },
            },
        },
    })


@pytest.fixture
def metric_resolver(metrics_config):
    """Create a MetricVersionResolver from test config."""
    return MetricVersionResolver(config_path=metrics_config)


@pytest.fixture
def binding_service(db_session, consumers_config, metric_resolver):
    """Create a DashboardMetricBindingService for testing."""
    return DashboardMetricBindingService(
        db=db_session,
        consumers_config_path=consumers_config,
        metric_resolver=metric_resolver,
    )


@pytest.fixture
def status_checker(binding_service, metric_resolver):
    """Create a MetricStatusChecker for testing."""
    return MetricStatusChecker(
        binding_service=binding_service,
        metric_resolver=metric_resolver,
    )


# ============================================================================
# check_dashboard_metric - "current" binding
# ============================================================================


class TestCurrentBinding:
    """Tests for 'current' alias bindings (no sunset risk)."""

    def test_current_binding_returns_hidden_banner(self, status_checker):
        """Binding to 'current' always returns show=False."""
        banner = status_checker.check_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
        )

        assert banner.show is False
        assert banner.tone == "info"
        assert banner.current_version == "current"
        assert banner.dashboard_id == "merchant_overview"
        assert banner.metric_name == "roas"

    def test_current_binding_with_tenant(self, status_checker):
        """'current' binding with tenant_id still returns show=False."""
        banner = status_checker.check_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            tenant_id="tenant_123",
        )

        assert banner.show is False
        assert banner.current_version == "current"


# ============================================================================
# check_dashboard_metric - Active version with newer available
# ============================================================================


class TestActiveWithNewerVersion:
    """Tests for active metrics where a newer version exists."""

    def test_pinned_to_old_version_shows_info_banner(self, status_checker, binding_service):
        """Dashboard pinned to v1 when v2 is current shows info banner."""
        # Repoint merchant_overview's ROAS to v1 (current is v2 in our fixture)
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Pin to v1 for testing",
            user_roles=["super_admin"],
        )

        banner = status_checker.check_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
        )

        assert banner.show is True
        assert banner.tone == "info"
        assert banner.current_version == "v1"
        assert banner.new_version_available == "v2"
        assert "newer version" in banner.message.lower() or "v2" in banner.message

    def test_pinned_to_current_version_shows_nothing(self, status_checker, binding_service):
        """Dashboard pinned to the current version shows no banner."""
        # Repoint to v2, which IS the current_version in our fixture
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="Pin to current",
            user_roles=["super_admin"],
        )

        banner = status_checker.check_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
        )

        assert banner.show is False
        assert banner.current_version == "v2"


# ============================================================================
# check_dashboard_metric - Deprecated version
# ============================================================================


class TestDeprecatedVersion:
    """Tests for deprecated metric versions (warning banners)."""

    def test_deprecated_version_shows_warning_banner(self, status_checker, binding_service):
        """Dashboard bound to deprecated version shows warning banner."""
        # Repoint to revenue v1 (deprecated in our fixture)
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Testing deprecation banner",
            user_roles=["super_admin"],
        )

        banner = status_checker.check_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
        )

        assert banner.show is True
        assert banner.tone == "warning"
        assert banner.current_version == "v1"
        assert "deprecated" in banner.message.lower()

    def test_deprecated_version_has_sunset_countdown(self, status_checker, binding_service):
        """Deprecated version banner includes days_until_sunset."""
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Testing countdown",
            user_roles=["super_admin"],
        )

        banner = status_checker.check_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
        )

        assert banner.days_until_sunset is not None
        assert banner.days_until_sunset > 0

    def test_deprecated_version_has_change_date(self, status_checker, binding_service):
        """Deprecated version banner includes change_date."""
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Testing change date",
            user_roles=["super_admin"],
        )

        banner = status_checker.check_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
        )

        assert banner.change_date is not None


# ============================================================================
# check_dashboard_metric - Sunset version (hard-fail)
# ============================================================================


class TestSunsetHardFail:
    """Tests for sunset metric versions (hard-fail enforcement)."""

    def test_sunset_version_raises_error(self, status_checker, binding_service, db_session):
        """Dashboard bound to sunset version raises MetricSunsetError."""
        # Directly insert a binding to the sunset old_metric v1
        # (We can't use repoint because it blocks sunset versions)
        from src.models.dashboard_metric_binding import DashboardMetricBinding

        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="old_metric",
            metric_version="v1",
            pinned_by="legacy@test.com",
            reason="Legacy binding",
        )
        db_session.add(binding)
        db_session.flush()

        with pytest.raises(MetricSunsetError) as exc_info:
            status_checker.check_dashboard_metric(
                dashboard_id="merchant_overview",
                metric_name="old_metric",
            )

        assert exc_info.value.dashboard_id == "merchant_overview"
        assert exc_info.value.metric_name == "old_metric"
        assert exc_info.value.version == "v1"
        assert "retired" in str(exc_info.value).lower() or "repoint" in str(exc_info.value).lower()

    def test_sunset_error_contains_action_guidance(self, status_checker, binding_service, db_session):
        """MetricSunsetError message tells the user what to do."""
        from src.models.dashboard_metric_binding import DashboardMetricBinding

        binding = DashboardMetricBinding(
            dashboard_id="campaign_performance",
            metric_name="old_metric",
            metric_version="v1",
            pinned_by="legacy@test.com",
            reason="Legacy binding",
        )
        db_session.add(binding)
        db_session.flush()

        with pytest.raises(MetricSunsetError) as exc_info:
            status_checker.check_dashboard_metric(
                dashboard_id="campaign_performance",
                metric_name="old_metric",
            )

        error_msg = str(exc_info.value)
        assert "repoint" in error_msg.lower() or "active version" in error_msg.lower()


# ============================================================================
# check_dashboard_metric - Version not found
# ============================================================================


class TestVersionNotFound:
    """Tests for bindings referencing nonexistent metric versions."""

    def test_unknown_version_raises_error(self, status_checker, db_session):
        """Binding to nonexistent version raises MetricVersionNotFoundError."""
        from src.models.dashboard_metric_binding import DashboardMetricBinding

        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v99",
            pinned_by="test@test.com",
            reason="Bad version",
        )
        db_session.add(binding)
        db_session.flush()

        with pytest.raises(MetricVersionNotFoundError) as exc_info:
            status_checker.check_dashboard_metric(
                dashboard_id="merchant_overview",
                metric_name="roas",
            )

        assert exc_info.value.dashboard_id == "merchant_overview"
        assert exc_info.value.metric_name == "roas"
        assert exc_info.value.version == "v99"

    def test_unknown_metric_raises_error(self, status_checker, db_session):
        """Binding to nonexistent metric name raises MetricVersionNotFoundError."""
        from src.models.dashboard_metric_binding import DashboardMetricBinding

        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="nonexistent",
            metric_version="v1",
            pinned_by="test@test.com",
            reason="Bad metric",
        )
        db_session.add(binding)
        db_session.flush()

        with pytest.raises(MetricVersionNotFoundError):
            status_checker.check_dashboard_metric(
                dashboard_id="merchant_overview",
                metric_name="nonexistent",
            )


# ============================================================================
# check_all_dashboard_metrics
# ============================================================================


class TestCheckAllDashboardMetrics:
    """Tests for checking all metrics on a dashboard."""

    def test_returns_only_visible_banners(self, status_checker):
        """check_all returns only banners with show=True."""
        # All defaults are "current" which return show=False
        banners = status_checker.check_all_dashboard_metrics(
            dashboard_id="merchant_overview",
        )

        assert len(banners) == 0

    def test_returns_warning_banners(self, status_checker, binding_service):
        """Deprecated bindings appear in check_all results."""
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Testing",
            user_roles=["super_admin"],
        )

        banners = status_checker.check_all_dashboard_metrics(
            dashboard_id="merchant_overview",
        )

        assert len(banners) >= 1
        warning_banners = [b for b in banners if b.tone == "warning"]
        assert len(warning_banners) >= 1

    def test_sunset_raises_immediately(self, status_checker, db_session):
        """check_all raises MetricSunsetError immediately for sunset metrics."""
        from src.models.dashboard_metric_binding import DashboardMetricBinding

        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="old_metric",
            metric_version="v1",
            pinned_by="legacy@test.com",
            reason="Legacy binding",
        )
        db_session.add(binding)
        db_session.flush()

        with pytest.raises(MetricSunsetError):
            status_checker.check_all_dashboard_metrics(
                dashboard_id="merchant_overview",
            )


# ============================================================================
# validate_all_bindings
# ============================================================================


class TestValidateAllBindings:
    """Tests for bulk validation of all bindings."""

    def test_clean_bindings_return_no_issues(self, status_checker):
        """All defaults are 'current' so no issues should be found."""
        issues = status_checker.validate_all_bindings()

        assert isinstance(issues, list)
        assert len(issues) == 0

    def test_sunset_binding_reported_as_critical(self, status_checker, db_session):
        """Sunset bindings are reported as critical issues."""
        from src.models.dashboard_metric_binding import DashboardMetricBinding

        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="old_metric",
            metric_version="v1",
            pinned_by="legacy@test.com",
            reason="Legacy binding",
        )
        db_session.add(binding)
        db_session.flush()

        issues = status_checker.validate_all_bindings()

        critical_issues = [i for i in issues if i["level"] == "critical"]
        assert len(critical_issues) >= 1
        assert critical_issues[0]["metric_name"] == "old_metric"
        assert critical_issues[0]["version"] == "v1"

    def test_deprecated_binding_reported_as_warning(self, status_checker, binding_service):
        """Deprecated bindings are reported as warning issues."""
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="revenue",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Testing validation",
            user_roles=["super_admin"],
        )

        issues = status_checker.validate_all_bindings()

        warning_issues = [i for i in issues if i["level"] == "warning"]
        assert len(warning_issues) >= 1
        assert warning_issues[0]["metric_name"] == "revenue"

    def test_missing_version_reported_as_critical(self, status_checker, db_session):
        """Bindings to nonexistent versions are reported as critical."""
        from src.models.dashboard_metric_binding import DashboardMetricBinding

        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v999",
            pinned_by="test@test.com",
            reason="Bad version",
        )
        db_session.add(binding)
        db_session.flush()

        issues = status_checker.validate_all_bindings()

        critical_issues = [i for i in issues if i["level"] == "critical"]
        version_missing = [i for i in critical_issues if i["version"] == "v999"]
        assert len(version_missing) >= 1
        assert "does not exist" in version_missing[0]["issue"].lower()

    def test_current_bindings_are_skipped(self, status_checker):
        """Bindings with version='current' are not validated."""
        # All defaults are "current", should be skipped entirely
        issues = status_checker.validate_all_bindings()
        assert len(issues) == 0


# ============================================================================
# BannerData dataclass
# ============================================================================


class TestBannerData:
    """Tests for BannerData dataclass structure."""

    def test_banner_data_defaults(self):
        """BannerData has correct default values."""
        banner = BannerData(
            show=True,
            tone="warning",
            dashboard_id="test_dashboard",
            metric_name="test_metric",
            current_version="v1",
            message="Test message",
        )

        assert banner.change_date is None
        assert banner.new_version_available is None
        assert banner.days_until_sunset is None

    def test_banner_data_full(self):
        """BannerData can hold all fields."""
        banner = BannerData(
            show=True,
            tone="critical",
            dashboard_id="merchant_overview",
            metric_name="roas",
            current_version="v1",
            message="Version retired",
            change_date="2026-01-15",
            new_version_available="v2",
            days_until_sunset=0,
        )

        assert banner.show is True
        assert banner.tone == "critical"
        assert banner.change_date == "2026-01-15"
        assert banner.new_version_available == "v2"
        assert banner.days_until_sunset == 0


# ============================================================================
# Exception classes
# ============================================================================


class TestExceptions:
    """Tests for MetricSunsetError and MetricVersionNotFoundError."""

    def test_sunset_error_attributes(self):
        """MetricSunsetError stores dashboard, metric, version."""
        err = MetricSunsetError(
            dashboard_id="dash_1",
            metric_name="roas",
            version="v1",
            message="Version retired",
        )

        assert err.dashboard_id == "dash_1"
        assert err.metric_name == "roas"
        assert err.version == "v1"
        assert str(err) == "Version retired"

    def test_version_not_found_error_attributes(self):
        """MetricVersionNotFoundError stores dashboard, metric, version."""
        err = MetricVersionNotFoundError(
            dashboard_id="dash_1",
            metric_name="roas",
            version="v99",
        )

        assert err.dashboard_id == "dash_1"
        assert err.metric_name == "roas"
        assert err.version == "v99"
        assert "v99" in str(err)
        assert "roas" in str(err)
        assert "dash_1" in str(err)

    def test_sunset_error_is_exception(self):
        """MetricSunsetError inherits from Exception."""
        assert issubclass(MetricSunsetError, Exception)

    def test_version_not_found_is_exception(self):
        """MetricVersionNotFoundError inherits from Exception."""
        assert issubclass(MetricVersionNotFoundError, Exception)
