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
from src.models.data_availability import (
    DataAvailability,
    AvailabilityState,
    AvailabilityReason,
)
# region agent log
# Debug instrumentation for module resolution (Debug Mode)
# Hypotheses:
# A) backend/src is missing from sys.path during regression runs
# B) merchant_data_health.py not visible at runtime
# C) working directory impacts resolution
try:
    import json
    import os
    import sys
    import time

    # Derive repo root for CI environments; ensure directories exist
    from pathlib import Path

    # Try multiple candidate roots; ensure directories exist.
    _payload_base = {
        "sessionId": "debug-session",
        "runId": "baseline",
        "timestamp": int(time.time() * 1000),
    }
    _parents = list(Path(__file__).resolve().parents)
    _log_paths = []
    # Relative to repo roots (common CI layouts)
    if len(_parents) >= 3:
        _log_paths.append(_parents[2] / ".cursor" / "debug.log")
    if len(_parents) >= 4:
        _log_paths.append(_parents[3] / ".cursor" / "debug.log")
    if len(_parents) >= 5:
        _log_paths.append(_parents[4] / ".cursor" / "debug.log")
    # Project root candidates in CI
    _log_paths.append(Path("/tmp/shopify_analytics_debug.log"))
    _log_paths.append(Path("/opt/hostedtoolcache/tmp/shopify_analytics_debug.log"))
    _log_paths.append(Path("/home/runner/work/Shopify-analytics-app/Shopify-analytics-app/.cursor/debug.log"))
    _log_paths.append(Path("/home/runner/work/Shopify-analytics-app/.cursor/debug.log"))
    _log_paths.append(Path("/home/runner/.cursor/debug.log"))
    # Local fallback
    _log_paths.append(Path(__file__).resolve().parent / ".cursor" / "debug.log")

    def _write_log(payload: dict):
        for _path in _log_paths:
            try:
                _path.parent.mkdir(parents=True, exist_ok=True)
                with open(_path, "a", encoding="utf-8") as _f:
                    _f.write(json.dumps(payload) + "\n")
                return f"file:{_path}"
            except Exception:
                continue
        # HTTP fallback (best-effort)
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://127.0.0.1:7242/ingest/c1515561-3278-4fa4-b574-7082f5f827eb",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
            return "http:fallback"
        except Exception:
            return "none"

    # Emit logs
    _write_log({**_payload_base,
                "hypothesisId": "A",
                "location": "src/models/__init__.py:agent-log-1",
                "message": "sys.path snapshot",
                "data": {"sys_path": sys.path, "cwd": os.getcwd(), "__file__": __file__}})
    _write_log({**_payload_base,
                "hypothesisId": "B",
                "location": "src/models/__init__.py:agent-log-2",
                "message": "merchant_data_health existence",
                "data": {
                    "file_exists": os.path.exists(os.path.join(os.path.dirname(__file__), "merchant_data_health.py")),
                    "file_dir": os.path.dirname(__file__),
                }})
    _write_log({**_payload_base,
                "hypothesisId": "C",
                "location": "src/models/__init__.py:agent-log-3",
                "message": "__file__ resolution",
                "data": {
                    "init_file": __file__,
                    "dir_contents_sample": sorted(os.listdir(os.path.dirname(__file__)))[:10],
                }})
    _now = int(time.time() * 1000)
    _entries = [
        {
            "sessionId": "debug-session",
            "runId": "baseline",
            "hypothesisId": "A",
            "location": "src/models/__init__.py:agent-log-1",
            "message": "sys.path snapshot",
            "data": {"sys_path": sys.path, "cwd": os.getcwd()},
            "timestamp": _now,
        },
        {
            "sessionId": "debug-session",
            "runId": "baseline",
            "hypothesisId": "B",
            "location": "src/models/__init__.py:agent-log-2",
            "message": "merchant_data_health existence",
            "data": {
                "file_exists": os.path.exists(os.path.join(os.path.dirname(__file__), "merchant_data_health.py")),
                "file_dir": os.path.dirname(__file__),
            },
            "timestamp": _now + 1,
        },
        {
            "sessionId": "debug-session",
            "runId": "baseline",
            "hypothesisId": "C",
            "location": "src/models/__init__.py:agent-log-3",
            "message": "__file__ resolution",
            "data": {
                "init_file": __file__,
                "dir_contents_sample": sorted(os.listdir(os.path.dirname(__file__)))[:10],
            },
            "timestamp": _now + 2,
        },
    ]
    with open(_log_path, "a", encoding="utf-8") as _f:
        for _e in _entries:
            _f.write(json.dumps(_e) + "\n")
except Exception:
    # Do not break imports during debugging
    pass
# endregion

# region agent log helper (Debug Mode - HTTP first, local fallback)
try:
    import json
    import os
    import sys
    import time
    from pathlib import Path
    import urllib.request

    def _agent_log_models_http(payload: dict):
        """Send debug log to HTTP endpoint first; fallback to local debug.log."""
        # HTTP first
        try:
            req = urllib.request.Request(
                "http://127.0.0.1:7242/ingest/c1515561-3278-4fa4-b574-7082f5f827eb",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=2)
            return
        except Exception:
            pass
        # Local fallback (module directory)
        try:
            local_path = Path(__file__).resolve().parent / "debug.log"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            with open(local_path, "a", encoding="utf-8") as _f:
                _f.write(json.dumps(payload) + "\n")
        except Exception:
            pass

    # Emit baseline logs
    _agent_log_models_http({
        "sessionId": "debug-session",
        "runId": "baseline",
        "hypothesisId": "A",
        "location": "src/models/__init__.py:agent-log-HTTP-1",
        "message": "sys.path snapshot",
        "data": {"sys_path": sys.path, "cwd": os.getcwd(), "__file__": __file__},
        "timestamp": int(time.time() * 1000),
    })
    _agent_log_models_http({
        "sessionId": "debug-session",
        "runId": "baseline",
        "hypothesisId": "B",
        "location": "src/models/__init__.py:agent-log-HTTP-2",
        "message": "merchant_data_health existence",
        "data": {
            "file_exists": os.path.exists(os.path.join(os.path.dirname(__file__), "merchant_data_health.py")),
            "file_dir": os.path.dirname(__file__),
        },
        "timestamp": int(time.time() * 1000) + 1,
    })
except Exception:
    pass
# endregion

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
]
