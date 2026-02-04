"""
Dashboard metric binding API schemas for Story 2.3.

Pydantic models for binding queries, mutations, and responses.
"""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field


class BindingEntry(BaseModel):
    """Single dashboard-metric binding."""

    dashboard_id: str
    metric_name: str
    metric_version: str
    pinned_by: Optional[str] = None
    pinned_at: Optional[datetime] = None
    reason: Optional[str] = None
    tenant_id: Optional[str] = None
    is_tenant_override: bool = False


class BindingsListResponse(BaseModel):
    """Response for listing bindings."""

    bindings: list[BindingEntry]
    total: int


class RepointRequest(BaseModel):
    """Request to repoint a dashboard metric binding."""

    dashboard_id: str = Field(..., description="Dashboard to repoint")
    metric_name: str = Field(..., description="Metric to repoint")
    new_version: str = Field(..., description="Target version ('current', 'v1', 'v2', etc.)")
    reason: str = Field(..., min_length=1, description="Required justification for the repoint")
    tenant_id: Optional[str] = Field(None, description="Tenant ID for tenant-level pin (null for global)")


class RepointResponse(BaseModel):
    """Response for a repoint operation."""

    success: bool
    dashboard_id: str
    metric_name: str
    old_version: str
    new_version: str
    reason: str
    repointed_by: str
    error: Optional[str] = None
    audit_id: Optional[str] = None


class UnpinRequest(BaseModel):
    """Request to unpin a tenant from a metric version."""

    dashboard_id: str = Field(..., description="Dashboard identifier")
    metric_name: str = Field(..., description="Metric name")
    tenant_id: str = Field(..., description="Tenant to unpin")
    reason: str = Field(..., min_length=1, description="Required justification")


class BlastRadiusRequest(BaseModel):
    """Request for blast radius analysis."""

    metric_name: str = Field(..., description="Metric being changed")
    from_version: str = Field(..., description="Current version")
    to_version: str = Field(..., description="Proposed new version")


class BlastRadiusResponse(BaseModel):
    """Blast radius analysis result."""

    metric_name: str
    from_version: str
    to_version: str
    affected_dashboards: list[dict[str, Any]]
    affected_tenant_count: int
    pinned_tenants: list[dict[str, Any]]
    is_breaking: bool
