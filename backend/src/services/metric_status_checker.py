"""
Metric Status Checker for Story 2.3.

Provides two capabilities:
1. Hard-fail enforcement: Raises when a dashboard references a sunset metric
2. Banner data: Returns contextual banner info for affected dashboards

SECURITY:
- Read-only service (no mutations)
- Tenant-scoped resolution via DashboardMetricBindingService
"""

import logging
from dataclasses import dataclass
from typing import Any

from src.governance.metric_versioning import (
    MetricVersionResolver,
    MetricStatus,
)
from src.services.dashboard_metric_binding_service import (
    DashboardMetricBindingService,
)

logger = logging.getLogger(__name__)


class MetricSunsetError(Exception):
    """Raised when a dashboard references a sunset/retired metric version."""

    def __init__(self, dashboard_id: str, metric_name: str, version: str, message: str):
        self.dashboard_id = dashboard_id
        self.metric_name = metric_name
        self.version = version
        super().__init__(message)


class MetricVersionNotFoundError(Exception):
    """Raised when a binding references a metric version that does not exist."""

    def __init__(self, dashboard_id: str, metric_name: str, version: str):
        self.dashboard_id = dashboard_id
        self.metric_name = metric_name
        self.version = version
        super().__init__(
            f"Metric version '{version}' of '{metric_name}' does not exist. "
            f"Dashboard '{dashboard_id}' cannot render. "
            f"Action required: repoint this dashboard to a valid version."
        )


@dataclass
class BannerData:
    """Data for rendering a metric version banner on a dashboard."""
    show: bool
    tone: str  # "info", "warning", "critical"
    dashboard_id: str
    metric_name: str
    current_version: str
    message: str
    change_date: str | None = None
    new_version_available: str | None = None
    days_until_sunset: int | None = None


class MetricStatusChecker:
    """
    Checks metric version status for dashboard rendering.

    Calling `check_dashboard_metric()` will:
    - RAISE MetricSunsetError if the bound version is sunset
    - RAISE MetricVersionNotFoundError if the version doesn't exist
    - Return BannerData if there's a deprecation warning or new version
    - Return BannerData(show=False) if everything is clean
    """

    def __init__(
        self,
        binding_service: DashboardMetricBindingService,
        metric_resolver: MetricVersionResolver,
    ):
        self.binding_service = binding_service
        self.metric_resolver = metric_resolver

    def check_dashboard_metric(
        self,
        dashboard_id: str,
        metric_name: str,
        tenant_id: str | None = None,
    ) -> BannerData:
        """
        Check a single dashboard-metric binding for status issues.

        Raises:
            MetricSunsetError: If bound version is sunset (hard-fail)
            MetricVersionNotFoundError: If bound version doesn't exist

        Returns:
            BannerData for rendering on the dashboard
        """
        binding = self.binding_service.resolve_binding(
            dashboard_id, metric_name, tenant_id
        )
        version = binding.metric_version

        # "current" always resolves to the latest approved version - no sunset risk
        if version == "current":
            return BannerData(
                show=False,
                tone="info",
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                current_version="current",
                message="",
            )

        # HARD-FAIL: Check sunset BEFORE resolve_metric (which raises for sunset)
        if self.metric_resolver.check_sunset_status(metric_name, version):
            raise MetricSunsetError(
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                version=version,
                message=(
                    f"Dashboard '{dashboard_id}' cannot render: "
                    f"metric '{metric_name}' version '{version}' has been retired. "
                    f"Action required: repoint to an active version."
                ),
            )

        # Resolve the concrete version through the metric versioning system
        try:
            resolution = self.metric_resolver.resolve_metric(
                metric_name=metric_name,
                requested_version=version,
            )
        except ValueError:
            raise MetricVersionNotFoundError(dashboard_id, metric_name, version)

        # DEPRECATION WARNING: Show banner with countdown
        if resolution.status == MetricStatus.DEPRECATED:
            warnings = resolution.warnings or []
            days_until = None
            for w in warnings:
                if hasattr(w, "days_until_sunset") and w.days_until_sunset is not None:
                    days_until = w.days_until_sunset
                    break

            sunset_date = None
            metric_config = self.metric_resolver._config.get("metrics", {}).get(metric_name, {})
            version_config = metric_config.get(version, {})
            sunset_date = version_config.get("sunset_date")

            return BannerData(
                show=True,
                tone="warning",
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                current_version=version,
                message=(
                    f"Metric '{metric_name}' version '{version}' is deprecated. "
                    f"{'It will be retired on ' + sunset_date + '. ' if sunset_date else ''}"
                    f"Please coordinate with your admin to upgrade."
                ),
                change_date=sunset_date,
                days_until_sunset=days_until,
            )

        # ACTIVE: Check if there's a newer version available
        metric_config = self.metric_resolver._config.get("metrics", {}).get(metric_name, {})
        current_version_tag = metric_config.get("current_version")

        if current_version_tag and current_version_tag != version:
            return BannerData(
                show=True,
                tone="info",
                dashboard_id=dashboard_id,
                metric_name=metric_name,
                current_version=version,
                message=(
                    f"A newer version of '{metric_name}' is available ({current_version_tag}). "
                    f"This dashboard is pinned to {version}."
                ),
                new_version_available=current_version_tag,
            )

        # Clean: active and up-to-date
        return BannerData(
            show=False,
            tone="info",
            dashboard_id=dashboard_id,
            metric_name=metric_name,
            current_version=version,
            message="",
        )

    def check_all_dashboard_metrics(
        self,
        dashboard_id: str,
        tenant_id: str | None = None,
    ) -> list[BannerData]:
        """
        Check all metrics for a dashboard.

        Returns list of BannerData (only those with show=True or errors).
        Sunset metrics raise immediately; this method collects warnings.
        """
        bindings = self.binding_service.list_bindings(dashboard_id=dashboard_id)
        results = []

        for binding in bindings:
            banner = self.check_dashboard_metric(
                dashboard_id=binding.dashboard_id,
                metric_name=binding.metric_name,
                tenant_id=tenant_id,
            )
            if banner.show:
                results.append(banner)

        return results

    def validate_all_bindings(self) -> list[dict[str, Any]]:
        """
        Validate all bindings across all dashboards.

        Returns a list of issues (sunset, missing, deprecated).
        Does not raise - collects all issues for reporting.
        """
        all_bindings = self.binding_service.list_bindings()
        issues = []

        for binding in all_bindings:
            if binding.metric_version == "current":
                continue

            # Check sunset first (resolve_metric raises for sunset versions)
            if self.metric_resolver.check_sunset_status(
                binding.metric_name, binding.metric_version
            ):
                issues.append({
                    "level": "critical",
                    "dashboard_id": binding.dashboard_id,
                    "metric_name": binding.metric_name,
                    "version": binding.metric_version,
                    "issue": "Version is sunset/retired. Dashboard will fail to render.",
                })
                continue

            try:
                resolution = self.metric_resolver.resolve_metric(
                    metric_name=binding.metric_name,
                    requested_version=binding.metric_version,
                )

                if resolution.status == MetricStatus.DEPRECATED:
                    issues.append({
                        "level": "warning",
                        "dashboard_id": binding.dashboard_id,
                        "metric_name": binding.metric_name,
                        "version": binding.metric_version,
                        "issue": "Version is deprecated. Plan migration to a newer version.",
                    })

            except ValueError:
                issues.append({
                    "level": "critical",
                    "dashboard_id": binding.dashboard_id,
                    "metric_name": binding.metric_name,
                    "version": binding.metric_version,
                    "issue": "Version does not exist in metrics registry.",
                })

        return issues
