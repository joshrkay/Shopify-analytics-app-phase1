"""
Datasets API routes.

Provides endpoints for dataset discovery and chart preview:
- List available datasets with column metadata
- Get columns for a specific dataset
- Validate report config columns against current schema
- Execute chart preview queries with caching

SECURITY: All routes require valid tenant context from JWT.
Requires CUSTOM_REPORTS entitlement.

Phase 2A - Dataset Discovery API
Phase 2B - Chart Preview Backend
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel, Field

from src.platform.tenant_context import get_tenant_context
from src.api.dependencies.entitlements import check_custom_reports_entitlement
from src.services.dataset_discovery_service import (
    DatasetDiscoveryService,
    ColumnMetadata,
    DatasetInfo,
)
from src.services.chart_query_service import (
    ChartConfig,
    ChartQueryService,
    ChartPreviewResult,
    validate_viz_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


# =============================================================================
# Response Models
# =============================================================================


class ColumnMetadataResponse(BaseModel):
    """Column metadata for chart builder filtering."""

    column_name: str = Field(..., description="Column name in the dataset")
    data_type: str = Field(..., description="SQL data type")
    description: str = Field("", description="Human-readable column description")
    is_metric: bool = Field(..., description="True if column can be used as a metric (SUM/AVG/etc)")
    is_dimension: bool = Field(..., description="True if column can be used as a dimension (GROUP BY)")
    is_temporal: bool = Field(..., description="True if column is a date/time type for time axes")


class DatasetResponse(BaseModel):
    """Response model for a single dataset."""

    dataset_name: str = Field(..., description="Table name in the warehouse")
    dataset_id: int = Field(..., description="Superset dataset ID")
    schema_name: str = Field(..., description="Database schema", alias="schema")
    description: str = Field("", description="Dataset description")
    columns: list[ColumnMetadataResponse] = Field(
        default_factory=list, description="Column metadata"
    )

    class Config:
        populate_by_name = True


class DatasetListResponse(BaseModel):
    """Response model for dataset list."""

    datasets: list[DatasetResponse] = Field(..., description="Available datasets")
    total: int = Field(..., description="Total dataset count")
    stale: bool = Field(False, description="True if data is from stale cache")
    cached_at: Optional[str] = Field(None, description="ISO timestamp when data was cached")


class ConfigWarningResponse(BaseModel):
    """Warning for a column referenced in config that no longer exists."""

    column_name: str = Field(..., description="Missing column name")
    dataset_name: str = Field(..., description="Dataset the column was expected in")
    message: str = Field(..., description="Human-readable warning message")


class ValidateConfigRequest(BaseModel):
    """Request to validate report config columns."""

    dataset_name: str = Field(..., description="Dataset name to validate against")
    referenced_columns: list[str] = Field(
        ..., description="Column names referenced in the report config"
    )


class ValidateConfigResponse(BaseModel):
    """Response with validation warnings."""

    valid: bool = Field(..., description="True if all columns exist")
    warnings: list[ConfigWarningResponse] = Field(
        default_factory=list, description="Warnings for missing columns"
    )


class ChartPreviewRequest(BaseModel):
    """Request to execute a chart preview query."""

    dataset_name: str = Field(..., description="Dataset to query")
    metrics: list[dict[str, Any]] = Field(..., description="Metrics to compute")
    dimensions: list[str] = Field(default_factory=list, description="GROUP BY dimensions")
    filters: list[dict[str, Any]] = Field(default_factory=list, description="Adhoc filters")
    time_range: str = Field("Last 30 days", description="Time range expression")
    time_column: Optional[str] = Field(None, description="Temporal column for time axis")
    time_grain: str = Field("P1D", description="Time grain (P1D, P1W, P1M, etc.)")
    viz_type: str = Field("line", description="Abstract chart type: line, bar, pie, table, etc.")


class ChartPreviewResponse(BaseModel):
    """Response from chart preview query."""

    data: list[dict[str, Any]] = Field(default_factory=list, description="Query result rows")
    columns: list[str] = Field(default_factory=list, description="Column names in result")
    row_count: int = Field(0, description="Number of rows returned")
    truncated: bool = Field(False, description="True if GROUP BY was truncated to max cardinality")
    message: Optional[str] = Field(None, description="Info or error message")
    query_duration_ms: Optional[float] = Field(None, description="Query execution time in ms")
    viz_type: str = Field("", description="Resolved Superset viz_type")


# =============================================================================
# Helpers
# =============================================================================

_discovery_service: Optional[DatasetDiscoveryService] = None
_chart_query_service: Optional[ChartQueryService] = None


def _get_discovery_service() -> DatasetDiscoveryService:
    """Lazy singleton for the discovery service."""
    global _discovery_service
    if _discovery_service is None:
        _discovery_service = DatasetDiscoveryService()
    return _discovery_service


def _get_chart_query_service() -> ChartQueryService:
    """Lazy singleton for the chart query service."""
    global _chart_query_service
    if _chart_query_service is None:
        _chart_query_service = ChartQueryService()
    return _chart_query_service


def _column_to_response(col: ColumnMetadata) -> ColumnMetadataResponse:
    return ColumnMetadataResponse(
        column_name=col.column_name,
        data_type=col.data_type,
        description=col.description,
        is_metric=col.is_metric,
        is_dimension=col.is_dimension,
        is_temporal=col.is_temporal,
    )


def _dataset_to_response(ds: DatasetInfo) -> DatasetResponse:
    return DatasetResponse(
        dataset_name=ds.dataset_name,
        dataset_id=ds.dataset_id,
        schema=ds.schema,
        description=ds.description,
        columns=[_column_to_response(c) for c in ds.columns],
    )


# =============================================================================
# Routes
# =============================================================================


@router.get(
    "",
    response_model=DatasetListResponse,
)
async def list_datasets(
    request: Request,
    db_session=Depends(check_custom_reports_entitlement),
):
    """
    List available datasets with column metadata.

    Returns all datasets discoverable from Superset, with column-level
    type information (is_metric, is_dimension, is_temporal) for the
    chart builder to filter options per chart type.

    If Superset is unavailable, returns cached data with stale=True.

    SECURITY: Requires valid tenant context and CUSTOM_REPORTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)
    logger.info(
        "Dataset list requested",
        extra={"tenant_id": tenant_ctx.tenant_id},
    )

    service = _get_discovery_service()
    result = service.discover_datasets()

    return DatasetListResponse(
        datasets=[_dataset_to_response(ds) for ds in result.datasets],
        total=len(result.datasets),
        stale=result.stale,
        cached_at=result.cached_at,
    )


@router.get(
    "/{dataset_id}/columns",
    response_model=list[ColumnMetadataResponse],
)
async def get_dataset_columns(
    request: Request,
    dataset_id: int,
    db_session=Depends(check_custom_reports_entitlement),
):
    """
    Get column metadata for a specific dataset.

    Returns typed column information for the chart builder.
    Numeric columns can be metrics. String columns are dimensions only.
    DateTime columns can be time axes.

    SECURITY: Requires valid tenant context and CUSTOM_REPORTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)
    logger.info(
        "Dataset columns requested",
        extra={"tenant_id": tenant_ctx.tenant_id, "dataset_id": dataset_id},
    )

    service = _get_discovery_service()
    columns = service.get_dataset_columns(dataset_id)

    if not columns:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset {dataset_id} not found or has no columns",
        )

    return [_column_to_response(c) for c in columns]


@router.post(
    "/validate-config",
    response_model=ValidateConfigResponse,
)
async def validate_config(
    request: Request,
    body: ValidateConfigRequest,
    db_session=Depends(check_custom_reports_entitlement),
):
    """
    Validate that columns referenced in a report config still exist.

    Returns warnings for missing columns rather than errors, so the
    frontend can show warning badges on affected report widgets.

    SECURITY: Requires valid tenant context and CUSTOM_REPORTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)
    logger.info(
        "Config validation requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "dataset_name": body.dataset_name,
            "column_count": len(body.referenced_columns),
        },
    )

    service = _get_discovery_service()
    result = service.discover_datasets()

    # Find the dataset
    target_ds = None
    for ds in result.datasets:
        if ds.dataset_name == body.dataset_name:
            target_ds = ds
            break

    if target_ds is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{body.dataset_name}' not found",
        )

    warnings = service.validate_config_columns(
        body.dataset_name,
        body.referenced_columns,
        target_ds.columns,
    )

    return ValidateConfigResponse(
        valid=len(warnings) == 0,
        warnings=[
            ConfigWarningResponse(
                column_name=w.column_name,
                dataset_name=w.dataset_name,
                message=w.message,
            )
            for w in warnings
        ],
    )


# =============================================================================
# Chart Preview Routes (Phase 2B)
# =============================================================================


@router.post(
    "/preview",
    response_model=ChartPreviewResponse,
)
async def chart_preview(
    request: Request,
    body: ChartPreviewRequest,
    db_session=Depends(check_custom_reports_entitlement),
):
    """
    Execute a chart preview query.

    Accepts a chart config, translates it to a Superset dataset query,
    and returns formatted data for frontend rendering.

    Constraints:
    - 100-row limit enforced
    - 10-second query timeout
    - Results cached for 60s keyed by (dataset_name, config_hash, tenant_id)
    - High-cardinality GROUP BY truncated to 100 unique values

    All column names are parameterized via Superset column references.
    No raw SQL interpolation.

    SECURITY: Requires valid tenant context and CUSTOM_REPORTS entitlement.
    """
    tenant_ctx = get_tenant_context(request)

    if not body.metrics:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one metric is required",
        )

    try:
        resolved_viz = validate_viz_type(body.viz_type)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    logger.info(
        "Chart preview requested",
        extra={
            "tenant_id": tenant_ctx.tenant_id,
            "dataset_name": body.dataset_name,
            "viz_type": body.viz_type,
            "metric_count": len(body.metrics),
            "dimension_count": len(body.dimensions),
        },
    )

    config = ChartConfig(
        dataset_name=body.dataset_name,
        metrics=body.metrics,
        dimensions=body.dimensions,
        filters=body.filters,
        time_range=body.time_range,
        time_column=body.time_column,
        time_grain=body.time_grain,
        viz_type=resolved_viz,
    )

    service = _get_chart_query_service()
    result = service.execute_preview(config, tenant_ctx.tenant_id)

    return ChartPreviewResponse(
        data=result.data,
        columns=result.columns,
        row_count=result.row_count,
        truncated=result.truncated,
        message=result.message,
        query_duration_ms=result.query_duration_ms,
        viz_type=result.viz_type,
    )
