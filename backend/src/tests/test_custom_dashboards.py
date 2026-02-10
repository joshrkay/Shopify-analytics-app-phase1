"""
Tests for Custom Dashboards feature.

Covers:
- Model creation and constraints
- Service layer CRUD with versioning and audit
- Edge cases: TOCTOU limit enforcement, optimistic locking,
  name conflicts, version cap, archive/restore, share access resolution

Phase: Custom Reports & Dashboard Builder
"""

import uuid
import pytest
from datetime import datetime, timezone, timedelta

from src.models.custom_dashboard import CustomDashboard, DashboardStatus
from src.models.custom_report import CustomReport, ChartType
from src.models.dashboard_version import DashboardVersion, MAX_DASHBOARD_VERSIONS
from src.models.dashboard_share import DashboardShare, SharePermission
from src.models.dashboard_audit import DashboardAudit, DashboardAuditAction
from src.models.report_template import ReportTemplate, TemplateCategory
from src.services.custom_dashboard_service import (
    CustomDashboardService,
    DashboardNotFoundError,
    DashboardLimitExceededError,
    DashboardConflictError,
    DashboardNameConflictError,
)
from src.services.custom_report_service import (
    CustomReportService,
    ReportNotFoundError,
    ReportNameConflictError,
)
from src.services.dashboard_share_service import (
    DashboardShareService,
    ShareNotFoundError,
    ShareConflictError,
    ShareValidationError,
)
from src.services.report_template_service import (
    ReportTemplateService,
    TemplateNotFoundError,
    TemplateRequirementsError,
)


TENANT_ID = "test-tenant-001"
USER_ID = "test-user-001"
OTHER_USER_ID = "test-user-002"


def _make_chart_config():
    """Factory for valid chart config JSON."""
    return {
        "metrics": [{"column": "total_revenue", "aggregation": "SUM"}],
        "dimensions": [],
        "time_range": "Last 30 days",
        "time_grain": "P1D",
        "filters": [],
        "display": {"color_scheme": "default", "show_legend": True},
    }


def _make_position(x=0, y=0, w=6, h=4):
    """Factory for valid grid position JSON."""
    return {"x": x, "y": y, "w": w, "h": h}


# =============================================================================
# Model Tests
# =============================================================================


class TestCustomDashboardModel:
    """Test CustomDashboard model creation and defaults."""

    def test_create_dashboard(self, db_session):
        dashboard = CustomDashboard(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            name="Test Dashboard",
            status=DashboardStatus.DRAFT.value,
            layout_json={},
            version_number=1,
            created_by=USER_ID,
        )
        db_session.add(dashboard)
        db_session.flush()

        assert dashboard.id is not None
        assert dashboard.tenant_id == TENANT_ID
        assert dashboard.status == "draft"
        assert dashboard.version_number == 1
        assert dashboard.created_at is not None

    def test_default_status_is_draft(self, db_session):
        dashboard = CustomDashboard(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            name="Defaults Test",
            layout_json={},
            version_number=1,
            created_by=USER_ID,
        )
        db_session.add(dashboard)
        db_session.flush()

        assert dashboard.status == DashboardStatus.DRAFT.value

    def test_cascade_delete_reports(self, db_session):
        dashboard = CustomDashboard(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            name="Cascade Test",
            status="draft",
            layout_json={},
            version_number=1,
            created_by=USER_ID,
        )
        db_session.add(dashboard)
        db_session.flush()

        report = CustomReport(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            dashboard_id=dashboard.id,
            name="Test Chart",
            chart_type="line",
            dataset_name="fact_orders",
            config_json=_make_chart_config(),
            position_json=_make_position(),
            created_by=USER_ID,
        )
        db_session.add(report)
        db_session.flush()

        report_id = report.id
        db_session.delete(dashboard)
        db_session.flush()

        assert db_session.get(CustomReport, report_id) is None


class TestCustomReportModel:
    """Test CustomReport model creation."""

    def test_create_report(self, db_session):
        dashboard = CustomDashboard(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            name="Parent Dashboard",
            status="draft",
            layout_json={},
            version_number=1,
            created_by=USER_ID,
        )
        db_session.add(dashboard)
        db_session.flush()

        report = CustomReport(
            id=str(uuid.uuid4()),
            tenant_id=TENANT_ID,
            dashboard_id=dashboard.id,
            name="Revenue Chart",
            chart_type=ChartType.LINE.value,
            dataset_name="fact_orders_current",
            config_json=_make_chart_config(),
            position_json=_make_position(),
            created_by=USER_ID,
        )
        db_session.add(report)
        db_session.flush()

        assert report.id is not None
        assert report.chart_type == "line"
        assert report.sort_order == 0


# =============================================================================
# Dashboard Service Tests
# =============================================================================


class TestCustomDashboardService:
    """Test CustomDashboardService business logic."""

    def _service(self, db_session, user_id=USER_ID):
        return CustomDashboardService(db_session, TENANT_ID, user_id)

    def test_create_dashboard_happy_path(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="My Dashboard")

        assert dashboard.name == "My Dashboard"
        assert dashboard.status == "draft"
        assert dashboard.version_number == 1
        assert dashboard.created_by == USER_ID

    def test_create_dashboard_creates_version(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Versioned")

        versions = db_session.query(DashboardVersion).filter(
            DashboardVersion.dashboard_id == dashboard.id,
        ).all()
        assert len(versions) == 1
        assert versions[0].version_number == 1
        assert versions[0].change_summary == "Created dashboard"

    def test_create_dashboard_creates_audit_entry(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Audited")

        audits = db_session.query(DashboardAudit).filter(
            DashboardAudit.dashboard_id == dashboard.id,
        ).all()
        assert len(audits) == 1
        assert audits[0].action == DashboardAuditAction.CREATED.value

    def test_create_dashboard_enforces_limit(self, db_session):
        service = self._service(db_session)

        service.create_dashboard(name="First", max_dashboards=2)
        service.create_dashboard(name="Second", max_dashboards=2)

        with pytest.raises(DashboardLimitExceededError) as exc_info:
            service.create_dashboard(name="Third", max_dashboards=2)

        assert exc_info.value.current_count == 2
        assert exc_info.value.max_count == 2

    def test_create_dashboard_unlimited_when_none(self, db_session):
        service = self._service(db_session)
        # None means unlimited — should not raise
        for i in range(5):
            service.create_dashboard(name=f"Dashboard {i}", max_dashboards=None)

    def test_create_dashboard_unlimited_when_negative_one(self, db_session):
        service = self._service(db_session)
        # -1 means unlimited
        for i in range(3):
            service.create_dashboard(name=f"Unlimited {i}", max_dashboards=-1)

    def test_list_dashboards_excludes_archived(self, db_session):
        service = self._service(db_session)
        d1 = service.create_dashboard(name="Active")
        d2 = service.create_dashboard(name="To Archive")
        service.publish_dashboard(d2.id)
        service.archive_dashboard(d2.id)

        dashboards, total = service.list_dashboards()
        assert total == 1
        assert dashboards[0].id == d1.id

    def test_update_dashboard_increments_version(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Original")

        updated = service.update_dashboard(dashboard.id, name="Updated Name")
        assert updated.version_number == 2
        assert updated.name == "Updated Name"

    def test_update_dashboard_optimistic_lock_rejects_stale(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Locked")

        stale_time = dashboard.updated_at - timedelta(seconds=10)

        with pytest.raises(DashboardConflictError):
            service.update_dashboard(
                dashboard.id,
                name="Conflict",
                expected_updated_at=stale_time,
            )

    def test_publish_dashboard(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="To Publish")

        published = service.publish_dashboard(dashboard.id)
        assert published.status == DashboardStatus.PUBLISHED.value

    def test_archive_dashboard_only_owner(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Owner Only")

        other_service = self._service(db_session, user_id=OTHER_USER_ID)
        with pytest.raises(DashboardNotFoundError):
            other_service.archive_dashboard(dashboard.id)

    def test_duplicate_dashboard_clones_reports(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Original")

        report_service = CustomReportService(db_session, TENANT_ID, USER_ID)
        report_service.add_report(
            dashboard_id=dashboard.id,
            name="Chart 1",
            chart_type="line",
            dataset_name="fact_orders",
            config_json=_make_chart_config(),
            position_json=_make_position(),
        )

        clone = service.duplicate_dashboard(dashboard.id, "Clone")
        assert clone.name == "Clone"
        assert len(clone.reports) == 1
        assert clone.reports[0].name == "Chart 1"
        assert clone.reports[0].id != dashboard.reports[0].id

    def test_get_dashboard_wrong_tenant_returns_not_found(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Tenant Scoped")

        other_tenant_service = CustomDashboardService(db_session, "other-tenant", USER_ID)
        with pytest.raises(DashboardNotFoundError):
            other_tenant_service.get_dashboard(dashboard.id)


# =============================================================================
# Version Management Tests
# =============================================================================


class TestVersionManagement:
    """Test version history and restore."""

    def _service(self, db_session):
        return CustomDashboardService(db_session, TENANT_ID, USER_ID)

    def test_version_history_tracks_changes(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Tracked")

        service.update_dashboard(dashboard.id, name="Renamed")
        service.update_dashboard(dashboard.id, description="Added desc")

        versions, total = service.list_versions(dashboard.id)
        assert total == 3  # create + 2 updates
        # Newest first
        assert versions[0].version_number == 3
        assert versions[2].version_number == 1

    def test_restore_version(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="V1 Name")
        service.update_dashboard(dashboard.id, name="V2 Name")

        restored = service.restore_version(dashboard.id, version_number=1)
        assert restored.name == "V1 Name"
        assert restored.version_number == 3  # New version after restore

    def test_restore_nonexistent_version_fails(self, db_session):
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Test")

        with pytest.raises(DashboardNotFoundError, match="Version 999 not found"):
            service.restore_version(dashboard.id, version_number=999)

    def test_version_cap_enforcement(self, db_session):
        """Oldest version is pruned when cap is exceeded."""
        service = self._service(db_session)
        dashboard = service.create_dashboard(name="Cap Test")

        # Create MAX_DASHBOARD_VERSIONS + 5 updates
        for i in range(MAX_DASHBOARD_VERSIONS + 5):
            service.update_dashboard(dashboard.id, description=f"Update {i}")

        versions, total = service.list_versions(dashboard.id)
        assert total <= MAX_DASHBOARD_VERSIONS


# =============================================================================
# Report Service Tests
# =============================================================================


class TestCustomReportService:
    """Test CustomReportService business logic."""

    def _setup(self, db_session):
        dash_service = CustomDashboardService(db_session, TENANT_ID, USER_ID)
        dashboard = dash_service.create_dashboard(name="Report Host")
        report_service = CustomReportService(db_session, TENANT_ID, USER_ID)
        return dashboard, report_service

    def test_add_report(self, db_session):
        dashboard, service = self._setup(db_session)

        report = service.add_report(
            dashboard_id=dashboard.id,
            name="Revenue Chart",
            chart_type="line",
            dataset_name="fact_orders",
            config_json=_make_chart_config(),
            position_json=_make_position(),
        )

        assert report.name == "Revenue Chart"
        assert report.chart_type == "line"
        assert report.sort_order == 0

    def test_add_report_increments_dashboard_version(self, db_session):
        dashboard, service = self._setup(db_session)
        initial_version = dashboard.version_number

        service.add_report(
            dashboard_id=dashboard.id,
            name="New Chart",
            chart_type="bar",
            dataset_name="fact_orders",
            config_json=_make_chart_config(),
            position_json=_make_position(),
        )

        db_session.refresh(dashboard)
        assert dashboard.version_number == initial_version + 1

    def test_add_report_duplicate_name_fails(self, db_session):
        dashboard, service = self._setup(db_session)

        service.add_report(
            dashboard_id=dashboard.id,
            name="Same Name",
            chart_type="line",
            dataset_name="fact_orders",
            config_json=_make_chart_config(),
            position_json=_make_position(),
        )

        with pytest.raises(ReportNameConflictError):
            service.add_report(
                dashboard_id=dashboard.id,
                name="Same Name",
                chart_type="bar",
                dataset_name="fact_orders",
                config_json=_make_chart_config(),
                position_json=_make_position(x=6),
            )

    def test_update_report(self, db_session):
        dashboard, service = self._setup(db_session)

        report = service.add_report(
            dashboard_id=dashboard.id,
            name="Original",
            chart_type="line",
            dataset_name="fact_orders",
            config_json=_make_chart_config(),
            position_json=_make_position(),
        )

        updated = service.update_report(
            dashboard_id=dashboard.id,
            report_id=report.id,
            name="Renamed",
        )

        assert updated.name == "Renamed"

    def test_remove_report(self, db_session):
        dashboard, service = self._setup(db_session)

        report = service.add_report(
            dashboard_id=dashboard.id,
            name="To Remove",
            chart_type="kpi",
            dataset_name="fact_orders",
            config_json=_make_chart_config(),
            position_json=_make_position(w=3, h=2),
        )

        service.remove_report(dashboard.id, report.id)

        with pytest.raises(ReportNotFoundError):
            service.get_report(dashboard.id, report.id)

    def test_reorder_reports(self, db_session):
        dashboard, service = self._setup(db_session)

        r1 = service.add_report(
            dashboard_id=dashboard.id, name="A",
            chart_type="line", dataset_name="fact_orders",
            config_json=_make_chart_config(), position_json=_make_position(),
        )
        r2 = service.add_report(
            dashboard_id=dashboard.id, name="B",
            chart_type="bar", dataset_name="fact_orders",
            config_json=_make_chart_config(), position_json=_make_position(x=6),
        )

        reordered = service.reorder_reports(dashboard.id, [r2.id, r1.id])
        assert reordered[0].id == r2.id
        assert reordered[0].sort_order == 0
        assert reordered[1].id == r1.id
        assert reordered[1].sort_order == 1

    def test_kpi_min_dimensions_enforced(self, db_session):
        dashboard, service = self._setup(db_session)

        with pytest.raises(ValueError, match="minimum size"):
            service.add_report(
                dashboard_id=dashboard.id,
                name="Tiny KPI",
                chart_type="kpi",
                dataset_name="fact_orders",
                config_json=_make_chart_config(),
                position_json=_make_position(w=1, h=1),  # Too small for KPI (needs 3x2)
            )


# =============================================================================
# Share Service Tests
# =============================================================================


class TestDashboardShareService:
    """Test DashboardShareService business logic."""

    def _setup(self, db_session):
        dash_service = CustomDashboardService(db_session, TENANT_ID, USER_ID)
        dashboard = dash_service.create_dashboard(name="Shared Dashboard")
        share_service = DashboardShareService(db_session, TENANT_ID, USER_ID)
        return dashboard, share_service

    def test_create_share(self, db_session):
        dashboard, service = self._setup(db_session)

        share = service.create_share(
            dashboard_id=dashboard.id,
            shared_with_user_id=OTHER_USER_ID,
            permission="view",
        )

        assert share.shared_with_user_id == OTHER_USER_ID
        assert share.permission == "view"

    def test_cannot_share_with_owner(self, db_session):
        dashboard, service = self._setup(db_session)

        with pytest.raises(ShareValidationError, match="owner"):
            service.create_share(
                dashboard_id=dashboard.id,
                shared_with_user_id=USER_ID,  # Same as creator
                permission="view",
            )

    def test_duplicate_share_fails(self, db_session):
        dashboard, service = self._setup(db_session)

        service.create_share(
            dashboard_id=dashboard.id,
            shared_with_user_id=OTHER_USER_ID,
            permission="view",
        )

        with pytest.raises(ShareConflictError):
            service.create_share(
                dashboard_id=dashboard.id,
                shared_with_user_id=OTHER_USER_ID,
                permission="edit",
            )

    def test_update_share_permission(self, db_session):
        dashboard, service = self._setup(db_session)

        share = service.create_share(
            dashboard_id=dashboard.id,
            shared_with_user_id=OTHER_USER_ID,
            permission="view",
        )

        updated = service.update_share(dashboard.id, share.id, permission="edit")
        assert updated.permission == "edit"

    def test_revoke_share(self, db_session):
        dashboard, service = self._setup(db_session)

        share = service.create_share(
            dashboard_id=dashboard.id,
            shared_with_user_id=OTHER_USER_ID,
            permission="view",
        )

        service.revoke_share(dashboard.id, share.id)

        with pytest.raises(ShareNotFoundError):
            service.revoke_share(dashboard.id, share.id)

    def test_resolve_access_owner(self, db_session):
        dashboard, service = self._setup(db_session)

        dash_service = CustomDashboardService(db_session, TENANT_ID, USER_ID)
        access = dash_service.get_access_level(dashboard)
        assert access == "owner"

    def test_resolve_access_shared_user(self, db_session):
        dashboard, service = self._setup(db_session)

        service.create_share(
            dashboard_id=dashboard.id,
            shared_with_user_id=OTHER_USER_ID,
            permission="edit",
        )

        other_service = CustomDashboardService(db_session, TENANT_ID, OTHER_USER_ID)
        access = other_service.get_access_level(dashboard)
        assert access == "edit"

    def test_expired_share_returns_no_access(self, db_session):
        dashboard, service = self._setup(db_session)

        service.create_share(
            dashboard_id=dashboard.id,
            shared_with_user_id=OTHER_USER_ID,
            permission="edit",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        other_service = CustomDashboardService(db_session, TENANT_ID, OTHER_USER_ID)
        access = other_service.get_access_level(dashboard)
        assert access == "none"

    def test_non_owner_cannot_manage_shares(self, db_session):
        dashboard, _ = self._setup(db_session)

        other_service = DashboardShareService(db_session, TENANT_ID, OTHER_USER_ID)
        with pytest.raises(DashboardNotFoundError, match="permission"):
            other_service.list_shares(dashboard.id)


# =============================================================================
# Template Service Tests
# =============================================================================


class TestReportTemplateService:
    """Test ReportTemplateService business logic."""

    def _seed_template(self, db_session, min_tier="growth"):
        template = ReportTemplate(
            id=str(uuid.uuid4()),
            name=f"Test Template {uuid.uuid4().hex[:6]}",
            description="A test template",
            category=TemplateCategory.SALES.value,
            layout_json={"columns": 12},
            reports_json=[
                {
                    "name": "Revenue KPI",
                    "chart_type": "kpi",
                    "dataset_name": "fact_orders_current",
                    "config_json": _make_chart_config(),
                    "position_json": _make_position(w=3, h=2),
                },
            ],
            required_datasets=["fact_orders_current"],
            min_billing_tier=min_tier,
            sort_order=0,
            is_active=True,
        )
        db_session.add(template)
        db_session.flush()
        return template

    def test_list_templates(self, db_session):
        self._seed_template(db_session)
        service = ReportTemplateService(db_session, "growth")

        templates = service.list_templates()
        assert len(templates) >= 1

    def test_list_templates_filters_by_category(self, db_session):
        self._seed_template(db_session)
        service = ReportTemplateService(db_session, "growth")

        templates = service.list_templates(category="marketing")
        sales_templates = [t for t in templates if t.category == "sales"]
        assert len(sales_templates) == 0

    def test_can_use_template_tier_check(self, db_session):
        template = self._seed_template(db_session, min_tier="enterprise")

        growth_service = ReportTemplateService(db_session, "growth")
        assert not growth_service.can_use_template(template)

        enterprise_service = ReportTemplateService(db_session, "enterprise")
        assert enterprise_service.can_use_template(template)

    def test_instantiate_template(self, db_session):
        template = self._seed_template(db_session)
        service = ReportTemplateService(db_session, "growth")

        dashboard = service.instantiate_template(
            template_id=template.id,
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            dashboard_name="From Template",
            available_datasets=["fact_orders_current"],
        )

        assert dashboard.name == "From Template"
        assert dashboard.is_template_derived is True
        assert dashboard.template_id == template.id
        assert len(dashboard.reports) == 1

    def test_instantiate_template_missing_datasets_fails(self, db_session):
        template = self._seed_template(db_session)
        service = ReportTemplateService(db_session, "growth")

        with pytest.raises(TemplateRequirementsError) as exc_info:
            service.instantiate_template(
                template_id=template.id,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                dashboard_name="Missing Data",
                available_datasets=["some_other_dataset"],
            )

        assert "fact_orders_current" in exc_info.value.missing_datasets

    def test_instantiate_template_wrong_tier_fails(self, db_session):
        template = self._seed_template(db_session, min_tier="enterprise")
        service = ReportTemplateService(db_session, "growth")

        with pytest.raises(ValueError, match="requires enterprise"):
            service.instantiate_template(
                template_id=template.id,
                tenant_id=TENANT_ID,
                user_id=USER_ID,
                dashboard_name="Wrong Tier",
            )


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestSchemaValidation:
    """Test Pydantic schema validation catches edge cases."""

    def test_grid_position_overflow(self):
        from src.api.schemas.custom_dashboards import GridPosition

        with pytest.raises(Exception):
            GridPosition(x=10, y=0, w=5, h=3)  # 10 + 5 > 12

    def test_kpi_requires_one_metric(self):
        from src.api.schemas.custom_dashboards import CreateReportRequest, ChartConfig, MetricConfig, GridPosition

        with pytest.raises(Exception):
            CreateReportRequest(
                name="Bad KPI",
                chart_type="kpi",
                dataset_name="fact_orders",
                config_json=ChartConfig(
                    metrics=[
                        MetricConfig(column="a", aggregation="SUM"),
                        MetricConfig(column="b", aggregation="SUM"),
                    ],
                ),
                position_json=GridPosition(x=0, y=0, w=3, h=2),
            )

    def test_invalid_aggregation_rejected(self):
        from src.api.schemas.custom_dashboards import MetricConfig

        with pytest.raises(Exception):
            MetricConfig(column="revenue", aggregation="INVALID")

    def test_valid_chart_types(self):
        from src.api.schemas.custom_dashboards import VALID_CHART_TYPES

        assert "line" in VALID_CHART_TYPES
        assert "bar" in VALID_CHART_TYPES
        assert "kpi" in VALID_CHART_TYPES
        assert "invalid" not in VALID_CHART_TYPES

    def test_share_requires_target(self):
        from src.api.schemas.custom_dashboards import CreateShareRequest

        with pytest.raises(Exception):
            CreateShareRequest(permission="view")
