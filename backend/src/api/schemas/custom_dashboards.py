"""
Pydantic schemas for Custom Dashboards API.

Request and response models with strict validation for layout JSON,
chart configs, and grid positions. Enforces constraints documented
in the edge case analysis.

Phase: Custom Reports & Dashboard Builder
"""

from typing import Optional, List, Any
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Grid Position Validation
# =============================================================================

class GridPosition(BaseModel):
    """Grid position for a report widget within the 12-column layout."""

    x: int = Field(..., ge=0, le=11, description="Column start (0-11)")
    y: int = Field(..., ge=0, description="Row start (0+)")
    w: int = Field(..., ge=1, le=12, description="Width in grid columns (1-12)")
    h: int = Field(..., ge=1, le=20, description="Height in grid rows (1-20)")

    @field_validator("w")
    @classmethod
    def width_must_fit_grid(cls, v: int, info) -> int:
        """Ensure widget doesn't extend beyond 12-column grid."""
        x = info.data.get("x", 0)
        if x + v > 12:
            raise ValueError(f"Widget extends beyond grid: x({x}) + w({v}) > 12")
        return v


# =============================================================================
# Chart Configuration Validation
# =============================================================================

class MetricConfig(BaseModel):
    """Configuration for a single metric in a chart."""

    column: str = Field(..., min_length=1, max_length=255, description="Column name from dataset")
    aggregation: str = Field(..., description="Aggregation function: SUM, AVG, COUNT, MIN, MAX")
    label: Optional[str] = Field(None, max_length=255, description="Display label override")
    format: Optional[str] = Field(None, max_length=50, description="Number format (e.g., ',.2f', '$,.0f')")

    @field_validator("aggregation")
    @classmethod
    def valid_aggregation(cls, v: str) -> str:
        allowed = {"SUM", "AVG", "COUNT", "MIN", "MAX"}
        if v.upper() not in allowed:
            raise ValueError(f"Invalid aggregation '{v}'. Must be one of: {allowed}")
        return v.upper()


class ChartFilter(BaseModel):
    """A single filter condition for a chart."""

    column: str = Field(..., min_length=1, max_length=255)
    operator: str = Field(..., description="Filter operator")
    value: Any = Field(..., description="Filter value")

    @field_validator("operator")
    @classmethod
    def valid_operator(cls, v: str) -> str:
        allowed = {"=", "!=", ">", "<", ">=", "<=", "IN", "NOT IN", "LIKE"}
        if v.upper() not in allowed:
            raise ValueError(f"Invalid operator '{v}'. Must be one of: {allowed}")
        return v.upper()


class DisplayConfig(BaseModel):
    """Display settings for a chart."""

    color_scheme: Optional[str] = Field("default", max_length=50)
    show_legend: bool = Field(True)
    legend_position: Optional[str] = Field("bottom")
    axis_label_x: Optional[str] = Field(None, max_length=255)
    axis_label_y: Optional[str] = Field(None, max_length=255)


class ChartConfig(BaseModel):
    """Full chart configuration for a custom report."""

    metrics: List[MetricConfig] = Field(..., min_length=1, max_length=20)
    dimensions: List[str] = Field(default_factory=list, max_length=5)
    time_range: str = Field("Last 30 days", max_length=100)
    time_grain: str = Field("P1D", description="ISO 8601 duration: P1D, P1W, P1M")
    filters: List[ChartFilter] = Field(default_factory=list, max_length=20)
    display: DisplayConfig = Field(default_factory=DisplayConfig)

    @field_validator("time_grain")
    @classmethod
    def valid_time_grain(cls, v: str) -> str:
        allowed = {"P1D", "P1W", "P1M", "P3M", "P1Y"}
        if v not in allowed:
            raise ValueError(f"Invalid time_grain '{v}'. Must be one of: {allowed}")
        return v


# =============================================================================
# Dashboard Filter Schemas
# =============================================================================

class DashboardFilter(BaseModel):
    """Dashboard-level filter definition."""

    column: str = Field(..., min_length=1, max_length=255)
    filter_type: str = Field(..., description="date_range, select, multi_select")
    default_value: Optional[Any] = None
    dataset_names: List[str] = Field(default_factory=list, description="Datasets this filter applies to")


# =============================================================================
# Request Models
# =============================================================================

class CreateDashboardRequest(BaseModel):
    """Request to create a new custom dashboard."""

    name: str = Field(..., min_length=1, max_length=255, description="Dashboard name")
    description: Optional[str] = Field(None, max_length=2000)
    template_id: Optional[str] = Field(None, max_length=36, description="Create from template")

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Dashboard name cannot be blank")
        return v.strip()


class UpdateDashboardRequest(BaseModel):
    """Request to update dashboard metadata or layout."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    layout_json: Optional[dict] = None
    filters_json: Optional[List[DashboardFilter]] = None
    expected_updated_at: Optional[datetime] = Field(
        None,
        description="Optimistic lock: reject if dashboard.updated_at != this value (409 Conflict)",
    )

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Dashboard name cannot be blank")
        return v.strip() if v else v


class DuplicateDashboardRequest(BaseModel):
    """Request to duplicate an existing dashboard."""

    new_name: str = Field(..., min_length=1, max_length=255)


# =============================================================================
# Report Request Models
# =============================================================================

VALID_CHART_TYPES = {"line", "bar", "area", "pie", "kpi", "table"}


class CreateReportRequest(BaseModel):
    """Request to add a new report/chart to a dashboard."""

    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    chart_type: str = Field(..., description="Visualization type")
    dataset_name: str = Field(..., min_length=1, max_length=255)
    config_json: ChartConfig
    position_json: GridPosition

    @field_validator("chart_type")
    @classmethod
    def valid_chart_type(cls, v: str) -> str:
        if v not in VALID_CHART_TYPES:
            raise ValueError(f"Invalid chart_type '{v}'. Must be one of: {VALID_CHART_TYPES}")
        return v

    @field_validator("config_json")
    @classmethod
    def validate_metrics_for_chart_type(cls, v: ChartConfig, info) -> ChartConfig:
        chart_type = info.data.get("chart_type")
        if chart_type == "kpi" and len(v.metrics) != 1:
            raise ValueError("KPI chart requires exactly 1 metric")
        if chart_type == "pie":
            if len(v.metrics) != 1:
                raise ValueError("Pie chart requires exactly 1 metric")
            if len(v.dimensions) != 1:
                raise ValueError("Pie chart requires exactly 1 dimension")
        return v


class UpdateReportRequest(BaseModel):
    """Request to update an existing report's config."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, max_length=2000)
    chart_type: Optional[str] = None
    config_json: Optional[ChartConfig] = None
    position_json: Optional[GridPosition] = None

    @field_validator("chart_type")
    @classmethod
    def valid_chart_type(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_CHART_TYPES:
            raise ValueError(f"Invalid chart_type '{v}'. Must be one of: {VALID_CHART_TYPES}")
        return v


class ReorderReportsRequest(BaseModel):
    """Request to reorder reports within a dashboard."""

    report_ids: List[str] = Field(..., min_length=1, description="Ordered list of report IDs")


# =============================================================================
# Share Request Models
# =============================================================================

VALID_SHARE_PERMISSIONS = {"view", "edit", "admin"}
VALID_SHARE_ROLES = {"merchant_admin", "merchant_viewer", "agency_admin", "agency_viewer"}


class CreateShareRequest(BaseModel):
    """Request to share a dashboard with a user or role."""

    shared_with_user_id: Optional[str] = Field(None, max_length=255)
    shared_with_role: Optional[str] = Field(None, max_length=50)
    permission: str = Field("view", description="Permission level: view, edit, admin")
    expires_at: Optional[datetime] = None

    @field_validator("permission")
    @classmethod
    def valid_permission(cls, v: str) -> str:
        if v not in VALID_SHARE_PERMISSIONS:
            raise ValueError(f"Invalid permission '{v}'. Must be one of: {VALID_SHARE_PERMISSIONS}")
        return v

    @field_validator("shared_with_role")
    @classmethod
    def valid_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_SHARE_ROLES:
            raise ValueError(f"Invalid role '{v}'. Must be one of: {VALID_SHARE_ROLES}")
        return v

    def model_post_init(self, __context: Any) -> None:
        if not self.shared_with_user_id and not self.shared_with_role:
            raise ValueError("Either shared_with_user_id or shared_with_role must be provided")
        if self.shared_with_user_id and self.shared_with_role:
            raise ValueError("Provide shared_with_user_id or shared_with_role, not both")


class UpdateShareRequest(BaseModel):
    """Request to update a share's permission or expiry."""

    permission: Optional[str] = None
    expires_at: Optional[datetime] = None

    @field_validator("permission")
    @classmethod
    def valid_permission(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in VALID_SHARE_PERMISSIONS:
            raise ValueError(f"Invalid permission '{v}'. Must be one of: {VALID_SHARE_PERMISSIONS}")
        return v


# =============================================================================
# Response Models
# =============================================================================

class ReportResponse(BaseModel):
    """Response model for a single custom report."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    name: str
    description: Optional[str] = None
    chart_type: str
    dataset_name: str
    config_json: dict
    position_json: dict
    sort_order: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    warnings: List[str] = Field(default_factory=list, description="Validation warnings (e.g., missing columns)")


class DashboardResponse(BaseModel):
    """Response model for a single custom dashboard."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: Optional[str] = None
    status: str
    layout_json: dict
    filters_json: Optional[list] = None
    template_id: Optional[str] = None
    is_template_derived: bool
    version_number: int
    reports: List[ReportResponse] = Field(default_factory=list)
    access_level: str = Field("owner", description="Caller's access level: owner, admin, edit, view")
    created_by: str
    created_at: datetime
    updated_at: datetime


class DashboardListResponse(BaseModel):
    """Paginated response for listing dashboards."""

    dashboards: List[DashboardResponse]
    total: int
    offset: int
    limit: int
    has_more: bool


class DashboardVersionResponse(BaseModel):
    """Response model for a dashboard version."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    version_number: int
    change_summary: str
    created_by: str
    created_at: datetime


class DashboardVersionDetailResponse(DashboardVersionResponse):
    """Response model for a single version with its full snapshot."""

    snapshot_json: dict


class VersionListResponse(BaseModel):
    """Paginated response for listing versions."""

    versions: List[DashboardVersionResponse]
    total: int


class ShareResponse(BaseModel):
    """Response model for a dashboard share."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    shared_with_user_id: Optional[str] = None
    shared_with_role: Optional[str] = None
    permission: str
    granted_by: str
    expires_at: Optional[datetime] = None
    is_expired: bool = False
    created_at: datetime
    updated_at: datetime


class ShareListResponse(BaseModel):
    """Response for listing shares."""

    shares: List[ShareResponse]
    total: int


class AuditEntryResponse(BaseModel):
    """Response model for a dashboard audit entry."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    dashboard_id: str
    action: str
    actor_id: str
    details_json: Optional[dict] = None
    created_at: datetime


class AuditListResponse(BaseModel):
    """Response for listing audit entries."""

    entries: List[AuditEntryResponse]
    total: int


class DashboardCountResponse(BaseModel):
    """Response with dashboard count vs limit for entitlement display."""

    current_count: int
    max_count: Optional[int] = Field(None, description="None means unlimited")
    can_create: bool


# =============================================================================
# Template Response Models
# =============================================================================

class TemplateResponse(BaseModel):
    """Response model for a report template."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    category: str
    thumbnail_url: Optional[str] = None
    layout_json: dict
    reports_json: list
    required_datasets: list
    min_billing_tier: str
    sort_order: int
    is_active: bool


class TemplateListResponse(BaseModel):
    """Response for listing templates."""

    templates: List[TemplateResponse]
    total: int


# =============================================================================
# Dataset Response Models
# =============================================================================

class DatasetColumnResponse(BaseModel):
    """Response for a single dataset column."""

    name: str
    type: str = Field(..., description="Data type: numeric, string, datetime, boolean")
    description: Optional[str] = None
    is_metric: bool
    is_dimension: bool


class DatasetResponse(BaseModel):
    """Response for a dataset's metadata."""

    name: str
    description: Optional[str] = None
    schema_name: str
    columns: List[DatasetColumnResponse]


class DatasetListResponse(BaseModel):
    """Response for listing available datasets."""

    datasets: List[DatasetResponse]
    total: int
