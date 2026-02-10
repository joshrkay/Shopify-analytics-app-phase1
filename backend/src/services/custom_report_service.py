"""
Custom Report Service - Business logic for chart widgets within dashboards.

Handles adding, updating, removing, and reordering reports on a custom dashboard.
Each mutation creates a dashboard version snapshot and audit entry.

Phase: Custom Reports & Dashboard Builder
"""

import logging
import uuid
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.custom_dashboard import CustomDashboard
from src.models.custom_report import CustomReport, ChartType, CHART_MIN_DIMENSIONS
from src.models.dashboard_audit import DashboardAudit, DashboardAuditAction
from src.services.custom_dashboard_service import (
    CustomDashboardService,
    DashboardNotFoundError,
)
from src.services.dataset_discovery_service import DatasetDiscoveryService

logger = logging.getLogger(__name__)


class ReportNotFoundError(Exception):
    """Report does not exist within the dashboard."""


class ReportNameConflictError(Exception):
    """Report name already exists within the dashboard."""


class DatasetNotFoundError(Exception):
    """Dataset name is not in the set of discoverable datasets."""


class CustomReportService:
    """Service for managing reports within a custom dashboard."""

    def __init__(self, db: Session, tenant_id: str, user_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._dashboard_service = CustomDashboardService(db, tenant_id, user_id)

    def list_reports(self, dashboard_id: str) -> List[CustomReport]:
        """List all reports in a dashboard ordered by sort_order."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        return (
            self.db.query(CustomReport)
            .filter(CustomReport.dashboard_id == dashboard.id)
            .order_by(CustomReport.sort_order)
            .all()
        )

    def get_report(self, dashboard_id: str, report_id: str) -> CustomReport:
        """Get a single report with dashboard access check."""
        self._dashboard_service.get_dashboard(dashboard_id)

        report = self.db.query(CustomReport).filter(
            CustomReport.id == report_id,
            CustomReport.dashboard_id == dashboard_id,
            CustomReport.tenant_id == self.tenant_id,
        ).first()

        if not report:
            raise ReportNotFoundError(f"Report {report_id} not found in dashboard {dashboard_id}")

        return report

    def add_report(
        self,
        dashboard_id: str,
        name: str,
        chart_type: str,
        dataset_name: str,
        config_json: dict,
        position_json: dict,
        description: Optional[str] = None,
    ) -> CustomReport:
        """Add a new report widget to a dashboard."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_dashboard_write_access(dashboard)
        self._validate_position_for_chart_type(chart_type, position_json)
        self._validate_dataset_access(dataset_name)

        # Determine sort order (append to end)
        max_sort = (
            self.db.query(CustomReport.sort_order)
            .filter(CustomReport.dashboard_id == dashboard.id)
            .order_by(CustomReport.sort_order.desc())
            .first()
        )
        next_sort = (max_sort[0] + 1) if max_sort else 0

        report = CustomReport(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            dashboard_id=dashboard.id,
            name=name,
            description=description,
            chart_type=chart_type,
            dataset_name=dataset_name,
            config_json=config_json,
            position_json=position_json,
            sort_order=next_sort,
            created_by=self.user_id,
        )

        try:
            self.db.add(report)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise ReportNameConflictError(
                f"A report named '{name}' already exists in this dashboard"
            )

        # Update dashboard version
        dashboard.version_number += 1
        self._dashboard_service._create_version(dashboard, f"Added chart: {name}")
        self._audit(dashboard.id, DashboardAuditAction.REPORT_ADDED, {
            "report_id": report.id,
            "report_name": name,
            "chart_type": chart_type,
        })
        self.db.commit()

        return report

    def update_report(
        self,
        dashboard_id: str,
        report_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        chart_type: Optional[str] = None,
        config_json: Optional[dict] = None,
        position_json: Optional[dict] = None,
    ) -> CustomReport:
        """Update an existing report's configuration."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_dashboard_write_access(dashboard)

        report = self.get_report(dashboard_id, report_id)

        effective_chart_type = chart_type or report.chart_type
        if position_json:
            self._validate_position_for_chart_type(effective_chart_type, position_json)

        changes = []
        if name is not None:
            report.name = name
            changes.append("name")
        if description is not None:
            report.description = description
            changes.append("description")
        if chart_type is not None:
            report.chart_type = chart_type
            changes.append("chart_type")
        if config_json is not None:
            report.config_json = config_json
            changes.append("config")
        if position_json is not None:
            report.position_json = position_json
            changes.append("position")

        if not changes:
            return report

        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise ReportNameConflictError(
                f"A report named '{name}' already exists in this dashboard"
            )

        dashboard.version_number += 1
        self._dashboard_service._create_version(
            dashboard, f"Updated chart: {report.name}"
        )
        self._audit(dashboard.id, DashboardAuditAction.REPORT_UPDATED, {
            "report_id": report.id,
            "report_name": report.name,
            "changes": changes,
        })
        self.db.commit()

        return report

    def remove_report(self, dashboard_id: str, report_id: str) -> None:
        """Remove a report from a dashboard."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_dashboard_write_access(dashboard)

        report = self.get_report(dashboard_id, report_id)
        report_name = report.name

        self.db.delete(report)
        self.db.flush()

        dashboard.version_number += 1
        self._dashboard_service._create_version(
            dashboard, f"Removed chart: {report_name}"
        )
        self._audit(dashboard.id, DashboardAuditAction.REPORT_REMOVED, {
            "report_id": report_id,
            "report_name": report_name,
        })
        self.db.commit()

    def reorder_reports(self, dashboard_id: str, report_ids: List[str]) -> List[CustomReport]:
        """Reorder reports within a dashboard by setting sort_order."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_dashboard_write_access(dashboard)

        reports = (
            self.db.query(CustomReport)
            .filter(
                CustomReport.dashboard_id == dashboard.id,
                CustomReport.id.in_(report_ids),
            )
            .all()
        )

        report_map = {r.id: r for r in reports}

        for idx, report_id in enumerate(report_ids):
            if report_id in report_map:
                report_map[report_id].sort_order = idx

        dashboard.version_number += 1
        self.db.flush()
        self._dashboard_service._create_version(dashboard, "Reordered charts")
        self._audit(dashboard.id, DashboardAuditAction.REPORTS_REORDERED, {
            "new_order": report_ids,
        })
        self.db.commit()

        return sorted(reports, key=lambda r: r.sort_order)

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _validate_dataset_access(self, dataset_name: str) -> None:
        """Verify the dataset exists in Superset's discoverable datasets."""
        try:
            discovery = DatasetDiscoveryService()
            result = discovery.discover_datasets()
            known_names = {ds.dataset_name for ds in result.datasets}
            if dataset_name not in known_names:
                raise DatasetNotFoundError(
                    f"Dataset '{dataset_name}' is not available. "
                    "Check the dataset name or contact your administrator."
                )
        except DatasetNotFoundError:
            raise
        except Exception as exc:
            # If Superset is unreachable, allow the operation but log a warning.
            # This avoids blocking dashboard creation when Superset is temporarily down.
            logger.warning(
                "custom_report.dataset_validation_skipped",
                extra={"dataset_name": dataset_name, "error": str(exc)},
            )

    def _check_dashboard_write_access(self, dashboard: CustomDashboard) -> None:
        """Verify caller can write to the parent dashboard."""
        access = self._dashboard_service.get_access_level(dashboard)
        if access not in ("owner", "admin", "edit"):
            raise DashboardNotFoundError("You do not have edit access to this dashboard")

    def _validate_position_for_chart_type(self, chart_type: str, position: dict) -> None:
        """Validate minimum grid dimensions for the chart type."""
        try:
            ct = ChartType(chart_type)
        except ValueError:
            return  # Unknown chart type — schema validator catches this

        min_w, min_h = CHART_MIN_DIMENSIONS.get(ct, (1, 1))
        w = position.get("w", 0)
        h = position.get("h", 0)

        if w < min_w or h < min_h:
            raise ValueError(
                f"Chart type '{chart_type}' requires minimum size {min_w}x{min_h}, "
                f"got {w}x{h}"
            )

    def _audit(
        self,
        dashboard_id: str,
        action: DashboardAuditAction,
        details: Optional[dict] = None,
    ) -> None:
        """Create an audit trail entry."""
        entry = DashboardAudit(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            dashboard_id=dashboard_id,
            action=action.value,
            actor_id=self.user_id,
            details_json=details,
        )
        self.db.add(entry)
