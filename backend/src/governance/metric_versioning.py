"""
5.8.2 - Metric and Dashboard Version Enforcement

Deterministic version resolution. No auto-migration without approval.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .base import load_yaml_config, serialize_dataclass

logger = logging.getLogger(__name__)


def _parse_date_with_timezone(date_str: str) -> datetime:
    """Parse a date string and ensure it's timezone-aware (UTC)."""
    # Handle Z suffix for UTC
    date_str = date_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(date_str)
    # If timezone-naive, assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class MetricStatus(Enum):
    """Status of a metric version."""

    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUNSET = "sunset"


class WarningLevel(Enum):
    """Warning severity levels."""

    INFO = "INFO"
    WARN = "WARN"
    BLOCK = "BLOCK"


@dataclass
class DeprecationWarning:
    """
    Warning emitted when deprecated metrics are queried.

    Attributes:
        metric_name: Name of the metric
        current_version: Version being used
        recommended_version: Recommended version to migrate to
        level: Warning severity (INFO, WARN, BLOCK)
        message: Human-readable warning message
        days_until_sunset: Days remaining until sunset (None if not deprecated)
        affected_dashboards: List of dashboards using this version
        migration_guide: Path to migration documentation
    """

    metric_name: str
    current_version: str
    recommended_version: str
    level: WarningLevel
    message: str
    days_until_sunset: int | None = None
    affected_dashboards: list[str] = field(default_factory=list)
    migration_guide: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return serialize_dataclass(self)


@dataclass
class MetricResolution:
    """
    Result of resolving a metric version.

    Attributes:
        metric_name: Name of the metric
        resolved_version: The version that will be used
        dbt_model: The dbt model backing this metric
        definition: The metric calculation definition
        status: Current status (active, deprecated, sunset)
        warnings: Any warnings associated with this resolution
    """

    metric_name: str
    resolved_version: str
    dbt_model: str
    definition: str
    status: MetricStatus
    warnings: list[DeprecationWarning] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return serialize_dataclass(self)


@dataclass
class MerchantAlert:
    """Alert to be shown to merchants about metric changes."""

    tenant_id: str
    alert_type: str  # "dashboard_banner", "email_notification"
    metric_name: str
    message: str
    action_required: bool
    sunset_date: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return serialize_dataclass(self)


class MetricVersionResolver:
    """
    Resolves metric versions and enforces deprecation policies.

    Ensures deterministic version resolution and prevents use of sunset metrics.
    """

    def __init__(
        self,
        config_path: str | Path,
        alert_hooks: list[Callable[[MerchantAlert], None]] | None = None,
    ):
        """
        Initialize the metric version resolver.

        Args:
            config_path: Path to metrics_versions.yaml
            alert_hooks: Optional list of callback functions for merchant alerts
        """
        self.config_path = Path(config_path)
        self.alert_hooks = alert_hooks or []

        self._config: dict[str, Any] = {}
        self._warnings_emitted: list[DeprecationWarning] = []

        self._load_config()

    def _load_config(self) -> None:
        """Load metrics configuration from YAML."""
        self._config = load_yaml_config(self.config_path, logger)

    def resolve_metric(
        self,
        metric_name: str,
        requested_version: str | None = None,
        tenant_id: str | None = None,
        dashboard_id: str | None = None,
    ) -> MetricResolution:
        """
        Resolve a metric to its concrete version.

        Args:
            metric_name: Name of the metric to resolve
            requested_version: Specific version requested (None = current)
            tenant_id: Tenant requesting the metric
            dashboard_id: Dashboard context for resolution

        Returns:
            MetricResolution with resolved version and any warnings

        Raises:
            ValueError: If metric is sunset and cannot be used
        """
        metrics_config = self._config.get("metrics", {})
        metric_config = metrics_config.get(metric_name)

        if not metric_config:
            raise ValueError(f"Unknown metric: {metric_name}")

        # Determine which version to use
        version = requested_version or metric_config.get("current_version")
        version_config = metric_config.get(version)

        if not version_config:
            raise ValueError(f"Unknown version '{version}' for metric '{metric_name}'")

        # Check status and generate warnings/blocks
        status_str = version_config.get("status", "active")
        status = MetricStatus(status_str)
        warnings = []

        if status == MetricStatus.SUNSET:
            # BLOCK - sunset metrics cannot be used
            raise ValueError(
                f"Metric '{metric_name}' version '{version}' has been sunset "
                f"as of {version_config.get('sunset_date')}. "
                f"Please migrate to version '{metric_config.get('current_version')}'."
            )

        if status == MetricStatus.DEPRECATED:
            warning = self._generate_deprecation_warning(
                metric_name, version, metric_config, version_config, dashboard_id
            )
            warnings.append(warning)
            self._warnings_emitted.append(warning)

            # Emit merchant alerts if configured
            if tenant_id:
                self._emit_merchant_alerts(tenant_id, metric_name, version, warning)

        return MetricResolution(
            metric_name=metric_name,
            resolved_version=version,
            dbt_model=version_config.get("dbt_model", ""),
            definition=version_config.get("definition", ""),
            status=status,
            warnings=warnings,
        )

    def check_sunset_status(self, metric_name: str, version: str) -> bool:
        """
        Check if a specific metric version is sunset.

        Args:
            metric_name: Name of the metric
            version: Version to check

        Returns:
            True if the metric version is sunset
        """
        metrics_config = self._config.get("metrics", {})
        metric_config = metrics_config.get(metric_name, {})
        version_config = metric_config.get(version, {})

        status = version_config.get("status", "active")
        if status == "sunset":
            return True

        # Also check if sunset_date has passed
        sunset_date_str = version_config.get("sunset_date")
        if sunset_date_str:
            try:
                sunset_date = _parse_date_with_timezone(sunset_date_str)
                if datetime.now(timezone.utc) > sunset_date:
                    return True
            except ValueError:
                pass

        return False

    def get_deprecated_metrics(self) -> list[dict[str, Any]]:
        """Get all deprecated metrics with their sunset dates."""
        deprecated = []
        metrics_config = self._config.get("metrics", {})

        for metric_name, metric_config in metrics_config.items():
            if isinstance(metric_config, dict):
                for version, version_config in metric_config.items():
                    if (
                        isinstance(version_config, dict)
                        and version_config.get("status") == "deprecated"
                    ):
                        deprecated.append(
                            {
                                "metric_name": metric_name,
                                "version": version,
                                "deprecated_date": version_config.get(
                                    "deprecated_date"
                                ),
                                "sunset_date": version_config.get("sunset_date"),
                                "migration_guide": version_config.get("migration_guide"),
                                "current_version": metric_config.get("current_version"),
                            }
                        )

        return deprecated

    def get_affected_tenants(
        self, metric_name: str, version: str
    ) -> list[dict[str, Any]]:
        """
        Get tenants affected by a metric version.

        NOTE: This would integrate with actual tenant/dashboard data.
        Currently returns structure for integration.

        Args:
            metric_name: Name of the metric
            version: Version to check

        Returns:
            List of affected tenant information
        """
        # This would be implemented with actual database queries
        # Placeholder structure for integration
        return [
            {
                "tenant_id": "placeholder",
                "dashboards_affected": [],
                "notification_sent": False,
            }
        ]

    def _generate_deprecation_warning(
        self,
        metric_name: str,
        version: str,
        metric_config: dict[str, Any],
        version_config: dict[str, Any],
        dashboard_id: str | None,
    ) -> DeprecationWarning:
        """Generate a deprecation warning for a metric version."""
        enforcement = self._config.get("deprecation_enforcement", {})
        warn_days = enforcement.get("warn_days_before_sunset", 30)

        sunset_date_str = version_config.get("sunset_date")
        days_until_sunset = None

        if sunset_date_str:
            try:
                sunset_date = _parse_date_with_timezone(sunset_date_str)
                delta = sunset_date - datetime.now(timezone.utc)
                days_until_sunset = delta.days
            except ValueError:
                pass

        # Determine warning level
        level = WarningLevel.WARN
        if days_until_sunset is not None and days_until_sunset <= warn_days:
            level = WarningLevel.WARN
        if days_until_sunset is not None and days_until_sunset <= 0:
            level = WarningLevel.BLOCK

        current_version = metric_config.get("current_version", "unknown")
        message = (
            f"Metric '{metric_name}' version '{version}' is deprecated. "
            f"Please migrate to version '{current_version}'."
        )

        if days_until_sunset is not None:
            if days_until_sunset > 0:
                message += f" Sunset in {days_until_sunset} days."
            else:
                message += " This version has reached its sunset date."

        affected_dashboards = []
        if dashboard_id:
            affected_dashboards.append(dashboard_id)

        return DeprecationWarning(
            metric_name=metric_name,
            current_version=version,
            recommended_version=current_version,
            level=level,
            message=message,
            days_until_sunset=days_until_sunset,
            affected_dashboards=affected_dashboards,
            migration_guide=version_config.get("migration_guide"),
        )

    def _emit_merchant_alerts(
        self,
        tenant_id: str,
        metric_name: str,
        version: str,
        warning: DeprecationWarning,
    ) -> None:
        """Emit alerts to merchant through configured channels."""
        enforcement = self._config.get("deprecation_enforcement", {})
        visibility_channels = enforcement.get("merchant_visibility", [])

        for channel in visibility_channels:
            alert = MerchantAlert(
                tenant_id=tenant_id,
                alert_type=channel,
                metric_name=metric_name,
                message=warning.message,
                action_required=warning.level == WarningLevel.WARN,
                sunset_date=str(warning.days_until_sunset)
                if warning.days_until_sunset
                else None,
            )

            # Call registered hooks
            for hook in self.alert_hooks:
                try:
                    hook(alert)
                except Exception as e:
                    logger.error(f"Alert hook failed: {e}")

            logger.info(
                f"Merchant alert emitted: tenant={tenant_id}, "
                f"channel={channel}, metric={metric_name}"
            )

    def get_warnings_emitted(self) -> list[dict[str, Any]]:
        """Get all deprecation warnings emitted."""
        return [w.to_dict() for w in self._warnings_emitted]

    def supports_rollback_to(self, metric_name: str, version: str) -> bool:
        """
        Check if a metric version supports rollback.

        A version supports rollback if it's not sunset and
        was previously active.

        Args:
            metric_name: Name of the metric
            version: Version to check

        Returns:
            True if rollback to this version is supported
        """
        if self.check_sunset_status(metric_name, version):
            return False

        metrics_config = self._config.get("metrics", {})
        metric_config = metrics_config.get(metric_name, {})
        version_config = metric_config.get(version)

        # Version must exist
        return version_config is not None


class DeprecationMiddleware:
    """
    Middleware that intercepts metric queries and emits deprecation warnings.

    Can be integrated into query execution pipeline.
    """

    def __init__(self, resolver: MetricVersionResolver):
        """
        Initialize the middleware.

        Args:
            resolver: MetricVersionResolver instance
        """
        self.resolver = resolver

    def check_query(
        self,
        metric_name: str,
        version: str | None,
        tenant_id: str | None,
        dashboard_id: str | None,
    ) -> tuple[bool, MetricResolution | None, str | None]:
        """
        Check a query for deprecated metric usage.

        Args:
            metric_name: Metric being queried
            version: Version requested (None = current)
            tenant_id: Tenant making the query
            dashboard_id: Dashboard context

        Returns:
            Tuple of (allowed, resolution, error_message)
        """
        try:
            resolution = self.resolver.resolve_metric(
                metric_name=metric_name,
                requested_version=version,
                tenant_id=tenant_id,
                dashboard_id=dashboard_id,
            )

            # Log warnings but allow query to proceed for deprecated metrics
            for warning in resolution.warnings:
                logger.warning(f"Deprecation: {warning.message}")

            return (True, resolution, None)

        except ValueError as e:
            # Sunset metrics are blocked
            return (False, None, str(e))

    def wrap_query(
        self,
        query_func: Callable[..., Any],
        metric_name: str,
        version: str | None = None,
        tenant_id: str | None = None,
        dashboard_id: str | None = None,
    ) -> Any:
        """
        Wrap a query function with deprecation checking.

        Args:
            query_func: The query function to wrap
            metric_name: Metric being queried
            version: Version requested
            tenant_id: Tenant context
            dashboard_id: Dashboard context

        Returns:
            Query result or raises ValueError if blocked
        """
        allowed, resolution, error = self.check_query(
            metric_name, version, tenant_id, dashboard_id
        )

        if not allowed:
            raise ValueError(error)

        # Execute the query with resolved metric info
        return query_func(resolution)
