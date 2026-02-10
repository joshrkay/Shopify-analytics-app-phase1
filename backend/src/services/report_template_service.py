"""
Report Template Service - Business logic for dashboard templates.

Handles listing templates filtered by billing tier and instantiating
templates into user-owned custom dashboards.

Key edge cases:
- Template instantiation validates required datasets exist
- Partial instantiation failure rolls back entire transaction
- Deactivated templates remain functional for existing dashboards

Phase: Custom Reports & Dashboard Builder
"""

import logging
import uuid
from typing import Optional, List

from sqlalchemy.orm import Session

from src.models.report_template import ReportTemplate
from src.models.custom_dashboard import CustomDashboard, DashboardStatus
from src.models.custom_report import CustomReport
from src.models.dashboard_version import DashboardVersion
from src.models.dashboard_audit import DashboardAudit, DashboardAuditAction

logger = logging.getLogger(__name__)

# Billing tier ordering for comparison
_TIER_ORDER = {"free": 0, "growth": 1, "pro": 2, "enterprise": 3}


class TemplateNotFoundError(Exception):
    """Template does not exist or is not active."""


class TemplateRequirementsError(Exception):
    """Template's required datasets are not available."""

    def __init__(self, missing_datasets: List[str]):
        self.missing_datasets = missing_datasets
        names = ", ".join(missing_datasets)
        super().__init__(f"Missing required datasets: {names}")


class ReportTemplateService:
    """Service for report template operations."""

    def __init__(self, db: Session, billing_tier: str = "free"):
        self.db = db
        self.billing_tier = billing_tier.lower()

    def list_templates(
        self,
        category: Optional[str] = None,
    ) -> List[ReportTemplate]:
        """
        List active templates accessible at the caller's billing tier.

        Higher-tier templates are included but marked with their
        min_billing_tier so the frontend can show them as locked.
        """
        query = self.db.query(ReportTemplate).filter(
            ReportTemplate.is_active.is_(True),
        )

        if category:
            query = query.filter(ReportTemplate.category == category)

        return query.order_by(ReportTemplate.sort_order).all()

    def get_template(self, template_id: str) -> ReportTemplate:
        """Get a single template by ID."""
        template = self.db.query(ReportTemplate).filter(
            ReportTemplate.id == template_id,
            ReportTemplate.is_active.is_(True),
        ).first()

        if not template:
            raise TemplateNotFoundError(f"Template {template_id} not found or inactive")

        return template

    def can_use_template(self, template: ReportTemplate) -> bool:
        """Check if the caller's billing tier meets the template minimum."""
        caller_rank = _TIER_ORDER.get(self.billing_tier, 0)
        required_rank = _TIER_ORDER.get(template.min_billing_tier, 0)
        return caller_rank >= required_rank

    def instantiate_template(
        self,
        template_id: str,
        tenant_id: str,
        user_id: str,
        dashboard_name: str,
        available_datasets: Optional[List[str]] = None,
    ) -> CustomDashboard:
        """
        Create a dashboard from a template.

        Validates billing tier and required datasets before creating.
        Entire operation is atomic — rolls back on any failure.

        Args:
            template_id: Template to instantiate
            tenant_id: Target tenant
            user_id: Creating user
            dashboard_name: Name for the new dashboard
            available_datasets: Datasets available to this tenant (for validation)

        Raises:
            TemplateNotFoundError: Template doesn't exist
            TemplateRequirementsError: Missing required datasets
            ValueError: Billing tier too low
        """
        template = self.get_template(template_id)

        if not self.can_use_template(template):
            raise ValueError(
                f"Template '{template.name}' requires {template.min_billing_tier} plan"
            )

        # Validate required datasets
        if available_datasets is not None and template.required_datasets:
            missing = [
                ds for ds in template.required_datasets
                if ds not in available_datasets
            ]
            if missing:
                raise TemplateRequirementsError(missing)

        # Create dashboard
        dashboard = CustomDashboard(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            name=dashboard_name,
            description=template.description,
            status=DashboardStatus.DRAFT.value,
            layout_json=template.layout_json,
            template_id=template.id,
            is_template_derived=True,
            version_number=1,
            created_by=user_id,
        )
        self.db.add(dashboard)
        self.db.flush()

        # Create reports from template config
        for idx, report_config in enumerate(template.reports_json):
            report = CustomReport(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                dashboard_id=dashboard.id,
                name=report_config["name"],
                description=report_config.get("description"),
                chart_type=report_config["chart_type"],
                dataset_name=report_config["dataset_name"],
                config_json=report_config["config_json"],
                position_json=report_config["position_json"],
                sort_order=idx,
                created_by=user_id,
            )
            self.db.add(report)

        self.db.flush()

        # Create initial version
        version = DashboardVersion(
            id=str(uuid.uuid4()),
            dashboard_id=dashboard.id,
            version_number=1,
            snapshot_json={
                "dashboard": {
                    "name": dashboard.name,
                    "description": dashboard.description,
                    "layout_json": dashboard.layout_json,
                    "filters_json": dashboard.filters_json,
                },
                "reports": template.reports_json,
            },
            change_summary=f"Created from template: {template.name}",
            created_by=user_id,
        )
        self.db.add(version)

        # Audit
        audit = DashboardAudit(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            dashboard_id=dashboard.id,
            action=DashboardAuditAction.CREATED.value,
            actor_id=user_id,
            details_json={
                "template_id": template.id,
                "template_name": template.name,
            },
        )
        self.db.add(audit)

        self.db.commit()
        return dashboard
