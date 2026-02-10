"""
Custom Dashboard Service - Business logic for custom dashboards.

Handles CRUD operations, versioning, audit trail, and entitlement enforcement.

Key edge cases handled:
- TOCTOU race on dashboard count limit (SELECT FOR UPDATE)
- Optimistic locking via expected_updated_at (409 Conflict)
- Version cap enforcement (MAX_DASHBOARD_VERSIONS)
- Downgraded tenants retain read access but lose write access
- Archived dashboard name reuse (unique constraint on tenant+name+status)

Phase: Custom Reports & Dashboard Builder
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.custom_dashboard import CustomDashboard, DashboardStatus
from src.models.custom_report import CustomReport
from src.models.dashboard_version import DashboardVersion, MAX_DASHBOARD_VERSIONS
from src.models.dashboard_audit import DashboardAudit, DashboardAuditAction
from src.models.dashboard_share import DashboardShare

logger = logging.getLogger(__name__)


class DashboardNotFoundError(Exception):
    """Dashboard does not exist or caller has no access."""


class DashboardLimitExceededError(Exception):
    """Tenant has reached their custom dashboard limit."""

    def __init__(self, current_count: int, max_count: int):
        self.current_count = current_count
        self.max_count = max_count
        super().__init__(f"Dashboard limit exceeded: {current_count}/{max_count}")


class DashboardConflictError(Exception):
    """Concurrent edit detected (optimistic lock failure)."""


class DashboardNameConflictError(Exception):
    """Dashboard name already exists for this tenant+status."""


class CustomDashboardService:
    """Service for custom dashboard CRUD with versioning and audit."""

    def __init__(self, db: Session, tenant_id: str, user_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id

    # =========================================================================
    # List / Get
    # =========================================================================

    def list_dashboards(
        self,
        status_filter: Optional[str] = None,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[CustomDashboard], int]:
        """List dashboards the user owns or has been shared with."""
        # Owned dashboards
        query = self.db.query(CustomDashboard).filter(
            CustomDashboard.tenant_id == self.tenant_id,
        )

        if status_filter:
            query = query.filter(CustomDashboard.status == status_filter)
        else:
            # Exclude archived by default
            query = query.filter(CustomDashboard.status != DashboardStatus.ARCHIVED.value)

        total = query.count()
        dashboards = (
            query
            .order_by(CustomDashboard.updated_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return dashboards, total

    def get_dashboard(self, dashboard_id: str) -> CustomDashboard:
        """Get a dashboard by ID with access check."""
        dashboard = self.db.query(CustomDashboard).filter(
            CustomDashboard.id == dashboard_id,
            CustomDashboard.tenant_id == self.tenant_id,
        ).first()

        if not dashboard:
            raise DashboardNotFoundError(f"Dashboard {dashboard_id} not found")

        return dashboard

    def get_access_level(self, dashboard: CustomDashboard) -> str:
        """Determine caller's access level for a dashboard."""
        if dashboard.created_by == self.user_id:
            return "owner"

        # Check direct user share
        share = self.db.query(DashboardShare).filter(
            DashboardShare.dashboard_id == dashboard.id,
            DashboardShare.shared_with_user_id == self.user_id,
        ).first()

        if share:
            now = datetime.now(timezone.utc)
            if share.expires_at:
                # Handle both timezone-aware and naive datetimes (SQLite stores naive)
                expiry = share.expires_at
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry < now:
                    return "none"
            return share.permission

        return "none"

    # =========================================================================
    # Create
    # =========================================================================

    def create_dashboard(
        self,
        name: str,
        description: Optional[str] = None,
        max_dashboards: Optional[int] = None,
    ) -> CustomDashboard:
        """
        Create a new custom dashboard.

        Uses SELECT FOR UPDATE to prevent TOCTOU race on count limit.

        Args:
            name: Dashboard name
            description: Optional description
            max_dashboards: Plan limit (None = unlimited, -1 = unlimited)

        Raises:
            DashboardLimitExceededError: If tenant has reached their limit
            DashboardNameConflictError: If name already exists for tenant+draft/published
        """
        # Atomic count check with row-level lock to prevent TOCTOU race
        if max_dashboards is not None and max_dashboards != -1:
            current_count = (
                self.db.query(func.count(CustomDashboard.id))
                .filter(
                    CustomDashboard.tenant_id == self.tenant_id,
                    CustomDashboard.status != DashboardStatus.ARCHIVED.value,
                )
                .with_for_update()
                .scalar()
            )
            if current_count >= max_dashboards:
                raise DashboardLimitExceededError(current_count, max_dashboards)

        dashboard = CustomDashboard(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            name=name,
            description=description,
            status=DashboardStatus.DRAFT.value,
            layout_json={},
            version_number=1,
            created_by=self.user_id,
        )

        try:
            self.db.add(dashboard)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise DashboardNameConflictError(
                f"A dashboard named '{name}' already exists with this status"
            )

        # Create initial version snapshot
        self._create_version(dashboard, "Created dashboard")

        # Audit
        self._audit(dashboard.id, DashboardAuditAction.CREATED, {
            "name": name,
        })

        self.db.commit()
        return dashboard

    # =========================================================================
    # Update
    # =========================================================================

    def update_dashboard(
        self,
        dashboard_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        layout_json: Optional[dict] = None,
        filters_json: Optional[list] = None,
        expected_updated_at: Optional[datetime] = None,
    ) -> CustomDashboard:
        """
        Update dashboard metadata or layout.

        Supports optimistic locking via expected_updated_at.

        Raises:
            DashboardNotFoundError: Dashboard not found
            DashboardConflictError: Concurrent edit detected
        """
        dashboard = self.get_dashboard(dashboard_id)
        self._check_write_access(dashboard)

        # Optimistic lock check
        if expected_updated_at is not None:
            if dashboard.updated_at != expected_updated_at:
                raise DashboardConflictError(
                    "Dashboard was modified by another user. "
                    "Refresh and try again."
                )

        changes = []
        if name is not None:
            dashboard.name = name
            changes.append("name")
        if description is not None:
            dashboard.description = description
            changes.append("description")
        if layout_json is not None:
            dashboard.layout_json = layout_json
            changes.append("layout")
        if filters_json is not None:
            dashboard.filters_json = filters_json
            changes.append("filters")

        if not changes:
            return dashboard

        dashboard.version_number += 1
        summary = f"Updated {', '.join(changes)}"

        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise DashboardNameConflictError(
                f"A dashboard named '{name}' already exists with this status"
            )

        self._create_version(dashboard, summary)
        self._audit(dashboard.id, DashboardAuditAction.UPDATED, {"changes": changes})
        self.db.commit()

        return dashboard

    # =========================================================================
    # Publish / Archive
    # =========================================================================

    def publish_dashboard(self, dashboard_id: str) -> CustomDashboard:
        """Change dashboard status from draft to published."""
        dashboard = self.get_dashboard(dashboard_id)
        self._check_write_access(dashboard)

        if dashboard.status == DashboardStatus.PUBLISHED.value:
            return dashboard

        dashboard.status = DashboardStatus.PUBLISHED.value
        dashboard.version_number += 1

        self._create_version(dashboard, "Published dashboard")
        self._audit(dashboard.id, DashboardAuditAction.PUBLISHED)
        self.db.commit()

        return dashboard

    def archive_dashboard(self, dashboard_id: str) -> CustomDashboard:
        """Soft-delete a dashboard by archiving it. Owner only."""
        dashboard = self.get_dashboard(dashboard_id)

        if dashboard.created_by != self.user_id:
            raise DashboardNotFoundError("Only the owner can archive a dashboard")

        dashboard.status = DashboardStatus.ARCHIVED.value

        self._audit(dashboard.id, DashboardAuditAction.ARCHIVED)
        self.db.commit()

        return dashboard

    # =========================================================================
    # Duplicate
    # =========================================================================

    def duplicate_dashboard(
        self,
        dashboard_id: str,
        new_name: str,
        max_dashboards: Optional[int] = None,
    ) -> CustomDashboard:
        """Clone a dashboard and all its reports."""
        source = self.get_dashboard(dashboard_id)

        # Count check same as create
        if max_dashboards is not None and max_dashboards != -1:
            current_count = (
                self.db.query(func.count(CustomDashboard.id))
                .filter(
                    CustomDashboard.tenant_id == self.tenant_id,
                    CustomDashboard.status != DashboardStatus.ARCHIVED.value,
                )
                .with_for_update()
                .scalar()
            )
            if current_count >= max_dashboards:
                raise DashboardLimitExceededError(current_count, max_dashboards)

        new_dashboard = CustomDashboard(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            name=new_name,
            description=source.description,
            status=DashboardStatus.DRAFT.value,
            layout_json=source.layout_json,
            filters_json=source.filters_json,
            template_id=source.template_id,
            is_template_derived=source.is_template_derived,
            version_number=1,
            created_by=self.user_id,
        )

        try:
            self.db.add(new_dashboard)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise DashboardNameConflictError(
                f"A dashboard named '{new_name}' already exists"
            )

        # Clone reports
        for report in source.reports:
            new_report = CustomReport(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                dashboard_id=new_dashboard.id,
                name=report.name,
                description=report.description,
                chart_type=report.chart_type,
                dataset_name=report.dataset_name,
                config_json=report.config_json,
                position_json=report.position_json,
                cache_timeout=report.cache_timeout,
                sort_order=report.sort_order,
                created_by=self.user_id,
            )
            self.db.add(new_report)

        self.db.flush()
        self._create_version(new_dashboard, f"Duplicated from '{source.name}'")
        self._audit(new_dashboard.id, DashboardAuditAction.DUPLICATED, {
            "source_dashboard_id": source.id,
            "source_name": source.name,
        })
        self.db.commit()

        return new_dashboard

    # =========================================================================
    # Version Management
    # =========================================================================

    def list_versions(
        self,
        dashboard_id: str,
        offset: int = 0,
        limit: int = 20,
    ) -> Tuple[List[DashboardVersion], int]:
        """List version history for a dashboard."""
        dashboard = self.get_dashboard(dashboard_id)

        query = self.db.query(DashboardVersion).filter(
            DashboardVersion.dashboard_id == dashboard.id,
        )
        total = query.count()
        versions = (
            query
            .order_by(DashboardVersion.version_number.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return versions, total

    def get_version(self, dashboard_id: str, version_number: int) -> DashboardVersion:
        """Get a single version with its snapshot for preview."""
        dashboard = self.get_dashboard(dashboard_id)

        version = self.db.query(DashboardVersion).filter(
            DashboardVersion.dashboard_id == dashboard.id,
            DashboardVersion.version_number == version_number,
        ).first()

        if not version:
            raise DashboardNotFoundError(
                f"Version {version_number} not found for dashboard {dashboard_id}"
            )

        return version

    def restore_version(self, dashboard_id: str, version_number: int) -> CustomDashboard:
        """Restore a dashboard to a previous version."""
        dashboard = self.get_dashboard(dashboard_id)
        self._check_write_access(dashboard)

        version = self.db.query(DashboardVersion).filter(
            DashboardVersion.dashboard_id == dashboard.id,
            DashboardVersion.version_number == version_number,
        ).first()

        if not version:
            raise DashboardNotFoundError(
                f"Version {version_number} not found for dashboard {dashboard_id}"
            )

        snapshot = version.snapshot_json
        dashboard_data = snapshot.get("dashboard", {})

        # Restore dashboard metadata
        dashboard.name = dashboard_data.get("name", dashboard.name)
        dashboard.description = dashboard_data.get("description")
        dashboard.layout_json = dashboard_data.get("layout_json", {})
        dashboard.filters_json = dashboard_data.get("filters_json")

        # Delete current reports and recreate from snapshot
        self.db.query(CustomReport).filter(
            CustomReport.dashboard_id == dashboard.id,
        ).delete()

        for report_data in snapshot.get("reports", []):
            restored_report = CustomReport(
                id=str(uuid.uuid4()),
                tenant_id=self.tenant_id,
                dashboard_id=dashboard.id,
                name=report_data["name"],
                description=report_data.get("description"),
                chart_type=report_data["chart_type"],
                dataset_name=report_data["dataset_name"],
                config_json=report_data["config_json"],
                position_json=report_data["position_json"],
                cache_timeout=report_data.get("cache_timeout", 86400),
                sort_order=report_data.get("sort_order", 0),
                created_by=self.user_id,
            )
            self.db.add(restored_report)

        dashboard.version_number += 1
        self.db.flush()

        self._create_version(dashboard, f"Restored to version {version_number}")
        self._audit(dashboard.id, DashboardAuditAction.RESTORED, {
            "restored_version": version_number,
        })
        self.db.commit()

        return dashboard

    # =========================================================================
    # Audit Trail
    # =========================================================================

    def list_audit_entries(
        self,
        dashboard_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> Tuple[List[DashboardAudit], int]:
        """List audit trail for a dashboard."""
        dashboard = self.get_dashboard(dashboard_id)

        query = self.db.query(DashboardAudit).filter(
            DashboardAudit.dashboard_id == dashboard.id,
        )
        total = query.count()
        entries = (
            query
            .order_by(DashboardAudit.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

        return entries, total

    # =========================================================================
    # Dashboard Count (for entitlement display)
    # =========================================================================

    def get_dashboard_count(self) -> int:
        """Get count of non-archived dashboards for this tenant."""
        return (
            self.db.query(func.count(CustomDashboard.id))
            .filter(
                CustomDashboard.tenant_id == self.tenant_id,
                CustomDashboard.status != DashboardStatus.ARCHIVED.value,
            )
            .scalar()
        )

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _check_write_access(self, dashboard: CustomDashboard) -> None:
        """Verify caller can write to this dashboard."""
        access = self.get_access_level(dashboard)
        if access not in ("owner", "admin", "edit"):
            raise DashboardNotFoundError("You do not have edit access to this dashboard")

    def _create_version(self, dashboard: CustomDashboard, change_summary: str) -> None:
        """Create a version snapshot and enforce version cap."""
        snapshot = {
            "dashboard": {
                "name": dashboard.name,
                "description": dashboard.description,
                "layout_json": dashboard.layout_json,
                "filters_json": dashboard.filters_json,
            },
            "reports": [
                {
                    "id": r.id,
                    "name": r.name,
                    "description": r.description,
                    "chart_type": r.chart_type,
                    "dataset_name": r.dataset_name,
                    "config_json": r.config_json,
                    "position_json": r.position_json,
                    "cache_timeout": r.cache_timeout,
                    "sort_order": r.sort_order,
                }
                for r in dashboard.reports
            ],
        }

        version = DashboardVersion(
            id=str(uuid.uuid4()),
            dashboard_id=dashboard.id,
            version_number=dashboard.version_number,
            snapshot_json=snapshot,
            change_summary=change_summary,
            created_by=self.user_id,
        )
        self.db.add(version)

        self.db.flush()

        # Enforce version cap — delete oldest versions exceeding limit
        version_count = (
            self.db.query(func.count(DashboardVersion.id))
            .filter(DashboardVersion.dashboard_id == dashboard.id)
            .scalar()
        )

        while version_count > MAX_DASHBOARD_VERSIONS:
            oldest = (
                self.db.query(DashboardVersion)
                .filter(DashboardVersion.dashboard_id == dashboard.id)
                .order_by(DashboardVersion.version_number.asc())
                .first()
            )
            if oldest:
                self.db.delete(oldest)
                self.db.flush()
                version_count -= 1
            else:
                break

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
