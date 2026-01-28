"""
Database models for billing, subscriptions, and entitlements.

All models follow strict tenant isolation patterns.
Tenant-scoped models inherit from TenantScopedMixin.
"""

from src.models.base import TimestampMixin, TenantScopedMixin
from src.models.store import ShopifyStore
from src.models.plan import Plan, PlanFeature
from src.models.subscription import Subscription
from src.models.usage import UsageRecord, UsageAggregate
from src.models.billing_event import BillingEvent
from src.models.airbyte_connection import TenantAirbyteConnection, ConnectionStatus, ConnectionType
from src.models.backfill import BackfillExecution, BackfillStatus
from src.models.dq_models import (
    DQCheck, DQResult, DQIncident, SyncRun, BackfillJob,
    DQCheckType, DQSeverity, DQResultStatus, DQIncidentStatus,
    SyncRunStatus, ConnectorSourceType, BackfillJobStatus,
    FRESHNESS_THRESHOLDS, get_freshness_threshold, is_critical_source,
    MAX_MERCHANT_BACKFILL_DAYS,
)
from src.models.ai_insight import AIInsight, InsightType, InsightSeverity
from src.models.insight_job import InsightJob, InsightJobStatus, InsightJobCadence

__all__ = [
    "TimestampMixin",
    "TenantScopedMixin",
    "ShopifyStore",
    "Plan",
    "PlanFeature",
    "Subscription",
    "UsageRecord",
    "UsageAggregate",
    "BillingEvent",
    "TenantAirbyteConnection",
    "ConnectionStatus",
    "ConnectionType",
    "BackfillExecution",
    "BackfillStatus",
    # Data Quality models
    "DQCheck",
    "DQResult",
    "DQIncident",
    "SyncRun",
    "BackfillJob",
    "DQCheckType",
    "DQSeverity",
    "DQResultStatus",
    "DQIncidentStatus",
    "SyncRunStatus",
    "ConnectorSourceType",
    "BackfillJobStatus",
    "FRESHNESS_THRESHOLDS",
    "get_freshness_threshold",
    "is_critical_source",
    "MAX_MERCHANT_BACKFILL_DAYS",
    # AI Insight models
    "AIInsight",
    "InsightType",
    "InsightSeverity",
    "InsightJob",
    "InsightJobStatus",
    "InsightJobCadence",
]
