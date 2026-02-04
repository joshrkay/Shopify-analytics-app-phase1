"""
Dashboard Metric Binding Service for Story 2.3.

Manages how dashboards bind to metric versions:
- Load defaults from consumers.yaml
- Repoint dashboards to new metric versions (with governance)
- Pin/unpin tenants to specific versions
- Calculate blast radius for proposed changes
- Emit audit events for all mutations

SECURITY:
- Only Super Admin / Analytics Admin can repoint
- All mutations require a reason
- All mutations emit audit events
- Sunset versions block binding
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.governance.base import load_yaml_config, AuditLogger
from src.governance.metric_versioning import MetricVersionResolver, MetricStatus
from src.models.dashboard_metric_binding import DashboardMetricBinding

logger = logging.getLogger(__name__)

# Roles allowed to modify dashboard metric bindings
REPOINT_ALLOWED_ROLES = frozenset({"super_admin", "admin", "analytics_admin"})

PERMISSION_ERROR = "Insufficient permissions. Requires: super_admin or analytics_admin."
REASON_REQUIRED_ERROR = "Reason is required for all dashboard binding operations."


@dataclass
class RepointResult:
    """Result of a dashboard metric repoint operation."""
    success: bool
    dashboard_id: str
    metric_name: str
    old_version: str
    new_version: str
    reason: str
    repointed_by: str
    error: str | None = None
    audit_id: str | None = None


@dataclass
class BlastRadiusReport:
    """Report showing impact of a metric version change."""
    metric_name: str
    from_version: str
    to_version: str
    affected_dashboards: list[dict[str, Any]] = field(default_factory=list)
    affected_tenant_count: int = 0
    pinned_tenants: list[dict[str, Any]] = field(default_factory=list)
    is_breaking: bool = False


@dataclass
class BindingInfo:
    """Information about a single dashboard-metric binding."""
    dashboard_id: str
    metric_name: str
    metric_version: str
    pinned_by: str | None = None
    pinned_at: datetime | None = None
    reason: str | None = None
    tenant_id: str | None = None
    is_tenant_override: bool = False


class DashboardMetricBindingService:
    """
    Manages dashboard-to-metric-version bindings with governance enforcement.

    Bindings flow:
    1. consumers.yaml defines defaults (dashboard -> metric -> "current" or "vN")
    2. DB table stores overrides and tenant-level pins
    3. This service resolves the effective version for any dashboard/metric/tenant
    """

    def __init__(
        self,
        db: Session,
        consumers_config_path: str | Path,
        metric_resolver: MetricVersionResolver,
    ):
        self.db = db
        self.metric_resolver = metric_resolver
        self.audit = AuditLogger("dashboard_metric_binding_audit")
        self._consumers_config = load_yaml_config(consumers_config_path, logger)

    # ========================================================================
    # Private helpers (eliminate duplicate queries and validation)
    # ========================================================================

    def _find_binding(
        self,
        dashboard_id: str,
        metric_name: str,
        tenant_id: str | None = None,
    ) -> DashboardMetricBinding | None:
        """Query a single binding by dashboard/metric/tenant scope."""
        filters = [
            DashboardMetricBinding.dashboard_id == dashboard_id,
            DashboardMetricBinding.metric_name == metric_name,
        ]
        if tenant_id is None:
            filters.append(DashboardMetricBinding.tenant_id.is_(None))
        else:
            filters.append(DashboardMetricBinding.tenant_id == tenant_id)
        return self.db.query(DashboardMetricBinding).filter(*filters).first()

    def _to_binding_info(self, db_binding: DashboardMetricBinding) -> BindingInfo:
        """Convert a DB binding row to a BindingInfo dataclass."""
        return BindingInfo(
            dashboard_id=db_binding.dashboard_id,
            metric_name=db_binding.metric_name,
            metric_version=db_binding.metric_version,
            pinned_by=db_binding.pinned_by,
            pinned_at=db_binding.pinned_at,
            reason=db_binding.reason,
            tenant_id=db_binding.tenant_id,
            is_tenant_override=db_binding.tenant_id is not None,
        )

    def _check_governance(
        self,
        user_roles: list[str],
        reason: str,
        dashboard_id: str,
        metric_name: str,
        user: str,
    ) -> RepointResult | None:
        """
        Run shared governance checks (permission + reason).
        Returns a failure RepointResult if blocked, None if allowed.
        """
        if not self._has_repoint_permission(user_roles):
            self.audit.log(
                action="repoint_denied",
                resource_id=f"{dashboard_id}/{metric_name}",
                result="BLOCKED",
                reason=PERMISSION_ERROR,
                context={"user": user, "roles": user_roles},
            )
            return RepointResult(
                success=False,
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                old_version="",
                new_version="",
                reason=reason,
                repointed_by=user,
                error=PERMISSION_ERROR,
            )

        if not reason or not reason.strip():
            return RepointResult(
                success=False,
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                old_version="",
                new_version="",
                reason="",
                repointed_by=user,
                error=REASON_REQUIRED_ERROR,
            )

        return None

    def _has_repoint_permission(self, user_roles: list[str]) -> bool:
        """Check if user has permission to repoint bindings."""
        normalized_roles = {r.lower() for r in user_roles}
        return bool(normalized_roles & REPOINT_ALLOWED_ROLES)

    # ========================================================================
    # Public API
    # ========================================================================

    def get_default_bindings(self) -> dict[str, dict[str, str]]:
        """
        Get default bindings from consumers.yaml.

        Returns:
            Dict of dashboard_id -> {metric_name: version}
        """
        dashboards = self._consumers_config.get("dashboards", {})
        result = {}
        for dashboard_id, dashboard_config in dashboards.items():
            if isinstance(dashboard_config, dict):
                metrics = dashboard_config.get("metrics", {})
                result[dashboard_id] = dict(metrics)
        return result

    def resolve_binding(
        self,
        dashboard_id: str,
        metric_name: str,
        tenant_id: str | None = None,
    ) -> BindingInfo:
        """
        Resolve the effective metric version for a dashboard/metric/tenant.

        Resolution order (highest priority first):
        1. Tenant-level DB override (if tenant_id provided)
        2. Global DB override
        3. consumers.yaml default
        """
        # 1. Check tenant-level DB override
        if tenant_id:
            tenant_binding = self._find_binding(dashboard_id, metric_name, tenant_id)
            if tenant_binding:
                return self._to_binding_info(tenant_binding)

        # 2. Check global DB override
        global_binding = self._find_binding(dashboard_id, metric_name, tenant_id=None)
        if global_binding:
            return self._to_binding_info(global_binding)

        # 3. Fall back to consumers.yaml default
        defaults = self.get_default_bindings()
        dashboard_defaults = defaults.get(dashboard_id, {})
        version = dashboard_defaults.get(metric_name, "current")

        return BindingInfo(
            dashboard_id=dashboard_id,
            metric_name=metric_name,
            metric_version=version,
        )

    def repoint_dashboard_metric(
        self,
        dashboard_id: str,
        metric_name: str,
        new_version: str,
        repointed_by: str,
        reason: str,
        user_roles: list[str],
        tenant_id: str | None = None,
    ) -> RepointResult:
        """
        Repoint a dashboard's metric to a new version.

        Enforces governance:
        - Only allowed roles can repoint
        - Reason is required
        - Sunset versions are blocked
        - Audit event is emitted
        """
        # Governance checks (permission + reason)
        blocked = self._check_governance(user_roles, reason, dashboard_id, metric_name, repointed_by)
        if blocked:
            blocked.new_version = new_version
            blocked.reason = reason
            return blocked

        # Validate the new version is not sunset
        if new_version != "current":
            try:
                resolution = self.metric_resolver.resolve_metric(
                    metric_name=metric_name,
                    requested_version=new_version,
                )
                if resolution.status == MetricStatus.SUNSET:
                    error_msg = (
                        f"Cannot bind to sunset version '{new_version}' "
                        f"of metric '{metric_name}'. Use a newer version."
                    )
                    self.audit.log(
                        action="repoint_blocked_sunset",
                        resource_id=f"{dashboard_id}/{metric_name}",
                        result="BLOCKED",
                        reason=error_msg,
                    )
                    return RepointResult(
                        success=False,
                        dashboard_id=dashboard_id,
                        metric_name=metric_name,
                        old_version="",
                        new_version=new_version,
                        reason=reason,
                        repointed_by=repointed_by,
                        error=error_msg,
                    )
            except ValueError as e:
                return RepointResult(
                    success=False,
                    dashboard_id=dashboard_id,
                    metric_name=metric_name,
                    old_version="",
                    new_version=new_version,
                    reason=reason,
                    repointed_by=repointed_by,
                    error=str(e),
                )

        # Get current binding for old_version tracking
        current_binding = self.resolve_binding(dashboard_id, metric_name, tenant_id)
        old_version = current_binding.metric_version

        # Upsert the binding in DB
        existing = self._find_binding(dashboard_id, metric_name, tenant_id)
        now = datetime.now(timezone.utc)

        if existing:
            existing.previous_version = existing.metric_version
            existing.metric_version = new_version
            existing.pinned_by = repointed_by
            existing.pinned_at = now
            existing.reason = reason
        else:
            new_binding = DashboardMetricBinding(
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                metric_version=new_version,
                pinned_by=repointed_by,
                pinned_at=now,
                reason=reason,
                tenant_id=tenant_id,
                previous_version=old_version,
            )
            self.db.add(new_binding)

        self.db.flush()

        audit_id = self.audit.log(
            action="repoint",
            resource_id=f"{dashboard_id}/{metric_name}",
            result="SUCCESS",
            reason=reason,
            context={
                "old_version": old_version,
                "new_version": new_version,
                "repointed_by": repointed_by,
                "tenant_id": tenant_id,
            },
        )

        logger.info(
            "Dashboard metric repointed",
            extra={
                "dashboard_id": dashboard_id,
                "metric_name": metric_name,
                "old_version": old_version,
                "new_version": new_version,
                "repointed_by": repointed_by,
                "tenant_id": tenant_id,
            },
        )

        return RepointResult(
            success=True,
            dashboard_id=dashboard_id,
            metric_name=metric_name,
            old_version=old_version,
            new_version=new_version,
            reason=reason,
            repointed_by=repointed_by,
            audit_id=audit_id,
        )

    def get_blast_radius(
        self,
        metric_name: str,
        from_version: str,
        to_version: str,
    ) -> BlastRadiusReport:
        """
        Calculate the blast radius of changing a metric version.

        Reports which dashboards and tenants would be affected.
        """
        defaults = self.get_default_bindings()
        affected_dashboards = []

        # Check each dashboard's default binding
        for dashboard_id, metrics in defaults.items():
            bound_version = metrics.get(metric_name)
            if bound_version is not None:
                if bound_version == "current" or bound_version == from_version:
                    affected_dashboards.append({
                        "dashboard_id": dashboard_id,
                        "current_binding": bound_version,
                        "source": "consumers.yaml",
                    })

        # Check DB overrides
        db_bindings = self.db.query(DashboardMetricBinding).filter(
            DashboardMetricBinding.metric_name == metric_name,
            DashboardMetricBinding.tenant_id.is_(None),
        ).all()

        for binding in db_bindings:
            if binding.metric_version == from_version:
                already_listed = any(
                    d["dashboard_id"] == binding.dashboard_id
                    for d in affected_dashboards
                )
                if not already_listed:
                    affected_dashboards.append({
                        "dashboard_id": binding.dashboard_id,
                        "current_binding": binding.metric_version,
                        "source": "db_override",
                    })

        # Tenant-level pins (these would NOT change)
        pinned_rows = self.db.query(DashboardMetricBinding).filter(
            DashboardMetricBinding.metric_name == metric_name,
            DashboardMetricBinding.tenant_id.isnot(None),
        ).all()

        pinned_tenants = [
            {
                "tenant_id": b.tenant_id,
                "dashboard_id": b.dashboard_id,
                "pinned_version": b.metric_version,
                "pinned_by": b.pinned_by,
            }
            for b in pinned_rows
        ]

        is_breaking = from_version != "current" and to_version != from_version

        return BlastRadiusReport(
            metric_name=metric_name,
            from_version=from_version,
            to_version=to_version,
            affected_dashboards=affected_dashboards,
            affected_tenant_count=len({b.tenant_id for b in pinned_rows}),
            pinned_tenants=pinned_tenants,
            is_breaking=is_breaking,
        )

    def list_bindings(
        self,
        dashboard_id: str | None = None,
        metric_name: str | None = None,
        tenant_id: str | None = None,
    ) -> list[BindingInfo]:
        """
        List all bindings, optionally filtered.
        Combines defaults from consumers.yaml with DB overrides.
        """
        results = []
        defaults = self.get_default_bindings()

        # Build from defaults
        for d_id, metrics in defaults.items():
            if dashboard_id and d_id != dashboard_id:
                continue
            for m_name, version in metrics.items():
                if metric_name and m_name != metric_name:
                    continue
                results.append(BindingInfo(
                    dashboard_id=d_id,
                    metric_name=m_name,
                    metric_version=version,
                ))

        # Override with DB bindings
        query = self.db.query(DashboardMetricBinding)
        if dashboard_id:
            query = query.filter(DashboardMetricBinding.dashboard_id == dashboard_id)
        if metric_name:
            query = query.filter(DashboardMetricBinding.metric_name == metric_name)
        if tenant_id:
            query = query.filter(DashboardMetricBinding.tenant_id == tenant_id)
        else:
            query = query.filter(DashboardMetricBinding.tenant_id.is_(None))

        for db_binding in query.all():
            info = self._to_binding_info(db_binding)
            # Replace matching default or append
            replaced = False
            for i, r in enumerate(results):
                if r.dashboard_id == info.dashboard_id and r.metric_name == info.metric_name:
                    results[i] = info
                    replaced = True
                    break
            if not replaced:
                results.append(info)

        return results

    def pin_tenant(
        self,
        dashboard_id: str,
        metric_name: str,
        version: str,
        tenant_id: str,
        pinned_by: str,
        reason: str,
        user_roles: list[str],
    ) -> RepointResult:
        """Pin a specific tenant to a metric version."""
        return self.repoint_dashboard_metric(
            dashboard_id=dashboard_id,
            metric_name=metric_name,
            new_version=version,
            repointed_by=pinned_by,
            reason=reason,
            user_roles=user_roles,
            tenant_id=tenant_id,
        )

    def unpin_tenant(
        self,
        dashboard_id: str,
        metric_name: str,
        tenant_id: str,
        unpinned_by: str,
        reason: str,
        user_roles: list[str],
    ) -> RepointResult:
        """Remove a tenant-level pin, reverting to global binding."""
        blocked = self._check_governance(user_roles, reason, dashboard_id, metric_name, unpinned_by)
        if blocked:
            return blocked

        existing = self._find_binding(dashboard_id, metric_name, tenant_id)

        if not existing:
            return RepointResult(
                success=False,
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                old_version="",
                new_version="",
                reason=reason,
                repointed_by=unpinned_by,
                error=f"No tenant pin found for tenant '{tenant_id}'.",
            )

        old_version = existing.metric_version
        self.db.delete(existing)
        self.db.flush()

        # Resolve the new effective version (falls back to global/default)
        new_binding = self.resolve_binding(dashboard_id, metric_name)

        audit_id = self.audit.log(
            action="unpin_tenant",
            resource_id=f"{dashboard_id}/{metric_name}/{tenant_id}",
            result="SUCCESS",
            reason=reason,
            context={
                "old_pinned_version": old_version,
                "new_effective_version": new_binding.metric_version,
                "unpinned_by": unpinned_by,
                "tenant_id": tenant_id,
            },
        )

        logger.info(
            "Tenant metric pin removed",
            extra={
                "dashboard_id": dashboard_id,
                "metric_name": metric_name,
                "tenant_id": tenant_id,
                "old_version": old_version,
                "new_effective_version": new_binding.metric_version,
                "unpinned_by": unpinned_by,
            },
        )

        return RepointResult(
            success=True,
            dashboard_id=dashboard_id,
            metric_name=metric_name,
            old_version=old_version,
            new_version=new_binding.metric_version,
            reason=reason,
            repointed_by=unpinned_by,
            audit_id=audit_id,
        )

    def get_audit_trail(self) -> list[dict[str, Any]]:
        """Get all audit entries for dashboard metric bindings."""
        return self.audit.get_entries()
