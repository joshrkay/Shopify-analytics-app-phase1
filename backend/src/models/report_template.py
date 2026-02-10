"""
Report Template model - System-defined dashboard templates.

Templates are GLOBAL (not tenant-scoped) — they are defined by the system
and available to all tenants based on billing tier. Users instantiate
templates to create pre-configured custom dashboards.

Phase: Custom Reports & Dashboard Builder
"""

import uuid
from enum import Enum as PyEnum

from sqlalchemy import (
    Column, String, Integer, Boolean, Text,
    Index, JSON,
)

from src.db_base import Base
from src.models.base import TimestampMixin


class TemplateCategory(str, PyEnum):
    """Categories for organizing templates in the gallery."""
    SALES = "sales"
    MARKETING = "marketing"
    OPERATIONS = "operations"
    FINANCE = "finance"


class ReportTemplate(Base, TimestampMixin):
    """
    System-defined dashboard template.

    Templates are global (no tenant_id) and define a starter layout
    with pre-configured report widgets. Users instantiate them to
    create editable CustomDashboard copies.

    Templates store:
    - layout_json: Default grid layout for the dashboard
    - reports_json: Array of report configs to create on instantiation
    - required_datasets: Dataset names that must exist for the template to work

    Billing tier gating:
    - min_billing_tier controls which plans can access each template
    - Templates with higher tier requirements appear locked in the gallery
    """

    __tablename__ = "report_templates"

    id = Column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)",
    )

    name = Column(
        String(255),
        nullable=False,
        unique=True,
        comment="Unique template name (e.g., 'Sales Overview')",
    )

    description = Column(
        Text,
        nullable=False,
        comment="What this template provides and who it's for",
    )

    category = Column(
        String(50),
        nullable=False,
        index=True,
        comment="Template category: sales, marketing, operations, finance",
    )

    thumbnail_url = Column(
        String(500),
        nullable=True,
        comment="URL to a preview image of the template",
    )

    layout_json = Column(
        JSON,
        nullable=False,
        comment="Default grid layout for the dashboard",
    )

    reports_json = Column(
        JSON,
        nullable=False,
        comment="Array of report configs: [{name, chart_type, dataset_name, config_json, position_json}]",
    )

    required_datasets = Column(
        JSON,
        nullable=False,
        default=list,
        comment="Dataset names required for this template (validated on instantiation)",
    )

    min_billing_tier = Column(
        String(20),
        nullable=False,
        default="growth",
        comment="Minimum billing tier required: free, growth, pro, enterprise",
    )

    sort_order = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Display ordering in the template gallery",
    )

    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether template is visible in the gallery. False hides it but existing dashboards remain.",
    )

    # Indexes
    __table_args__ = (
        Index(
            "idx_report_templates_category_active",
            "category", "is_active",
        ),
        Index(
            "idx_report_templates_tier_active",
            "min_billing_tier", "is_active",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ReportTemplate(id={self.id}, name={self.name!r}, "
            f"category={self.category}, min_billing_tier={self.min_billing_tier})>"
        )
