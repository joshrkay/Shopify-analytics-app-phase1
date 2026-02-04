"""
Tests for Dashboard Metric Binding (Story 2.3).

Tests cover:
- DashboardMetricBinding model creation and constraints
- DashboardMetricBindingService:
  - Default binding resolution from consumers.yaml
  - DB override resolution
  - Tenant-level pin resolution
  - Repoint with governance (role check, reason required, sunset blocked)
  - Blast radius calculation
  - Pin/unpin tenant workflows
  - Audit trail
- Edge cases:
  - Repoint without permission
  - Repoint without reason
  - Repoint to sunset version
  - Unpin nonexistent pin
  - Resolution priority (tenant > global > yaml)
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.models.dashboard_metric_binding import DashboardMetricBinding
from src.services.dashboard_metric_binding_service import (
    DashboardMetricBindingService,
    BlastRadiusReport,
    BindingInfo,
    RepointResult,
    REPOINT_ALLOWED_ROLES,
)
from src.governance.metric_versioning import MetricVersionResolver


# ============================================================================
# Test Fixtures (uses shared temp_config_dir and make_yaml_config from conftest)
# ============================================================================


@pytest.fixture
def consumers_config(make_yaml_config):
    """Create test consumers.yaml configuration."""
    return make_yaml_config("consumers.yaml", {
        "dashboards": {
            "merchant_overview": {
                "description": "Primary merchant dashboard",
                "metrics": {
                    "roas": "current",
                    "revenue": "current",
                    "cac": "current",
                },
            },
            "revenue_trend": {
                "description": "Revenue trend dashboard",
                "metrics": {
                    "revenue": "current",
                },
            },
            "campaign_performance": {
                "description": "Campaign dashboard",
                "metrics": {
                    "roas": "current",
                    "cac": "current",
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
    """Create test metrics versioning configuration."""
    future_sunset = (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d")
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
                "current_version": "v1",
                "v1": {
                    "dbt_model": "metric_roas_v1",
                    "definition": "attributed_revenue / ad_spend",
                    "status": "active",
                    "released_date": "2025-06-01",
                    "description": "Attributed ROAS",
                },
                "v2": {
                    "dbt_model": "metric_roas_v2",
                    "definition": "(attributed + organic revenue) / ad_spend",
                    "status": "active",
                    "released_date": "2026-02-01",
                    "description": "Blended ROAS",
                },
            },
            "revenue": {
                "current_version": "v2",
                "v2": {
                    "dbt_model": "fact_orders",
                    "definition": "SUM(revenue)",
                    "status": "active",
                    "released_date": "2026-01-15",
                    "description": "Includes refunds",
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


# ============================================================================
# Model Tests
# ============================================================================


class TestDashboardMetricBindingModel:
    """Tests for the DashboardMetricBinding SQLAlchemy model."""

    def test_create_global_binding(self, db_session):
        """Global binding (no tenant_id) can be created."""
        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v1",
            pinned_by="admin@test.com",
            reason="Initial setup",
        )
        db_session.add(binding)
        db_session.flush()

        assert binding.id is not None
        assert binding.dashboard_id == "merchant_overview"
        assert binding.metric_name == "roas"
        assert binding.metric_version == "v1"
        assert binding.tenant_id is None
        assert binding.pinned_by == "admin@test.com"

    def test_create_tenant_binding(self, db_session):
        """Tenant-level binding override can be created."""
        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v1",
            pinned_by="admin@test.com",
            reason="Tenant pinned to v1 during migration",
            tenant_id="tenant_123",
        )
        db_session.add(binding)
        db_session.flush()

        assert binding.tenant_id == "tenant_123"

    def test_repr(self, db_session):
        """Model __repr__ is readable."""
        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v1",
        )
        assert "merchant_overview" in repr(binding)
        assert "roas" in repr(binding)
        assert "v1" in repr(binding)

    def test_tenant_repr(self, db_session):
        """Model __repr__ includes tenant when set."""
        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v1",
            tenant_id="tenant_123",
        )
        assert "tenant_123" in repr(binding)

    def test_previous_version_tracking(self, db_session):
        """Previous version is tracked for rollback."""
        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v2",
            previous_version="v1",
            reason="Upgrade to blended ROAS",
        )
        db_session.add(binding)
        db_session.flush()

        assert binding.previous_version == "v1"
        assert binding.metric_version == "v2"


# ============================================================================
# Service - Default Binding Tests
# ============================================================================


class TestDefaultBindings:
    """Tests for loading default bindings from consumers.yaml."""

    def test_get_default_bindings(self, binding_service):
        """Defaults are loaded from consumers.yaml."""
        defaults = binding_service.get_default_bindings()

        assert "merchant_overview" in defaults
        assert defaults["merchant_overview"]["roas"] == "current"
        assert defaults["merchant_overview"]["revenue"] == "current"

        assert "revenue_trend" in defaults
        assert defaults["revenue_trend"]["revenue"] == "current"

    def test_resolve_from_yaml_default(self, binding_service):
        """Resolution falls back to consumers.yaml when no DB overrides."""
        binding = binding_service.resolve_binding("merchant_overview", "roas")

        assert binding.dashboard_id == "merchant_overview"
        assert binding.metric_name == "roas"
        assert binding.metric_version == "current"
        assert binding.pinned_by is None
        assert binding.is_tenant_override is False

    def test_resolve_unknown_dashboard(self, binding_service):
        """Unknown dashboard returns 'current' as fallback."""
        binding = binding_service.resolve_binding("nonexistent_dashboard", "roas")
        assert binding.metric_version == "current"

    def test_resolve_unknown_metric(self, binding_service):
        """Unknown metric for known dashboard returns 'current'."""
        binding = binding_service.resolve_binding("merchant_overview", "nonexistent_metric")
        assert binding.metric_version == "current"


# ============================================================================
# Service - DB Override Resolution Tests
# ============================================================================


class TestDBOverrideResolution:
    """Tests for resolution with DB overrides."""

    def test_global_db_override_takes_precedence(self, binding_service, db_session):
        """Global DB binding overrides consumers.yaml default."""
        binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v2",
            pinned_by="admin@test.com",
            reason="Upgraded to blended ROAS",
        )
        db_session.add(binding)
        db_session.flush()

        result = binding_service.resolve_binding("merchant_overview", "roas")
        assert result.metric_version == "v2"
        assert result.pinned_by == "admin@test.com"
        assert result.is_tenant_override is False

    def test_tenant_override_takes_highest_precedence(self, binding_service, db_session):
        """Tenant-level DB binding overrides global DB binding."""
        # Global override
        global_binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v2",
            pinned_by="admin@test.com",
            reason="Global upgrade",
        )
        db_session.add(global_binding)

        # Tenant-level pin
        tenant_binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v1",
            pinned_by="support@test.com",
            reason="Tenant pinned to v1 during migration",
            tenant_id="tenant_123",
        )
        db_session.add(tenant_binding)
        db_session.flush()

        result = binding_service.resolve_binding(
            "merchant_overview", "roas", tenant_id="tenant_123"
        )
        assert result.metric_version == "v1"
        assert result.is_tenant_override is True
        assert result.tenant_id == "tenant_123"

    def test_no_tenant_override_falls_to_global(self, binding_service, db_session):
        """When no tenant override exists, falls back to global."""
        global_binding = DashboardMetricBinding(
            dashboard_id="merchant_overview",
            metric_name="roas",
            metric_version="v2",
            pinned_by="admin@test.com",
            reason="Global upgrade",
        )
        db_session.add(global_binding)
        db_session.flush()

        result = binding_service.resolve_binding(
            "merchant_overview", "roas", tenant_id="tenant_no_override"
        )
        assert result.metric_version == "v2"
        assert result.is_tenant_override is False


# ============================================================================
# Service - Repoint Tests
# ============================================================================


class TestRepoint:
    """Tests for repointing dashboard metric bindings."""

    def test_successful_repoint(self, binding_service):
        """Authorized repoint succeeds."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="Upgrade to blended ROAS per CR-2026-005",
            user_roles=["super_admin"],
        )

        assert result.success is True
        assert result.old_version == "current"
        assert result.new_version == "v2"
        assert result.audit_id is not None

        # Verify binding persisted
        resolved = binding_service.resolve_binding("merchant_overview", "roas")
        assert resolved.metric_version == "v2"

    def test_repoint_denied_insufficient_permissions(self, binding_service):
        """Repoint is denied for non-admin roles."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="viewer@test.com",
            reason="I want to change this",
            user_roles=["viewer"],
        )

        assert result.success is False
        assert "permissions" in result.error.lower()

    def test_repoint_denied_empty_reason(self, binding_service):
        """Repoint is denied without a reason."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="",
            user_roles=["super_admin"],
        )

        assert result.success is False
        assert "reason" in result.error.lower()

    def test_repoint_denied_whitespace_reason(self, binding_service):
        """Repoint is denied with whitespace-only reason."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="   ",
            user_roles=["super_admin"],
        )

        assert result.success is False
        assert "reason" in result.error.lower()

    def test_repoint_blocked_sunset_version(self, binding_service):
        """Cannot repoint to a sunset metric version."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="old_metric",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Want to use old version",
            user_roles=["super_admin"],
        )

        assert result.success is False
        assert "sunset" in result.error.lower()

    def test_repoint_blocked_unknown_metric(self, binding_service):
        """Cannot repoint to a nonexistent metric."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="nonexistent_metric",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Trying invalid metric",
            user_roles=["super_admin"],
        )

        assert result.success is False

    def test_repoint_to_current_allowed(self, binding_service):
        """Repointing to 'current' alias is allowed."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="current",
            repointed_by="admin@test.com",
            reason="Reverting to current alias",
            user_roles=["admin"],
        )

        assert result.success is True
        assert result.new_version == "current"

    def test_repoint_updates_existing_binding(self, binding_service, db_session):
        """Repointing an already-overridden binding updates in place."""
        # First repoint
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="First repoint",
            user_roles=["super_admin"],
        )

        # Second repoint
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Rollback to v1",
            user_roles=["super_admin"],
        )

        assert result.success is True
        assert result.old_version == "v2"
        assert result.new_version == "v1"

        # Verify only one binding row exists
        count = db_session.query(DashboardMetricBinding).filter(
            DashboardMetricBinding.dashboard_id == "merchant_overview",
            DashboardMetricBinding.metric_name == "roas",
            DashboardMetricBinding.tenant_id.is_(None),
        ).count()
        assert count == 1

    def test_analytics_admin_can_repoint(self, binding_service):
        """analytics_admin role is authorized to repoint."""
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="analytics@test.com",
            reason="Scheduled upgrade",
            user_roles=["analytics_admin"],
        )
        assert result.success is True


# ============================================================================
# Service - Tenant Pin/Unpin Tests
# ============================================================================


class TestTenantPinUnpin:
    """Tests for pinning and unpinning tenants."""

    def test_pin_tenant_to_version(self, binding_service):
        """Pin a tenant to a specific version."""
        result = binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            version="v1",
            tenant_id="tenant_123",
            pinned_by="admin@test.com",
            reason="Tenant requested to stay on v1",
            user_roles=["super_admin"],
        )

        assert result.success is True

        # Verify tenant sees pinned version
        resolved = binding_service.resolve_binding(
            "merchant_overview", "roas", tenant_id="tenant_123"
        )
        assert resolved.metric_version == "v1"
        assert resolved.is_tenant_override is True

    def test_unpin_tenant(self, binding_service):
        """Unpin a tenant, reverting to global binding."""
        # First pin
        binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            version="v1",
            tenant_id="tenant_123",
            pinned_by="admin@test.com",
            reason="Temporary pin",
            user_roles=["super_admin"],
        )

        # Unpin
        result = binding_service.unpin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            tenant_id="tenant_123",
            unpinned_by="admin@test.com",
            reason="Migration complete",
            user_roles=["super_admin"],
        )

        assert result.success is True
        assert result.old_version == "v1"

        # Verify tenant falls back to default
        resolved = binding_service.resolve_binding(
            "merchant_overview", "roas", tenant_id="tenant_123"
        )
        assert resolved.metric_version == "current"
        assert resolved.is_tenant_override is False

    def test_unpin_nonexistent_fails(self, binding_service):
        """Unpinning a tenant that has no pin fails gracefully."""
        result = binding_service.unpin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            tenant_id="tenant_no_pin",
            unpinned_by="admin@test.com",
            reason="Trying to unpin",
            user_roles=["super_admin"],
        )

        assert result.success is False
        assert "no tenant pin found" in result.error.lower()

    def test_unpin_requires_permission(self, binding_service):
        """Unpin requires admin role."""
        # Pin first
        binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            version="v1",
            tenant_id="tenant_123",
            pinned_by="admin@test.com",
            reason="Pin",
            user_roles=["super_admin"],
        )

        result = binding_service.unpin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            tenant_id="tenant_123",
            unpinned_by="viewer@test.com",
            reason="Trying to unpin",
            user_roles=["viewer"],
        )

        assert result.success is False
        assert "permissions" in result.error.lower()

    def test_unpin_requires_reason(self, binding_service):
        """Unpin requires a reason."""
        binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            version="v1",
            tenant_id="tenant_123",
            pinned_by="admin@test.com",
            reason="Pin",
            user_roles=["super_admin"],
        )

        result = binding_service.unpin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            tenant_id="tenant_123",
            unpinned_by="admin@test.com",
            reason="",
            user_roles=["super_admin"],
        )

        assert result.success is False
        assert "reason" in result.error.lower()


# ============================================================================
# Service - Blast Radius Tests
# ============================================================================


class TestBlastRadius:
    """Tests for blast radius analysis."""

    def test_blast_radius_for_roas(self, binding_service):
        """Blast radius shows all dashboards using ROAS."""
        report = binding_service.get_blast_radius(
            metric_name="roas",
            from_version="v1",
            to_version="v2",
        )

        assert report.metric_name == "roas"
        assert report.from_version == "v1"
        assert report.to_version == "v2"
        assert report.is_breaking is True

        # merchant_overview and campaign_performance both use roas
        dashboard_ids = [d["dashboard_id"] for d in report.affected_dashboards]
        assert "merchant_overview" in dashboard_ids
        assert "campaign_performance" in dashboard_ids

    def test_blast_radius_with_tenant_pins(self, binding_service, db_session):
        """Blast radius reports tenant-level pins."""
        # Pin a tenant
        binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            version="v1",
            tenant_id="tenant_pinned",
            pinned_by="admin@test.com",
            reason="Pinned for testing",
            user_roles=["super_admin"],
        )

        report = binding_service.get_blast_radius(
            metric_name="roas",
            from_version="v1",
            to_version="v2",
        )

        assert len(report.pinned_tenants) >= 1
        pinned_ids = [p["tenant_id"] for p in report.pinned_tenants]
        assert "tenant_pinned" in pinned_ids

    def test_blast_radius_metric_not_used(self, binding_service):
        """Blast radius for unused metric shows no affected dashboards."""
        report = binding_service.get_blast_radius(
            metric_name="conversion_rate",
            from_version="v1",
            to_version="v2",
        )

        assert len(report.affected_dashboards) == 0


# ============================================================================
# Service - List Bindings Tests
# ============================================================================


class TestListBindings:
    """Tests for listing bindings."""

    def test_list_all_bindings(self, binding_service):
        """Lists all bindings from consumers.yaml defaults."""
        bindings = binding_service.list_bindings()

        # merchant_overview has roas, revenue, cac (3)
        # revenue_trend has revenue (1)
        # campaign_performance has roas, cac (2)
        # Total: 6
        assert len(bindings) == 6

    def test_list_filtered_by_dashboard(self, binding_service):
        """Filter bindings by dashboard_id."""
        bindings = binding_service.list_bindings(dashboard_id="revenue_trend")

        assert len(bindings) == 1
        assert bindings[0].dashboard_id == "revenue_trend"
        assert bindings[0].metric_name == "revenue"

    def test_list_filtered_by_metric(self, binding_service):
        """Filter bindings by metric_name."""
        bindings = binding_service.list_bindings(metric_name="roas")

        dashboard_ids = {b.dashboard_id for b in bindings}
        assert "merchant_overview" in dashboard_ids
        assert "campaign_performance" in dashboard_ids

    def test_list_shows_db_overrides(self, binding_service, db_session):
        """DB overrides appear in listing with override metadata."""
        # Create a DB override
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="Upgraded",
            user_roles=["super_admin"],
        )

        bindings = binding_service.list_bindings(
            dashboard_id="merchant_overview",
            metric_name="roas",
        )

        assert len(bindings) == 1
        assert bindings[0].metric_version == "v2"
        assert bindings[0].pinned_by == "admin@test.com"


# ============================================================================
# Service - Audit Trail Tests
# ============================================================================


class TestAuditTrail:
    """Tests for audit event emission."""

    def test_repoint_emits_audit(self, binding_service):
        """Successful repoint emits audit event."""
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="Approved upgrade",
            user_roles=["super_admin"],
        )

        trail = binding_service.get_audit_trail()
        assert len(trail) >= 1

        last_event = trail[-1]
        assert last_event["action"] == "repoint"
        assert last_event["result"] == "SUCCESS"
        assert "v2" in str(last_event["context"]["new_version"])

    def test_denied_repoint_emits_audit(self, binding_service):
        """Denied repoint emits audit event with BLOCKED result."""
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="viewer@test.com",
            reason="Not allowed",
            user_roles=["viewer"],
        )

        trail = binding_service.get_audit_trail()
        blocked_events = [e for e in trail if e["result"] == "BLOCKED"]
        assert len(blocked_events) >= 1

    def test_unpin_emits_audit(self, binding_service):
        """Unpin operation emits audit event."""
        binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            version="v1",
            tenant_id="tenant_123",
            pinned_by="admin@test.com",
            reason="Pin for testing",
            user_roles=["super_admin"],
        )

        binding_service.unpin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            tenant_id="tenant_123",
            unpinned_by="admin@test.com",
            reason="Migration complete",
            user_roles=["super_admin"],
        )

        trail = binding_service.get_audit_trail()
        unpin_events = [e for e in trail if e["action"] == "unpin_tenant"]
        assert len(unpin_events) >= 1


# ============================================================================
# Service - Governance Integration Tests
# ============================================================================


class TestGovernanceIntegration:
    """Integration tests for governance enforcement."""

    def test_full_lifecycle(self, binding_service):
        """Full lifecycle: default → repoint → pin tenant → unpin → revert."""
        # 1. Default binding from YAML
        b = binding_service.resolve_binding("merchant_overview", "roas")
        assert b.metric_version == "current"

        # 2. Global repoint to v2
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v2",
            repointed_by="admin@test.com",
            reason="Approved upgrade to blended ROAS",
            user_roles=["super_admin"],
        )
        b = binding_service.resolve_binding("merchant_overview", "roas")
        assert b.metric_version == "v2"

        # 3. Pin tenant_123 to v1 (they need more migration time)
        binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            version="v1",
            tenant_id="tenant_123",
            pinned_by="support@test.com",
            reason="Tenant requested v1 during migration",
            user_roles=["admin"],
        )
        b = binding_service.resolve_binding("merchant_overview", "roas", tenant_id="tenant_123")
        assert b.metric_version == "v1"

        # Other tenants see v2
        b = binding_service.resolve_binding("merchant_overview", "roas", tenant_id="tenant_other")
        assert b.metric_version == "v2"

        # 4. Unpin tenant_123 (migration complete)
        binding_service.unpin_tenant(
            dashboard_id="merchant_overview",
            metric_name="roas",
            tenant_id="tenant_123",
            unpinned_by="support@test.com",
            reason="Migration complete",
            user_roles=["admin"],
        )
        b = binding_service.resolve_binding("merchant_overview", "roas", tenant_id="tenant_123")
        assert b.metric_version == "v2"

        # 5. Revert global to v1 if issues found
        binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="roas",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Rollback due to merchant complaints",
            user_roles=["super_admin"],
        )
        b = binding_service.resolve_binding("merchant_overview", "roas")
        assert b.metric_version == "v1"

        # Audit trail should have all events
        trail = binding_service.get_audit_trail()
        assert len(trail) >= 4

    def test_sunset_blocks_all_binding_operations(self, binding_service):
        """Sunset metric blocks both repoint and pin operations."""
        # Repoint blocked
        result = binding_service.repoint_dashboard_metric(
            dashboard_id="merchant_overview",
            metric_name="old_metric",
            new_version="v1",
            repointed_by="admin@test.com",
            reason="Want old version",
            user_roles=["super_admin"],
        )
        assert result.success is False

        # Pin blocked
        result = binding_service.pin_tenant(
            dashboard_id="merchant_overview",
            metric_name="old_metric",
            version="v1",
            tenant_id="tenant_123",
            pinned_by="admin@test.com",
            reason="Want old version",
            user_roles=["super_admin"],
        )
        assert result.success is False

    def test_allowed_roles_constant(self):
        """REPOINT_ALLOWED_ROLES includes expected roles."""
        assert "super_admin" in REPOINT_ALLOWED_ROLES
        assert "admin" in REPOINT_ALLOWED_ROLES
        assert "analytics_admin" in REPOINT_ALLOWED_ROLES
        assert "viewer" not in REPOINT_ALLOWED_ROLES
