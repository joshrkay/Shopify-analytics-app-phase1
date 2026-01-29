"""
Data Quality Service for sync health monitoring.

Provides:
- Freshness evaluation against source-specific SLAs
- Anomaly detection (row count drops, zero values, missing days, etc.)
- Severity calculation (warning/high/critical)
- Incident management
- Event emission for alerting

SECURITY: All operations are tenant-scoped via tenant_id from JWT.

Freshness SLAs:
- Shopify orders/refunds: stale if > 2 hours
- Recharge: stale if > 2 hours
- Ads (Meta, Google, TikTok, Pinterest, Snap, Amazon): stale if > 24 hours
- Klaviyo + SMS (Postscript, Attentive): stale if > 24 hours
- GA4: stale if > 24 hours

Severity Multipliers:
- warning: exceeded threshold up to 2x
- high: exceeded threshold up to 4x
- critical: exceeded > 4x OR critical connector missing beyond threshold
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Dict, Any, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_

from src.models.dq_models import (
    DQCheck, DQResult, DQIncident, SyncRun,
    DQCheckType, DQSeverity, DQResultStatus, DQIncidentStatus,
    SyncRunStatus, ConnectorSourceType,
    FRESHNESS_THRESHOLDS, get_freshness_threshold, is_critical_source,
)
from src.models.airbyte_connection import TenantAirbyteConnection

logger = logging.getLogger(__name__)


# Event types for alerting
class DQEventType(str, Enum):
    """Data quality event types for alerting."""
    FRESHNESS_FAILED = "dq.freshness_failed"
    ANOMALY_DETECTED = "dq.anomaly_detected"
    SEVERE_BLOCK = "dq.severe_block"
    RESOLVED = "dq.resolved"


@dataclass
class DQEvent:
    """
    Data quality event for alerting.

    Emitted when DQ checks fail or resolve.
    """
    event_type: DQEventType
    run_id: str
    correlation_id: str
    tenant_id: str
    connector_id: str
    check_type: str
    severity: Optional[DQSeverity]
    message: str
    merchant_message: str
    support_details: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "event_type": self.event_type.value,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "connector_id": self.connector_id,
            "check_type": self.check_type,
            "severity": self.severity.value if self.severity else None,
            "message": self.message,
            "merchant_message": self.merchant_message,
            "support_details": self.support_details,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class FreshnessCheckResult:
    """Result of a freshness check."""
    connector_id: str
    connector_name: str
    source_type: ConnectorSourceType
    is_fresh: bool
    severity: Optional[DQSeverity]
    minutes_since_sync: Optional[int]
    threshold_minutes: int
    last_sync_at: Optional[datetime]
    message: str
    merchant_message: str
    support_details: str


@dataclass
class AnomalyCheckResult:
    """Result of an anomaly check."""
    connector_id: str
    connector_name: str
    check_type: DQCheckType
    is_anomaly: bool
    severity: DQSeverity
    observed_value: Optional[Decimal]
    expected_value: Optional[Decimal]
    message: str
    merchant_message: str
    support_details: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorSyncHealth:
    """Sync health summary for a single connector."""
    connector_id: str
    connector_name: str
    source_type: Optional[str]
    status: str  # "healthy", "delayed", "error"
    freshness_status: str  # "fresh", "stale", "critical", "never_synced"
    severity: Optional[DQSeverity]
    last_sync_at: Optional[datetime]
    last_rows_synced: Optional[int]
    minutes_since_sync: Optional[int]
    message: str
    merchant_message: str
    recommended_actions: List[str]
    is_blocking: bool
    has_open_incidents: bool
    open_incident_count: int


@dataclass
class SyncHealthSummary:
    """Overall sync health summary for a tenant."""
    tenant_id: str
    total_connectors: int
    healthy_count: int
    delayed_count: int
    error_count: int
    blocking_issues: int
    overall_status: str  # "healthy", "degraded", "critical"
    health_score: float  # 0-100
    connectors: List[ConnectorSyncHealth]
    has_blocking_issues: bool


class DQServiceError(Exception):
    """Base exception for DQ service errors."""
    pass


class DQService:
    """
    Data Quality service for freshness and anomaly checks.

    SECURITY: All methods require tenant_id from JWT context.
    """

    def __init__(self, db_session: Session, tenant_id: str):
        """
        Initialize DQ service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID from JWT (org_id)

        Raises:
            ValueError: If tenant_id is empty or None
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self._event_queue: List[DQEvent] = []

    def _generate_run_id(self) -> str:
        """Generate a unique run ID."""
        return str(uuid.uuid4())

    def _generate_correlation_id(self) -> str:
        """Generate a correlation ID for tracing."""
        return str(uuid.uuid4())

    def _get_source_type(self, connector_source: str) -> Optional[ConnectorSourceType]:
        """Map connector source string to ConnectorSourceType enum."""
        source_mapping = {
            "shopify": ConnectorSourceType.SHOPIFY_ORDERS,
            "shopify_orders": ConnectorSourceType.SHOPIFY_ORDERS,
            "shopify_refunds": ConnectorSourceType.SHOPIFY_REFUNDS,
            "recharge": ConnectorSourceType.RECHARGE,
            "meta": ConnectorSourceType.META_ADS,
            "meta_ads": ConnectorSourceType.META_ADS,
            "facebook": ConnectorSourceType.META_ADS,
            "google": ConnectorSourceType.GOOGLE_ADS,
            "google_ads": ConnectorSourceType.GOOGLE_ADS,
            "tiktok": ConnectorSourceType.TIKTOK_ADS,
            "tiktok_ads": ConnectorSourceType.TIKTOK_ADS,
            "pinterest": ConnectorSourceType.PINTEREST_ADS,
            "pinterest_ads": ConnectorSourceType.PINTEREST_ADS,
            "snap": ConnectorSourceType.SNAP_ADS,
            "snap_ads": ConnectorSourceType.SNAP_ADS,
            "snapchat": ConnectorSourceType.SNAP_ADS,
            "amazon": ConnectorSourceType.AMAZON_ADS,
            "amazon_ads": ConnectorSourceType.AMAZON_ADS,
            "klaviyo": ConnectorSourceType.KLAVIYO,
            "postscript": ConnectorSourceType.POSTSCRIPT,
            "attentive": ConnectorSourceType.ATTENTIVE,
            "ga4": ConnectorSourceType.GA4,
            "google_analytics": ConnectorSourceType.GA4,
        }
        if connector_source:
            return source_mapping.get(connector_source.lower())
        return None

    def _calculate_freshness_severity(
        self,
        minutes_since_sync: int,
        source_type: ConnectorSourceType
    ) -> Optional[DQSeverity]:
        """
        Calculate severity based on minutes since sync and source type.

        Severity Multipliers:
        - warning: exceeded threshold up to 2x
        - high: exceeded threshold up to 4x
        - critical: exceeded > 4x OR critical source
        """
        thresholds = FRESHNESS_THRESHOLDS.get(source_type)
        if not thresholds:
            return None

        warning_threshold = thresholds["warning"]
        high_threshold = thresholds["high"]
        critical_threshold = thresholds["critical"]

        # Check if beyond critical
        if minutes_since_sync > critical_threshold:
            return DQSeverity.CRITICAL

        # Check if beyond high (2x to 4x)
        if minutes_since_sync > high_threshold:
            return DQSeverity.HIGH

        # Check if beyond warning (up to 2x)
        if minutes_since_sync > warning_threshold:
            return DQSeverity.WARNING

        return None

    def check_freshness(
        self,
        connector_id: str,
        run_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> FreshnessCheckResult:
        """
        Check freshness for a single connector.

        Args:
            connector_id: Connector ID to check
            run_id: Optional run ID for tracking
            correlation_id: Optional correlation ID for tracing

        Returns:
            FreshnessCheckResult with check results
        """
        run_id = run_id or self._generate_run_id()
        correlation_id = correlation_id or self._generate_correlation_id()

        # Get connector info (tenant-scoped query)
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == connector_id,
        ).first()

        if not connector:
            return FreshnessCheckResult(
                connector_id=connector_id,
                connector_name="Unknown",
                source_type=ConnectorSourceType.SHOPIFY_ORDERS,
                is_fresh=False,
                severity=DQSeverity.CRITICAL,
                minutes_since_sync=None,
                threshold_minutes=120,
                last_sync_at=None,
                message="Connector not found",
                merchant_message="Data source not found. Please reconnect.",
                support_details=f"Connector {connector_id} not found for tenant {self.tenant_id}",
            )

        # Determine source type
        source_type = self._get_source_type(connector.source_type)
        if not source_type:
            source_type = ConnectorSourceType.SHOPIFY_ORDERS  # Default

        # Calculate time since last sync
        if not connector.last_sync_at:
            # Never synced
            threshold = get_freshness_threshold(source_type, DQSeverity.WARNING)
            return FreshnessCheckResult(
                connector_id=connector_id,
                connector_name=connector.connection_name,
                source_type=source_type,
                is_fresh=False,
                severity=DQSeverity.CRITICAL if is_critical_source(source_type) else DQSeverity.HIGH,
                minutes_since_sync=None,
                threshold_minutes=threshold,
                last_sync_at=None,
                message=f"Connector {connector.connection_name} has never synced",
                merchant_message="This data source has never synced. Please check the connection.",
                support_details=f"Connector {connector_id} has no last_sync_at timestamp",
            )

        # Calculate minutes since sync
        now = datetime.now(timezone.utc)
        last_sync = connector.last_sync_at
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)

        minutes_since_sync = int((now - last_sync).total_seconds() / 60)
        threshold = get_freshness_threshold(source_type, DQSeverity.WARNING)

        # Calculate severity
        severity = self._calculate_freshness_severity(minutes_since_sync, source_type)

        is_fresh = severity is None

        if is_fresh:
            return FreshnessCheckResult(
                connector_id=connector_id,
                connector_name=connector.connection_name,
                source_type=source_type,
                is_fresh=True,
                severity=None,
                minutes_since_sync=minutes_since_sync,
                threshold_minutes=threshold,
                last_sync_at=last_sync,
                message=f"Connector {connector.connection_name} is fresh",
                merchant_message="Data is up to date.",
                support_details="",
            )

        # Generate messages based on severity
        hours_stale = minutes_since_sync // 60

        if severity == DQSeverity.CRITICAL:
            merchant_msg = (
                f"Your {connector.connection_name} data is significantly delayed "
                f"({hours_stale}+ hours). Reports may be inaccurate."
            )
            support_msg = (
                f"CRITICAL: {connector.connection_name} ({connector_id}) is "
                f"{minutes_since_sync} minutes stale (threshold: {threshold} minutes). "
                f"Check Airbyte job status and API rate limits."
            )
        elif severity == DQSeverity.HIGH:
            merchant_msg = (
                f"Your {connector.connection_name} data is delayed "
                f"({hours_stale}+ hours). Recent data may not appear in reports."
            )
            support_msg = (
                f"HIGH: {connector.connection_name} ({connector_id}) is "
                f"{minutes_since_sync} minutes stale (threshold: {threshold} minutes)."
            )
        else:
            merchant_msg = (
                f"Your {connector.connection_name} data may be slightly delayed."
            )
            support_msg = (
                f"WARNING: {connector.connection_name} ({connector_id}) is "
                f"{minutes_since_sync} minutes stale (threshold: {threshold} minutes)."
            )

        return FreshnessCheckResult(
            connector_id=connector_id,
            connector_name=connector.connection_name,
            source_type=source_type,
            is_fresh=False,
            severity=severity,
            minutes_since_sync=minutes_since_sync,
            threshold_minutes=threshold,
            last_sync_at=last_sync,
            message=f"Connector {connector.connection_name} is stale ({severity.value})",
            merchant_message=merchant_msg,
            support_details=support_msg,
        )

    def check_all_freshness(
        self,
        run_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> List[FreshnessCheckResult]:
        """
        Check freshness for all tenant connectors.

        Returns:
            List of FreshnessCheckResult for all connectors
        """
        run_id = run_id or self._generate_run_id()
        correlation_id = correlation_id or self._generate_correlation_id()

        # Get all active connectors for tenant
        connectors = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.is_enabled == True,
            TenantAirbyteConnection.status != "deleted",
        ).all()

        results = []
        for connector in connectors:
            result = self.check_freshness(connector.id, run_id, correlation_id)
            results.append(result)

        return results

    def check_row_count_drop(
        self,
        connector_id: str,
        current_count: int,
        previous_count: int,
        threshold_percent: float = 50.0,
    ) -> AnomalyCheckResult:
        """
        Check for row count drop anomaly (>= 50% day-over-day).

        Args:
            connector_id: Connector ID
            current_count: Today's row count
            previous_count: Yesterday's row count
            threshold_percent: Drop threshold percentage (default 50%)

        Returns:
            AnomalyCheckResult
        """
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == connector_id,
        ).first()

        connector_name = connector.connection_name if connector else "Unknown"

        if previous_count == 0:
            return AnomalyCheckResult(
                connector_id=connector_id,
                connector_name=connector_name,
                check_type=DQCheckType.ROW_COUNT_DROP,
                is_anomaly=False,
                severity=DQSeverity.WARNING,
                observed_value=Decimal(current_count),
                expected_value=Decimal(previous_count),
                message="No baseline for comparison (previous count is 0)",
                merchant_message="",
                support_details="Cannot calculate drop percentage with zero baseline",
            )

        drop_percent = ((previous_count - current_count) / previous_count) * 100

        if drop_percent >= threshold_percent:
            return AnomalyCheckResult(
                connector_id=connector_id,
                connector_name=connector_name,
                check_type=DQCheckType.ROW_COUNT_DROP,
                is_anomaly=True,
                severity=DQSeverity.HIGH if drop_percent >= 75 else DQSeverity.WARNING,
                observed_value=Decimal(current_count),
                expected_value=Decimal(previous_count),
                message=f"Row count dropped {drop_percent:.1f}% (from {previous_count} to {current_count})",
                merchant_message=(
                    f"We noticed a significant drop in data volume for {connector_name}. "
                    "This may indicate a sync issue."
                ),
                support_details=(
                    f"Row count dropped {drop_percent:.1f}% for {connector_name} ({connector_id}). "
                    f"Previous: {previous_count}, Current: {current_count}. "
                    "Investigate potential data loss or API changes."
                ),
                metadata={"drop_percent": drop_percent},
            )

        return AnomalyCheckResult(
            connector_id=connector_id,
            connector_name=connector_name,
            check_type=DQCheckType.ROW_COUNT_DROP,
            is_anomaly=False,
            severity=DQSeverity.WARNING,
            observed_value=Decimal(current_count),
            expected_value=Decimal(previous_count),
            message="Row count within normal range",
            merchant_message="",
            support_details="",
        )

    def check_zero_spend(
        self,
        connector_id: str,
        current_spend: Decimal,
        previous_spend: Decimal,
    ) -> AnomalyCheckResult:
        """
        Check for zero spend anomaly (spend = 0 when previously non-zero).
        """
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == connector_id,
        ).first()

        connector_name = connector.connection_name if connector else "Unknown"

        if previous_spend > 0 and current_spend == 0:
            return AnomalyCheckResult(
                connector_id=connector_id,
                connector_name=connector_name,
                check_type=DQCheckType.ZERO_SPEND,
                is_anomaly=True,
                severity=DQSeverity.HIGH,
                observed_value=current_spend,
                expected_value=previous_spend,
                message="Spend dropped to zero from non-zero value",
                merchant_message=(
                    f"Your ad spend for {connector_name} is showing as zero. "
                    "This may indicate a connection issue with your ad platform."
                ),
                support_details=(
                    f"Zero spend detected for {connector_name} ({connector_id}). "
                    f"Previous spend: {previous_spend}. Check ad account status and API permissions."
                ),
            )

        return AnomalyCheckResult(
            connector_id=connector_id,
            connector_name=connector_name,
            check_type=DQCheckType.ZERO_SPEND,
            is_anomaly=False,
            severity=DQSeverity.WARNING,
            observed_value=current_spend,
            expected_value=previous_spend,
            message="Spend is normal",
            merchant_message="",
            support_details="",
        )

    def check_zero_orders(
        self,
        connector_id: str,
        current_orders: int,
        previous_orders: int,
    ) -> AnomalyCheckResult:
        """
        Check for zero orders anomaly (orders = 0 when previously non-zero).
        """
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == connector_id,
        ).first()

        connector_name = connector.connection_name if connector else "Unknown"

        if previous_orders > 0 and current_orders == 0:
            return AnomalyCheckResult(
                connector_id=connector_id,
                connector_name=connector_name,
                check_type=DQCheckType.ZERO_ORDERS,
                is_anomaly=True,
                severity=DQSeverity.CRITICAL,
                observed_value=Decimal(current_orders),
                expected_value=Decimal(previous_orders),
                message="Orders dropped to zero from non-zero value",
                merchant_message=(
                    "No orders detected. This may indicate a sync issue with Shopify."
                ),
                support_details=(
                    f"Zero orders detected for {connector_name} ({connector_id}). "
                    f"Previous orders: {previous_orders}. Check Shopify connection."
                ),
            )

        return AnomalyCheckResult(
            connector_id=connector_id,
            connector_name=connector_name,
            check_type=DQCheckType.ZERO_ORDERS,
            is_anomaly=False,
            severity=DQSeverity.WARNING,
            observed_value=Decimal(current_orders),
            expected_value=Decimal(previous_orders),
            message="Orders count is normal",
            merchant_message="",
            support_details="",
        )

    def check_missing_days(
        self,
        connector_id: str,
        dates_present: List[date],
        expected_dates: List[date],
    ) -> AnomalyCheckResult:
        """
        Check for missing days in time series data.
        """
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == connector_id,
        ).first()

        connector_name = connector.connection_name if connector else "Unknown"

        dates_set = set(dates_present)
        expected_set = set(expected_dates)
        missing_dates = expected_set - dates_set

        if missing_dates:
            missing_list = sorted(missing_dates)
            return AnomalyCheckResult(
                connector_id=connector_id,
                connector_name=connector_name,
                check_type=DQCheckType.MISSING_DAYS,
                is_anomaly=True,
                severity=DQSeverity.HIGH if len(missing_dates) > 3 else DQSeverity.WARNING,
                observed_value=Decimal(len(dates_present)),
                expected_value=Decimal(len(expected_dates)),
                message=f"Missing {len(missing_dates)} days in time series",
                merchant_message=(
                    f"Some days are missing from your {connector_name} data. Reports may be incomplete."
                ),
                support_details=(
                    f"Missing {len(missing_dates)} days for {connector_name} ({connector_id}): "
                    f"{', '.join(d.isoformat() for d in missing_list[:10])}"
                    f"{' ...' if len(missing_list) > 10 else ''}"
                ),
                metadata={"missing_dates": [d.isoformat() for d in missing_list]},
            )

        return AnomalyCheckResult(
            connector_id=connector_id,
            connector_name=connector_name,
            check_type=DQCheckType.MISSING_DAYS,
            is_anomaly=False,
            severity=DQSeverity.WARNING,
            observed_value=Decimal(len(dates_present)),
            expected_value=Decimal(len(expected_dates)),
            message="All expected days present",
            merchant_message="",
            support_details="",
        )

    def check_negative_values(
        self,
        connector_id: str,
        field_name: str,
        negative_count: int,
        total_count: int,
    ) -> AnomalyCheckResult:
        """
        Check for negative values in fields that should be positive.
        """
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == connector_id,
        ).first()

        connector_name = connector.connection_name if connector else "Unknown"

        if negative_count > 0:
            return AnomalyCheckResult(
                connector_id=connector_id,
                connector_name=connector_name,
                check_type=DQCheckType.NEGATIVE_VALUES,
                is_anomaly=True,
                severity=DQSeverity.HIGH,
                observed_value=Decimal(negative_count),
                expected_value=Decimal(0),
                message=f"Found {negative_count} negative values in {field_name}",
                merchant_message=(
                    f"Unexpected negative values detected in your {connector_name} data."
                ),
                support_details=(
                    f"Found {negative_count}/{total_count} negative values in {field_name} "
                    f"for {connector_name} ({connector_id}). Investigate data quality."
                ),
                metadata={"field_name": field_name, "negative_count": negative_count},
            )

        return AnomalyCheckResult(
            connector_id=connector_id,
            connector_name=connector_name,
            check_type=DQCheckType.NEGATIVE_VALUES,
            is_anomaly=False,
            severity=DQSeverity.WARNING,
            observed_value=Decimal(negative_count),
            expected_value=Decimal(0),
            message="No negative values found",
            merchant_message="",
            support_details="",
        )

    def check_duplicate_primary_keys(
        self,
        connector_id: str,
        duplicate_count: int,
        total_count: int,
    ) -> AnomalyCheckResult:
        """
        Check for duplicate primary keys in data.
        """
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == connector_id,
        ).first()

        connector_name = connector.connection_name if connector else "Unknown"

        if duplicate_count > 0:
            return AnomalyCheckResult(
                connector_id=connector_id,
                connector_name=connector_name,
                check_type=DQCheckType.DUPLICATE_PRIMARY_KEY,
                is_anomaly=True,
                severity=DQSeverity.HIGH,
                observed_value=Decimal(duplicate_count),
                expected_value=Decimal(0),
                message=f"Found {duplicate_count} duplicate primary keys",
                merchant_message=(
                    f"Duplicate records detected in your {connector_name} data. "
                    "This may cause inaccurate reporting."
                ),
                support_details=(
                    f"Found {duplicate_count} duplicate primary keys for "
                    f"{connector_name} ({connector_id}). Check for sync or transformation issues."
                ),
                metadata={"duplicate_count": duplicate_count, "total_count": total_count},
            )

        return AnomalyCheckResult(
            connector_id=connector_id,
            connector_name=connector_name,
            check_type=DQCheckType.DUPLICATE_PRIMARY_KEY,
            is_anomaly=False,
            severity=DQSeverity.WARNING,
            observed_value=Decimal(duplicate_count),
            expected_value=Decimal(0),
            message="No duplicate primary keys found",
            merchant_message="",
            support_details="",
        )

    def record_result(
        self,
        check: DQCheck,
        connector_id: str,
        run_id: str,
        correlation_id: str,
        status: DQResultStatus,
        severity: Optional[DQSeverity] = None,
        observed_value: Optional[Decimal] = None,
        expected_value: Optional[Decimal] = None,
        threshold_value: Optional[Decimal] = None,
        minutes_since_sync: Optional[int] = None,
        message: str = "",
        merchant_message: str = "",
        support_details: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> DQResult:
        """
        Record a DQ check result to the database.
        """
        result = DQResult(
            check_id=check.id,
            tenant_id=self.tenant_id,
            connector_id=connector_id,
            run_id=run_id,
            correlation_id=correlation_id,
            status=status.value,
            severity=severity.value if severity else None,
            observed_value=observed_value,
            expected_value=expected_value,
            threshold_value=threshold_value,
            minutes_since_sync=minutes_since_sync,
            message=message,
            merchant_message=merchant_message,
            support_details=support_details,
            context_metadata=metadata or {},
        )
        self.db.add(result)
        self.db.commit()

        logger.info(
            "DQ result recorded",
            extra={
                "tenant_id": self.tenant_id,
                "connector_id": connector_id,
                "check_id": check.id,
                "run_id": run_id,
                "status": status.value,
                "severity": severity.value if severity else None,
            }
        )

        return result

    def create_incident(
        self,
        check: DQCheck,
        connector_id: str,
        result_id: str,
        run_id: str,
        correlation_id: str,
        severity: DQSeverity,
        title: str,
        description: str,
        merchant_message: str,
        support_details: str,
        is_blocking: bool = False,
        recommended_actions: Optional[List[str]] = None,
    ) -> DQIncident:
        """
        Create a DQ incident for severe failures.
        """
        incident = DQIncident(
            tenant_id=self.tenant_id,
            connector_id=connector_id,
            check_id=check.id,
            result_id=result_id,
            run_id=run_id,
            correlation_id=correlation_id,
            severity=severity.value,
            status=DQIncidentStatus.OPEN.value,
            is_blocking=is_blocking,
            title=title,
            description=description,
            merchant_message=merchant_message,
            support_details=support_details,
            recommended_actions=recommended_actions or [],
        )
        self.db.add(incident)
        self.db.commit()

        logger.warning(
            "DQ incident created",
            extra={
                "tenant_id": self.tenant_id,
                "connector_id": connector_id,
                "incident_id": incident.id,
                "severity": severity.value,
                "is_blocking": is_blocking,
            }
        )

        return incident

    def resolve_incident(
        self,
        incident_id: str,
        resolved_by: str = "system",
        resolution_notes: str = "",
        auto_resolved: bool = False,
    ) -> Optional[DQIncident]:
        """
        Resolve an open incident.
        """
        incident = self.db.query(DQIncident).filter(
            DQIncident.tenant_id == self.tenant_id,
            DQIncident.id == incident_id,
        ).first()

        if not incident:
            return None

        incident.status = (
            DQIncidentStatus.AUTO_RESOLVED.value if auto_resolved
            else DQIncidentStatus.RESOLVED.value
        )
        incident.resolved_at = datetime.now(timezone.utc)
        incident.resolved_by = resolved_by
        incident.resolution_notes = resolution_notes
        self.db.commit()

        logger.info(
            "DQ incident resolved",
            extra={
                "tenant_id": self.tenant_id,
                "incident_id": incident_id,
                "resolved_by": resolved_by,
                "auto_resolved": auto_resolved,
            }
        )

        return incident

    def get_open_incidents(
        self,
        connector_id: Optional[str] = None,
    ) -> List[DQIncident]:
        """
        Get all open incidents for the tenant.
        """
        query = self.db.query(DQIncident).filter(
            DQIncident.tenant_id == self.tenant_id,
            DQIncident.status.in_([
                DQIncidentStatus.OPEN.value,
                DQIncidentStatus.ACKNOWLEDGED.value,
            ]),
        )

        if connector_id:
            query = query.filter(DQIncident.connector_id == connector_id)

        return query.order_by(DQIncident.opened_at.desc()).all()

    def get_blocking_incidents(self) -> List[DQIncident]:
        """
        Get all blocking incidents for the tenant.
        """
        return self.db.query(DQIncident).filter(
            DQIncident.tenant_id == self.tenant_id,
            DQIncident.is_blocking == True,
            DQIncident.status.in_([
                DQIncidentStatus.OPEN.value,
                DQIncidentStatus.ACKNOWLEDGED.value,
            ]),
        ).all()

    def emit_event(self, event: DQEvent) -> None:
        """
        Queue an event for processing by alert system.
        """
        self._event_queue.append(event)
        logger.info(
            "DQ event emitted",
            extra={
                "tenant_id": self.tenant_id,
                "event_type": event.event_type.value,
                "connector_id": event.connector_id,
                "severity": event.severity.value if event.severity else None,
            }
        )

    def get_queued_events(self) -> List[DQEvent]:
        """
        Get all queued events and clear the queue.
        """
        events = self._event_queue.copy()
        self._event_queue.clear()
        return events

    def get_sync_health_summary(self) -> SyncHealthSummary:
        """
        Get overall sync health summary for the tenant.

        Returns:
            SyncHealthSummary with per-connector health and overall status
        """
        # Get all active connectors
        connectors = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.is_enabled == True,
            TenantAirbyteConnection.status != "deleted",
        ).all()

        # Get open incidents per connector
        open_incidents = self.get_open_incidents()
        incidents_by_connector: Dict[str, List[DQIncident]] = {}
        for incident in open_incidents:
            if incident.connector_id not in incidents_by_connector:
                incidents_by_connector[incident.connector_id] = []
            incidents_by_connector[incident.connector_id].append(incident)

        # Get latest sync runs per connector
        latest_runs_subq = self.db.query(
            SyncRun.connector_id,
            func.max(SyncRun.started_at).label("max_started_at")
        ).filter(
            SyncRun.tenant_id == self.tenant_id,
        ).group_by(SyncRun.connector_id).subquery()

        latest_runs = self.db.query(SyncRun).join(
            latest_runs_subq,
            and_(
                SyncRun.connector_id == latest_runs_subq.c.connector_id,
                SyncRun.started_at == latest_runs_subq.c.max_started_at,
            )
        ).filter(SyncRun.tenant_id == self.tenant_id).all()

        runs_by_connector = {run.connector_id: run for run in latest_runs}

        # Build connector health list
        connector_health_list = []
        healthy_count = 0
        delayed_count = 0
        error_count = 0
        blocking_count = 0

        for connector in connectors:
            freshness_result = self.check_freshness(connector.id)
            connector_incidents = incidents_by_connector.get(connector.id, [])
            latest_run = runs_by_connector.get(connector.id)

            # Determine status
            if freshness_result.severity == DQSeverity.CRITICAL:
                status = "error"
                error_count += 1
            elif freshness_result.severity in [DQSeverity.HIGH, DQSeverity.WARNING]:
                status = "delayed"
                delayed_count += 1
            elif not freshness_result.is_fresh:
                status = "delayed"
                delayed_count += 1
            else:
                status = "healthy"
                healthy_count += 1

            # Check for blocking incidents
            is_blocking = any(inc.is_blocking for inc in connector_incidents)
            if is_blocking:
                blocking_count += 1

            # Determine freshness status
            if freshness_result.minutes_since_sync is None:
                freshness_status = "never_synced"
            elif freshness_result.severity == DQSeverity.CRITICAL:
                freshness_status = "critical"
            elif freshness_result.severity in [DQSeverity.HIGH, DQSeverity.WARNING]:
                freshness_status = "stale"
            else:
                freshness_status = "fresh"

            # Build recommended actions
            recommended_actions = []
            if not freshness_result.is_fresh:
                recommended_actions.append("Retry sync")
                if freshness_result.severity in [DQSeverity.HIGH, DQSeverity.CRITICAL]:
                    recommended_actions.append("Check connector connection")
                    recommended_actions.append("Run backfill if needed")

            connector_health_list.append(ConnectorSyncHealth(
                connector_id=connector.id,
                connector_name=connector.connection_name,
                source_type=connector.source_type,
                status=status,
                freshness_status=freshness_status,
                severity=freshness_result.severity,
                last_sync_at=connector.last_sync_at,
                last_rows_synced=latest_run.rows_synced if latest_run else None,
                minutes_since_sync=freshness_result.minutes_since_sync,
                message=freshness_result.message,
                merchant_message=freshness_result.merchant_message,
                recommended_actions=recommended_actions,
                is_blocking=is_blocking,
                has_open_incidents=len(connector_incidents) > 0,
                open_incident_count=len(connector_incidents),
            ))

        # Calculate overall status
        total = len(connectors)
        if total == 0:
            overall_status = "healthy"
            health_score = 100.0
        else:
            if error_count > 0 or blocking_count > 0:
                overall_status = "critical"
            elif delayed_count > 0:
                overall_status = "degraded"
            else:
                overall_status = "healthy"

            # Calculate health score
            health_score = (healthy_count / total) * 100 if total > 0 else 100.0

        return SyncHealthSummary(
            tenant_id=self.tenant_id,
            total_connectors=total,
            healthy_count=healthy_count,
            delayed_count=delayed_count,
            error_count=error_count,
            blocking_issues=blocking_count,
            overall_status=overall_status,
            health_score=round(health_score, 1),
            connectors=connector_health_list,
            has_blocking_issues=blocking_count > 0,
        )

    def is_dashboard_blocked(self) -> Tuple[bool, List[str]]:
        """
        Check if any dashboards should be blocked due to severe DQ issues.

        Returns:
            Tuple of (is_blocked, list of blocking messages)
        """
        blocking_incidents = self.get_blocking_incidents()

        if not blocking_incidents:
            return False, []

        messages = [
            incident.merchant_message or incident.title
            for incident in blocking_incidents
        ]

        return True, messages

    def get_incident_scope(self, incident: DQIncident) -> str:
        """
        Generate human-readable scope description for an incident.

        Used for incident banner messaging per Story 9.6.

        Args:
            incident: The DQ incident

        Returns:
            Human-readable scope string (e.g., "Meta Ads connector")
        """
        # Try to get connector name
        connector = self.db.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.tenant_id == self.tenant_id,
            TenantAirbyteConnection.id == incident.connector_id,
        ).first()

        if connector:
            return f"{connector.connection_name} connector"

        return "Data pipeline"

    def get_incident_eta(self, incident: DQIncident) -> Optional[str]:
        """
        Estimate resolution time based on incident severity.

        Used for incident banner messaging per Story 9.6.

        Args:
            incident: The DQ incident

        Returns:
            Human-readable ETA string or None
        """
        # Provide ETAs based on severity
        eta_map = {
            "warning": "Expected resolution: 1-2 hours",
            "high": "Expected resolution: 2-4 hours",
            "critical": "Investigating - updates every 30 minutes",
        }
        return eta_map.get(incident.severity)
