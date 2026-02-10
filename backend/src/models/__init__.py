"""
Database models for billing, subscriptions, and entitlements.

All models follow strict tenant isolation patterns.
Tenant-scoped models inherit from TenantScopedMixin.
"""

from src.models.base import TimestampMixin, TenantScopedMixin
# Identity models (Epic 1.1)
from src.models.organization import Organization
from src.models.tenant import Tenant, TenantStatus
from src.models.user import User
from src.models.user_tenant_roles import UserTenantRole
# RBAC models (Story 5.5.1)
from src.models.role import Role, RolePermission
from src.models.user_role_assignment import UserRoleAssignment
# Agency access models (Story 5.5.2)
from src.models.agency_access_request import AgencyAccessRequest, AgencyAccessRequestStatus
# Access revocation models (Story 5.5.4)
from src.models.access_revocation import AccessRevocation, RevocationStatus
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
from src.models.ai_recommendation import (
    AIRecommendation,
    RecommendationType,
    RecommendationPriority,
    EstimatedImpact,
    RiskLevel,
    AffectedEntityType,
)
from src.models.recommendation_job import (
    RecommendationJob,
    RecommendationJobStatus,
    RecommendationJobCadence,
)
from src.models.action_proposal import (
    ActionProposal,
    ActionType,
    ActionStatus,
    TargetPlatform,
    TargetEntityType,
    MAX_SCOPE_RULES,
    DEFAULT_PROPOSAL_TTL_DAYS,
)
from src.models.action_approval_audit import (
    ActionApprovalAudit,
    AuditAction,
)
from src.models.action_proposal_job import (
    ActionProposalJob,
    ActionProposalJobStatus,
    ActionProposalJobCadence,
)
from src.models.notification import (
    Notification,
    NotificationEventType,
    NotificationImportance,
    NotificationStatus,
    EVENT_IMPORTANCE_MAP,
)
from src.models.notification_preference import NotificationPreference
from src.models.llm_routing import (
    LLMModelRegistry,
    LLMOrgConfig,
    LLMPromptTemplate,
    LLMUsageLog,
    LLMResponseStatus,
)
from src.models.changelog_entry import (
    ChangelogEntry,
    ReleaseType,
    FEATURE_AREAS,
)
from src.models.changelog_read_status import ChangelogReadStatus
from src.models.data_change_event import (
    DataChangeEvent,
    DataChangeEventType,
    AFFECTED_METRICS,
)
from src.models.dashboard_metric_binding import DashboardMetricBinding
# Custom Reports & Dashboard Builder models
from src.models.report_template import ReportTemplate, TemplateCategory
from src.models.custom_dashboard import CustomDashboard, DashboardStatus
from src.models.custom_report import CustomReport, ChartType, CHART_MIN_DIMENSIONS
from src.models.dashboard_version import DashboardVersion, MAX_DASHBOARD_VERSIONS
from src.models.dashboard_share import DashboardShare, SharePermission
from src.models.dashboard_audit import DashboardAudit, DashboardAuditAction
from src.models.data_availability import (
    DataAvailability,
    AvailabilityState,
    AvailabilityReason,
)
from src.models.dataset_version import (
    DatasetVersion,
    DatasetVersionStatus,
)
from src.models.dataset_metrics import (
    DatasetMetrics,
    DatasetSyncStatus,
)
from src.models.explore_guardrail_exception import (
    ExploreGuardrailException,
    GuardrailExceptionStatus,
)
from src.models.report_template import (
    ReportTemplate,
    TemplateCategory,
)
try:
    from .merchant_data_health import (
        MerchantHealthState,
        MerchantDataHealthResponse,
    )
except ModuleNotFoundError:
    # Fallback: ensure backend/src is on sys.path when running in CI
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from .merchant_data_health import (
        MerchantHealthState,
        MerchantDataHealthResponse,
    )

__all__ = [
    "TimestampMixin",
    "TenantScopedMixin",
    # Identity models (Epic 1.1)
    "Organization",
    "Tenant",
    "TenantStatus",
    "User",
    "UserTenantRole",
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
    # AI Recommendation models
    "AIRecommendation",
    "RecommendationType",
    "RecommendationPriority",
    "EstimatedImpact",
    "RiskLevel",
    "AffectedEntityType",
    "RecommendationJob",
    "RecommendationJobStatus",
    "RecommendationJobCadence",
    # AI Action models (Story 8.5)
    "AIAction",
    "ActionType",
    "ActionStatus",
    "ActionTargetEntityType",
    "ActionExecutionLog",
    "ActionLogEventType",
    "ActionJob",
    "ActionJobStatus",
    # Action Proposal models (Story 8.4)
    "ActionProposal",
    "ActionType",
    "ActionStatus",
    "TargetPlatform",
    "TargetEntityType",
    "MAX_SCOPE_RULES",
    "DEFAULT_PROPOSAL_TTL_DAYS",
    "ActionApprovalAudit",
    "AuditAction",
    "ActionProposalJob",
    "ActionProposalJobStatus",
    "ActionProposalJobCadence",
    # Notification models (Story 9.1)
    "Notification",
    "NotificationEventType",
    "NotificationImportance",
    "NotificationStatus",
    "EVENT_IMPORTANCE_MAP",
    "NotificationPreference",
    # LLM Routing models (Story 8.8)
    "LLMModelRegistry",
    "LLMOrgConfig",
    "LLMPromptTemplate",
    "LLMUsageLog",
    "LLMResponseStatus",
    # Changelog models (Story 9.7)
    "ChangelogEntry",
    "ReleaseType",
    "FEATURE_AREAS",
    "ChangelogReadStatus",
    # Data Change Event models (Story 9.8)
    "DataChangeEvent",
    "DataChangeEventType",
    "AFFECTED_METRICS",
    # Dashboard Metric Binding models (Story 2.3)
    "DashboardMetricBinding",
    # Data Availability state machine
    "DataAvailability",
    "AvailabilityState",
    "AvailabilityReason",
    # Merchant Data Health (Story 4.3)
    "MerchantHealthState",
    "MerchantDataHealthResponse",
    # Dataset Versioning & Observability (Story 5.2)
    "DatasetVersion",
    "DatasetVersionStatus",
    "DatasetMetrics",
    "DatasetSyncStatus",
    "ExploreGuardrailException",
    "GuardrailExceptionStatus",
    # Report Template models (Phase 2C)
    "ReportTemplate",
    "TemplateCategory",
    # RBAC models (Story 5.5.1)
    "Role",
    "RolePermission",
    "UserRoleAssignment",
    # Agency access models (Story 5.5.2)
    "AgencyAccessRequest",
    "AgencyAccessRequestStatus",
    # Access revocation models (Story 5.5.4)
    "AccessRevocation",
    "RevocationStatus",
    # Custom Reports & Dashboard Builder models
    "ReportTemplate",
    "TemplateCategory",
    "CustomDashboard",
    "DashboardStatus",
    "CustomReport",
    "ChartType",
    "CHART_MIN_DIMENSIONS",
    "DashboardVersion",
    "MAX_DASHBOARD_VERSIONS",
    "DashboardShare",
    "SharePermission",
    "DashboardAudit",
    "DashboardAuditAction",
]
