# Implementation Plan: Stories 8.6 & 8.7
## AI Safety, Limits, Guardrails, Audit & Rollback

**Created:** 2026-01-28
**Branch:** `claude/plan-ai-safety-ODk0h`

---

## Executive Summary

This plan analyzes the existing codebase infrastructure and identifies gaps in the original prompts for Stories 8.6 (Safety & Guardrails) and 8.7 (Audit & Rollback). The codebase already has strong foundations including feature flags, audit logging, AI guardrails, and rollback orchestration. The additional tasks below complete the implementation requirements.

---

## Part 1: Codebase Analysis — What Already Exists

### Existing Safety Infrastructure

| Component | Location | Status |
|-----------|----------|--------|
| Feature Flags (Kill Switch) | `src/platform/feature_flags.py` | ✅ Exists (`AI_WRITE_BACK` flag) |
| AI Guardrails Framework | `src/governance/ai_guardrails.py` | ✅ Exists (prohibition registry) |
| Audit Log Model | `src/platform/audit.py` | ✅ Exists (append-only) |
| Audit Event Registry | `src/platform/audit_events.py` | ✅ Exists (50+ events) |
| Action Execution Logs | `src/models/action_execution_log.py` | ✅ Exists (immutable factory methods) |
| Rollback Orchestrator | `src/governance/rollback_orchestrator.py` | ✅ Exists (state machine) |
| Billing Entitlements | `src/services/billing_entitlements.py` | ✅ Exists (tier-based limits) |
| Before/After State Capture | `src/services/action_execution_service.py` | ✅ Exists |

### What's Missing (Gaps Identified)

| Gap | Required For | Priority |
|-----|--------------|----------|
| Per-tenant rate limiting service | 8.6 | High |
| Cooldown window tracking | 8.6 | High |
| Max recommendations per run config | 8.6 | Medium |
| Suppressed/blocked action logging | 8.6 | High |
| Rate limit hit metrics | 8.6 | Medium |
| Rollback API endpoints | 8.7 | High |
| Audit query API | 8.7 | High |
| AI-specific audit events | 8.7 | Medium |
| Audit export (compliance) | 8.7 | Medium |
| Correlation ID propagation | 8.7 | High |

---

## Part 2: Story 8.6 — Enhanced Prompt with Additional Tasks

### Original Prompt Analysis

```
TASK: Implement AI safety guardrails.

INCLUDE:
- Rate limits per tenant
- Max recommendations per run
- Cooldown windows
- Kill switch (feature flag)

LOG ALL:
- Suppressed actions
- Blocked actions
- Rate limit hits
```

### Missing Tasks to Add

The original prompt lacks:
1. **Database schema** for rate limit tracking
2. **API integration** with existing guardrails framework
3. **Configuration management** for limits
4. **Circuit breaker pattern** for platform failures
5. **Budget/spend safeguards** for financial protection
6. **Concurrent execution prevention**
7. **Testing requirements**
8. **Monitoring and alerting**

---

### Enhanced Prompt: Story 8.6 — Safety, Limits & Guardrails

```markdown
STORY 8.6 — Safety, Limits & Guardrails

CONTEXT:
AI must never overload systems or surprise users. The codebase already has:
- Feature flags with kill switch capability (src/platform/feature_flags.py)
- AI guardrails framework (src/governance/ai_guardrails.py)
- Billing entitlements with tier limits (src/services/billing_entitlements.py)

TASK:
Implement comprehensive AI safety guardrails building on existing infrastructure.

─────────────────────────────────────────────────────────────────────
SECTION 1: RATE LIMITING SERVICE
─────────────────────────────────────────────────────────────────────

Create: src/services/ai_rate_limiter.py

IMPLEMENT:
- AIRateLimiter class with sliding window algorithm
- Per-tenant rate tracking using Redis or DB
- Configurable limits by billing tier:
  - free: 10 insights/day, 5 recommendations/day, 0 actions
  - growth: 100 insights/day, 50 recommendations/day, 100 actions/month
  - enterprise: 1000 insights/day, 500 recommendations/day, unlimited actions

METHODS:
- check_rate_limit(tenant_id, operation_type) → RateLimitResult
- consume_quota(tenant_id, operation_type, count=1) → bool
- get_remaining_quota(tenant_id, operation_type) → QuotaInfo
- reset_quota(tenant_id, operation_type) → None (admin only)

RETURN TYPES:
@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    reset_at: datetime
    limit: int
    retry_after_seconds: int | None

@dataclass
class QuotaInfo:
    used: int
    limit: int
    reset_at: datetime
    period: str  # "daily" | "monthly"

─────────────────────────────────────────────────────────────────────
SECTION 2: COOLDOWN WINDOWS
─────────────────────────────────────────────────────────────────────

Create: src/services/cooldown_manager.py

PURPOSE:
Prevent rapid consecutive actions on the same entity.

IMPLEMENT:
- CooldownManager class
- Track last action timestamp per (tenant_id, entity_type, entity_id)
- Configurable cooldown periods:
  - budget_change: 1 hour
  - pause_campaign: 4 hours
  - scale_campaign: 2 hours
  - default: 30 minutes

METHODS:
- check_cooldown(tenant_id, entity_type, entity_id, action_type) → CooldownResult
- record_action(tenant_id, entity_type, entity_id, action_type) → None
- clear_cooldown(tenant_id, entity_type, entity_id) → None (admin only)
- get_cooldown_status(tenant_id, entity_type, entity_id) → CooldownStatus

RETURN TYPES:
@dataclass
class CooldownResult:
    allowed: bool
    cooldown_remaining_seconds: int
    last_action_at: datetime | None
    cooldown_expires_at: datetime | None

─────────────────────────────────────────────────────────────────────
SECTION 3: MAX RECOMMENDATIONS PER RUN
─────────────────────────────────────────────────────────────────────

Update: src/services/recommendation_generator_service.py

ADD:
- MAX_RECOMMENDATIONS_PER_RUN config (default: 25)
- MAX_HIGH_PRIORITY_PER_RUN config (default: 5)
- Prioritization logic: high > medium > low
- Truncation with logging when limit exceeded

IMPLEMENT:
def generate_recommendations(tenant_id, insights) -> list[Recommendation]:
    # Generate all candidates
    candidates = self._generate_candidates(insights)

    # Sort by priority and confidence
    sorted_candidates = self._prioritize(candidates)

    # Apply limits
    if len(sorted_candidates) > MAX_RECOMMENDATIONS_PER_RUN:
        self._log_truncation(tenant_id, len(sorted_candidates), MAX_RECOMMENDATIONS_PER_RUN)
        sorted_candidates = sorted_candidates[:MAX_RECOMMENDATIONS_PER_RUN]

    return sorted_candidates

─────────────────────────────────────────────────────────────────────
SECTION 4: KILL SWITCH INTEGRATION
─────────────────────────────────────────────────────────────────────

Update: src/platform/feature_flags.py

EXISTING FLAGS TO USE:
- AI_WRITE_BACK: Master kill switch for all write operations
- AI_AUTOMATION: Kill switch for scheduled/automated actions

ADD NEW FLAGS:
- AI_INSIGHTS_GENERATION: Kill switch for insight generation
- AI_RECOMMENDATIONS_GENERATION: Kill switch for recommendation generation
- AI_ACTION_EXECUTION: Kill switch for action execution specifically

IMPLEMENT GLOBAL KILL SWITCH CHECK:
async def check_ai_safety_gates(tenant_id: str, operation: str) -> SafetyGateResult:
    """Check all safety gates before any AI operation."""

    gates = [
        (FeatureFlag.MAINTENANCE_MODE, "System maintenance"),
        (FeatureFlag.AI_WRITE_BACK, "AI writes disabled"),
    ]

    if operation in ["execute_action", "rollback_action"]:
        gates.append((FeatureFlag.AI_ACTION_EXECUTION, "Action execution disabled"))

    for flag, reason in gates:
        if await is_kill_switch_active(flag):
            return SafetyGateResult(blocked=True, reason=reason, flag=flag.value)

    return SafetyGateResult(blocked=False)

─────────────────────────────────────────────────────────────────────
SECTION 5: BUDGET & SPEND SAFEGUARDS
─────────────────────────────────────────────────────────────────────

Create: src/services/budget_safeguard_service.py

PURPOSE:
Prevent AI from making financially dangerous changes.

IMPLEMENT:
- BudgetSafeguardService class
- Configurable thresholds per tenant (stored in tenant_settings)

CHECKS:
- max_single_budget_change_percent: 50% (default)
- max_daily_spend_increase: $1000 (default)
- require_approval_above: $500 (default)
- block_campaign_pause_above_spend: $10000 (campaigns spending >$10k/day)

METHODS:
- validate_budget_change(tenant_id, current_budget, proposed_budget) → ValidationResult
- validate_spend_change(tenant_id, action_type, estimated_impact) → ValidationResult
- get_safeguard_config(tenant_id) → SafeguardConfig

RETURN TYPE:
@dataclass
class ValidationResult:
    allowed: bool
    requires_approval: bool
    reason: str | None
    threshold_exceeded: str | None
    suggested_limit: float | None

─────────────────────────────────────────────────────────────────────
SECTION 6: CIRCUIT BREAKER FOR PLATFORM APIs
─────────────────────────────────────────────────────────────────────

Create: src/services/circuit_breaker.py

PURPOSE:
Stop hammering external APIs when they're failing.

IMPLEMENT:
- CircuitBreaker class with states: CLOSED, OPEN, HALF_OPEN
- Per-platform tracking (Meta, Google, Shopify)
- Configurable thresholds:
  - failure_threshold: 5 consecutive failures
  - success_threshold: 3 successes to close
  - open_duration: 60 seconds

METHODS:
- record_success(platform: str) → None
- record_failure(platform: str, error: Exception) → None
- is_open(platform: str) → bool
- get_state(platform: str) → CircuitState

INTEGRATION:
Update platform executors (src/services/platform_executors/) to use circuit breaker.

─────────────────────────────────────────────────────────────────────
SECTION 7: CONCURRENT EXECUTION PREVENTION
─────────────────────────────────────────────────────────────────────

NOTE: Partial unique index already exists on ai_actions table.

ENHANCE:
- Add advisory lock before execution: pg_advisory_xact_lock(tenant_id, entity_id)
- Validate no conflicting actions in queued/executing state
- Return clear error if concurrent action detected

IMPLEMENT in ActionExecutionService:
async def validate_no_concurrent_execution(tenant_id, platform, entity_id) -> None:
    """Prevent concurrent actions on same entity."""
    existing = await db.execute(
        select(AIAction).where(
            AIAction.tenant_id == tenant_id,
            AIAction.platform == platform,
            AIAction.target_entity_id == entity_id,
            AIAction.status.in_(['queued', 'executing'])
        )
    )
    if existing.scalar_one_or_none():
        raise ConcurrentActionError(f"Action already in progress for {entity_id}")

─────────────────────────────────────────────────────────────────────
SECTION 8: SAFETY EVENT LOGGING
─────────────────────────────────────────────────────────────────────

Create: src/services/safety_event_logger.py

PURPOSE:
Log all suppressed, blocked, and rate-limited events for observability.

LOG EVENTS:
- action_suppressed: Action prevented by guardrail
- action_blocked: Action blocked by kill switch
- rate_limit_hit: Tenant hit rate limit
- cooldown_enforced: Action delayed by cooldown
- budget_safeguard_triggered: Budget check failed
- circuit_breaker_opened: Platform circuit breaker tripped
- concurrent_action_prevented: Duplicate action blocked

SCHEMA:
Table: ai_safety_events (append-only)
- id: UUID
- tenant_id: String
- event_type: Enum
- operation_type: String (insight, recommendation, action)
- entity_id: String (optional)
- reason: String
- metadata: JSONB
- created_at: Timestamp

SERVICE METHODS:
- log_suppressed_action(tenant_id, action_type, reason, metadata)
- log_blocked_action(tenant_id, action_type, blocked_by, metadata)
- log_rate_limit_hit(tenant_id, operation_type, limit, current_count)
- log_cooldown_enforced(tenant_id, entity_id, cooldown_remaining)
- log_budget_safeguard(tenant_id, action_id, threshold, value)
- log_circuit_breaker(platform, state_change, failure_count)

─────────────────────────────────────────────────────────────────────
SECTION 9: DATABASE MIGRATIONS
─────────────────────────────────────────────────────────────────────

Create: backend/migrations/YYYYMMDD_ai_safety_events.sql

-- Rate limit tracking table
CREATE TABLE ai_rate_limits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    operation_type VARCHAR(50) NOT NULL,
    period_start TIMESTAMP NOT NULL,
    period_type VARCHAR(20) NOT NULL, -- 'daily', 'monthly'
    count INTEGER NOT NULL DEFAULT 0,
    limit_value INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tenant_id, operation_type, period_start)
);

CREATE INDEX ix_rate_limits_tenant_operation ON ai_rate_limits(tenant_id, operation_type);
CREATE INDEX ix_rate_limits_period ON ai_rate_limits(period_start);

-- Cooldown tracking table
CREATE TABLE ai_cooldowns (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(255) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    last_action_at TIMESTAMP NOT NULL,
    cooldown_expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(tenant_id, entity_type, entity_id, action_type)
);

CREATE INDEX ix_cooldowns_tenant_entity ON ai_cooldowns(tenant_id, entity_type, entity_id);
CREATE INDEX ix_cooldowns_expires ON ai_cooldowns(cooldown_expires_at);

-- Safety events log (append-only)
CREATE TABLE ai_safety_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    operation_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(255),
    reason TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    correlation_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_safety_events_tenant ON ai_safety_events(tenant_id);
CREATE INDEX ix_safety_events_type ON ai_safety_events(event_type);
CREATE INDEX ix_safety_events_created ON ai_safety_events(created_at DESC);
CREATE INDEX ix_safety_events_correlation ON ai_safety_events(correlation_id);

-- NO DOWN MIGRATION (append-only schema)

─────────────────────────────────────────────────────────────────────
SECTION 10: API ENDPOINTS
─────────────────────────────────────────────────────────────────────

Create: src/api/routes/safety.py

ENDPOINTS:
GET /api/safety/rate-limits
  - Returns current rate limit status for tenant
  - Response: { insights: QuotaInfo, recommendations: QuotaInfo, actions: QuotaInfo }

GET /api/safety/cooldowns
  - Returns active cooldowns for tenant
  - Query params: entity_type, entity_id (optional)
  - Response: list[CooldownStatus]

GET /api/safety/events
  - Returns safety events for audit/debugging
  - Query params: event_type, start_date, end_date, limit
  - Response: list[SafetyEvent]

GET /api/safety/status
  - Returns overall safety system status
  - Response: { kill_switches: dict, circuit_breakers: dict, rate_limits: dict }

POST /api/admin/safety/reset-cooldown (admin only)
  - Clear cooldown for specific entity
  - Body: { entity_type, entity_id }

POST /api/admin/safety/reset-rate-limit (admin only)
  - Reset rate limit counter
  - Body: { operation_type }

─────────────────────────────────────────────────────────────────────
SECTION 11: CONFIGURATION
─────────────────────────────────────────────────────────────────────

Create: src/config/safety_config.py

@dataclass
class SafetyConfig:
    # Rate limits by tier
    rate_limits: dict[str, dict[str, int]] = field(default_factory=lambda: {
        "free": {"insights_daily": 10, "recommendations_daily": 5, "actions_monthly": 0},
        "growth": {"insights_daily": 100, "recommendations_daily": 50, "actions_monthly": 100},
        "enterprise": {"insights_daily": 1000, "recommendations_daily": 500, "actions_monthly": -1}  # -1 = unlimited
    })

    # Cooldown periods (seconds)
    cooldowns: dict[str, int] = field(default_factory=lambda: {
        "budget_change": 3600,      # 1 hour
        "pause_campaign": 14400,    # 4 hours
        "scale_campaign": 7200,     # 2 hours
        "default": 1800             # 30 minutes
    })

    # Recommendations
    max_recommendations_per_run: int = 25
    max_high_priority_per_run: int = 5

    # Budget safeguards
    max_budget_change_percent: float = 50.0
    max_daily_spend_increase: float = 1000.0
    require_approval_above: float = 500.0

    # Circuit breaker
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_success_threshold: int = 3
    circuit_breaker_open_duration_seconds: int = 60

─────────────────────────────────────────────────────────────────────
SECTION 12: TESTING REQUIREMENTS
─────────────────────────────────────────────────────────────────────

Create tests in: backend/src/tests/

UNIT TESTS (tests/unit/services/):
- test_ai_rate_limiter.py
  - Test sliding window algorithm
  - Test quota consumption and reset
  - Test tier-based limits

- test_cooldown_manager.py
  - Test cooldown enforcement
  - Test expiration handling
  - Test action recording

- test_budget_safeguard_service.py
  - Test budget change validation
  - Test approval thresholds
  - Test safeguard configuration

- test_circuit_breaker.py
  - Test state transitions (CLOSED → OPEN → HALF_OPEN → CLOSED)
  - Test failure/success recording
  - Test per-platform isolation

- test_safety_event_logger.py
  - Test all event types logged correctly
  - Test metadata capture

INTEGRATION TESTS (tests/integration/):
- test_safety_integration.py
  - Test rate limiting across multiple requests
  - Test cooldown with real actions
  - Test kill switch stops execution
  - Test circuit breaker with mock platform failures

REGRESSION TESTS (tests/regression/):
- test_safety_regression.py
  - Ensure rate limits don't leak between tenants
  - Ensure cooldowns are tenant-isolated
  - Ensure safety events have correlation IDs

─────────────────────────────────────────────────────────────────────
SECTION 13: MONITORING & ALERTING
─────────────────────────────────────────────────────────────────────

ADD METRICS:
- ai_rate_limit_hits_total (counter, labels: tenant_id, operation_type)
- ai_cooldown_enforced_total (counter, labels: tenant_id, action_type)
- ai_action_blocked_total (counter, labels: tenant_id, reason)
- ai_circuit_breaker_state (gauge, labels: platform, state)
- ai_budget_safeguard_triggered_total (counter, labels: tenant_id, threshold)

ALERTING RULES:
- Alert if circuit breaker OPEN for >5 minutes
- Alert if rate limit hit rate >10/minute for single tenant
- Alert if kill switch activated
- Alert if budget safeguard triggers >3x in 24 hours

─────────────────────────────────────────────────────────────────────
IMPLEMENTATION ORDER
─────────────────────────────────────────────────────────────────────

1. Database migrations (creates tables)
2. Safety configuration (centralized config)
3. Rate limiter service
4. Cooldown manager service
5. Budget safeguard service
6. Circuit breaker service
7. Safety event logger
8. Kill switch integration
9. API endpoints
10. Update existing services to use safety layer
11. Unit tests
12. Integration tests
13. Monitoring setup
```

---

## Part 3: Story 8.7 — Enhanced Prompt with Additional Tasks

### Original Prompt Analysis

```
TASK: Log all AI lifecycle events.

EVENTS:
- insight_generated
- recommendation_created
- proposal_approved
- action_executed
- action_failed
- rollback_triggered

INCLUDE:
- correlation_id
- user_id
- tenant_id
- timestamps

STORE:
- append-only audit table
```

### Missing Tasks to Add

The original prompt lacks:
1. **Rollback API endpoints** (only mentioned logging, not implementation)
2. **Audit query/search API** (how to retrieve audit data)
3. **Audit export for compliance** (SOC2, GDPR)
4. **Retention policy** implementation
5. **Rollback execution logic** (leveraging existing orchestrator)
6. **Before/after state in audit** (for explainability)
7. **Integration with existing ActionExecutionLog**
8. **Accountability chain** (who triggered what, approval history)

---

### Enhanced Prompt: Story 8.7 — Audit, Rollback & Accountability

```markdown
STORY 8.7 — Audit, Rollback & Accountability

USER STORY:
As a compliance officer
I want a complete audit trail
So that all AI behavior is explainable after the fact

CONTEXT:
The codebase already has:
- AuditLog model with append-only design (src/platform/audit.py)
- AuditAction registry with 50+ events (src/platform/audit_events.py)
- ActionExecutionLog with factory methods (src/models/action_execution_log.py)
- RollbackOrchestrator state machine (src/governance/rollback_orchestrator.py)
- Before/after state capture in ActionExecutionService

TASK:
Complete the audit and rollback system by adding query APIs, rollback
endpoints, and compliance export functionality.

─────────────────────────────────────────────────────────────────────
SECTION 1: AI AUDIT EVENTS
─────────────────────────────────────────────────────────────────────

Update: src/platform/audit_events.py

ADD NEW AI-SPECIFIC EVENTS:
class AuditAction(str, Enum):
    # ... existing events ...

    # AI Insights
    AI_INSIGHT_JOB_STARTED = "ai.insight.job_started"
    AI_INSIGHT_GENERATED = "ai.insight.generated"
    AI_INSIGHT_JOB_COMPLETED = "ai.insight.job_completed"
    AI_INSIGHT_JOB_FAILED = "ai.insight.job_failed"
    AI_INSIGHT_DISMISSED = "ai.insight.dismissed"
    AI_INSIGHT_READ = "ai.insight.read"

    # AI Recommendations
    AI_RECOMMENDATION_JOB_STARTED = "ai.recommendation.job_started"
    AI_RECOMMENDATION_CREATED = "ai.recommendation.created"
    AI_RECOMMENDATION_JOB_COMPLETED = "ai.recommendation.job_completed"
    AI_RECOMMENDATION_JOB_FAILED = "ai.recommendation.job_failed"
    AI_RECOMMENDATION_ACCEPTED = "ai.recommendation.accepted"
    AI_RECOMMENDATION_DISMISSED = "ai.recommendation.dismissed"

    # AI Actions
    AI_ACTION_CREATED = "ai.action.created"
    AI_ACTION_APPROVAL_REQUESTED = "ai.action.approval_requested"
    AI_ACTION_APPROVED = "ai.action.approved"
    AI_ACTION_REJECTED = "ai.action.rejected"
    AI_ACTION_QUEUED = "ai.action.queued"
    AI_ACTION_EXECUTION_STARTED = "ai.action.execution_started"
    AI_ACTION_EXECUTION_SUCCEEDED = "ai.action.execution_succeeded"
    AI_ACTION_EXECUTION_FAILED = "ai.action.execution_failed"
    AI_ACTION_CANCELLED = "ai.action.cancelled"

    # Rollback
    AI_ROLLBACK_REQUESTED = "ai.rollback.requested"
    AI_ROLLBACK_APPROVED = "ai.rollback.approved"
    AI_ROLLBACK_STARTED = "ai.rollback.started"
    AI_ROLLBACK_SUCCEEDED = "ai.rollback.succeeded"
    AI_ROLLBACK_FAILED = "ai.rollback.failed"
    AI_ROLLBACK_CANCELLED = "ai.rollback.cancelled"

    # Safety Events (cross-reference with 8.6)
    AI_SAFETY_RATE_LIMITED = "ai.safety.rate_limited"
    AI_SAFETY_BLOCKED = "ai.safety.blocked"
    AI_SAFETY_COOLDOWN_ENFORCED = "ai.safety.cooldown_enforced"
    AI_SAFETY_BUDGET_SAFEGUARD = "ai.safety.budget_safeguard"

SEVERITY MAPPING:
Add to AUDIT_EVENT_SEVERITY dict:
- AI_ACTION_EXECUTION_FAILED: "high"
- AI_ROLLBACK_FAILED: "critical"
- AI_SAFETY_BLOCKED: "high"
- Others: "medium" or "low"

─────────────────────────────────────────────────────────────────────
SECTION 2: AUDIT LOG ENRICHMENT
─────────────────────────────────────────────────────────────────────

PURPOSE:
Ensure all audit logs contain complete context for explainability.

REQUIRED METADATA for AI events:
{
    "correlation_id": "uuid",
    "tenant_id": "string",
    "user_id": "string | null",  // null for system-triggered
    "triggered_by": "user | system | scheduler",
    "action_id": "uuid",  // for action events
    "insight_id": "uuid",  // for insight events
    "recommendation_id": "uuid",  // for recommendation events
    "platform": "meta | google | shopify",
    "entity_type": "campaign | ad_set | ad",
    "entity_id": "string",
    "before_state": {},  // snapshot before change
    "after_state": {},   // snapshot after change
    "execution_duration_ms": 1234,
    "error_details": {},  // for failures
    "approval_chain": [  // for approved actions
        {"user_id": "...", "role": "...", "approved_at": "..."}
    ]
}

Update: src/services/action_execution_service.py

ENSURE each phase logs to AuditLog:
1. Action created → AI_ACTION_CREATED
2. Approval requested → AI_ACTION_APPROVAL_REQUESTED
3. Approval granted → AI_ACTION_APPROVED (with approver info)
4. Queued for execution → AI_ACTION_QUEUED
5. Execution started → AI_ACTION_EXECUTION_STARTED (with before_state)
6. Execution succeeded → AI_ACTION_EXECUTION_SUCCEEDED (with after_state)
7. Execution failed → AI_ACTION_EXECUTION_FAILED (with error_details)

─────────────────────────────────────────────────────────────────────
SECTION 3: ROLLBACK API ENDPOINTS
─────────────────────────────────────────────────────────────────────

Create: src/api/routes/rollback.py

ENDPOINTS:

POST /api/actions/{action_id}/rollback
  - Initiate rollback for a specific action
  - Requires: can_rollback_actions permission
  - Body: { reason: string, force: bool (default false) }
  - Validations:
    - Action must be in 'succeeded' status
    - Rollback window not expired (default 24 hours)
    - No concurrent rollback in progress
    - before_state must exist
  - Response: { rollback_id: uuid, status: "pending" | "in_progress" }

GET /api/actions/{action_id}/rollback-status
  - Get rollback status for an action
  - Response: {
      rollback_id: uuid,
      status: "pending" | "validating" | "executing" | "succeeded" | "failed",
      started_at: datetime,
      completed_at: datetime | null,
      error: string | null
    }

GET /api/actions/{action_id}/rollback-preview
  - Preview what rollback would do without executing
  - Response: {
      can_rollback: bool,
      reason_if_not: string | null,
      rollback_window_expires_at: datetime,
      before_state: {},
      current_state: {},
      rollback_params: {}
    }

POST /api/actions/{action_id}/rollback/cancel
  - Cancel a pending rollback
  - Only valid if status is "pending"

GET /api/rollbacks
  - List all rollbacks for tenant
  - Query params: status, action_id, start_date, end_date
  - Response: paginated list of rollbacks

─────────────────────────────────────────────────────────────────────
SECTION 4: ROLLBACK SERVICE
─────────────────────────────────────────────────────────────────────

Create: src/services/action_rollback_service.py
(Note: Partial implementation may exist, enhance it)

IMPLEMENT:

class ActionRollbackService:

    async def initiate_rollback(
        self,
        action_id: UUID,
        triggered_by: str,
        reason: str,
        force: bool = False
    ) -> RollbackResult:
        """
        Initiate rollback for a completed action.

        Steps:
        1. Validate action is rollback-eligible
        2. Fetch before_state from action_execution_logs
        3. Fetch current_state from platform
        4. Generate rollback_params using executor
        5. Create rollback record
        6. Queue rollback job
        7. Log AI_ROLLBACK_REQUESTED audit event
        """

    async def execute_rollback(self, rollback_id: UUID) -> ExecutionResult:
        """
        Execute the rollback operation.

        Steps:
        1. Log AI_ROLLBACK_STARTED
        2. Get platform executor
        3. Execute rollback with idempotency key
        4. Capture after_state
        5. Verify rollback succeeded (compare to before_state)
        6. Update action status to 'rolled_back'
        7. Log AI_ROLLBACK_SUCCEEDED or AI_ROLLBACK_FAILED
        """

    async def validate_rollback_eligible(self, action_id: UUID) -> ValidationResult:
        """
        Check if action can be rolled back.

        Checks:
        - Action status is 'succeeded'
        - Rollback window not expired
        - before_state exists
        - No concurrent rollback
        - Platform supports rollback for this action type
        """

    async def preview_rollback(self, action_id: UUID) -> RollbackPreview:
        """
        Generate preview of rollback without executing.
        """

ROLLBACK WINDOW CONFIGURATION:
- Default: 24 hours
- Configurable per action type:
  - budget_change: 48 hours
  - pause_campaign: 72 hours
  - scale_campaign: 24 hours

─────────────────────────────────────────────────────────────────────
SECTION 5: AUDIT QUERY API
─────────────────────────────────────────────────────────────────────

Create: src/api/routes/audit.py

ENDPOINTS:

GET /api/audit/logs
  - Query audit logs with filters
  - Query params:
    - action: string (filter by AuditAction)
    - resource_type: string (action, insight, recommendation)
    - resource_id: uuid
    - user_id: uuid
    - start_date: datetime
    - end_date: datetime
    - severity: string (critical, high, medium, low)
    - correlation_id: string
    - limit: int (default 50, max 500)
    - offset: int
  - Response: {
      total: int,
      logs: list[AuditLogEntry],
      has_more: bool
    }

GET /api/audit/logs/{log_id}
  - Get single audit log entry with full metadata
  - Response: AuditLogEntry with expanded metadata

GET /api/audit/actions/{action_id}/timeline
  - Get complete audit timeline for a specific action
  - Returns all events related to that action in chronological order
  - Response: list[AuditLogEntry]

GET /api/audit/correlation/{correlation_id}
  - Get all events sharing a correlation ID
  - Useful for tracing request chains
  - Response: list[AuditLogEntry]

GET /api/audit/summary
  - Get summary statistics for audit logs
  - Query params: start_date, end_date
  - Response: {
      total_events: int,
      by_action: dict[str, int],
      by_severity: dict[str, int],
      by_resource_type: dict[str, int]
    }

─────────────────────────────────────────────────────────────────────
SECTION 6: COMPLIANCE EXPORT
─────────────────────────────────────────────────────────────────────

Create: src/services/audit_export_service.py

PURPOSE:
Export audit data for compliance reporting (SOC2, GDPR).

IMPLEMENT:

class AuditExportService:

    async def export_to_csv(
        self,
        tenant_id: str,
        filters: AuditFilters,
        include_metadata: bool = True
    ) -> bytes:
        """Export audit logs to CSV format."""

    async def export_to_json(
        self,
        tenant_id: str,
        filters: AuditFilters,
        pretty: bool = False
    ) -> bytes:
        """Export audit logs to JSON format."""

    async def generate_compliance_report(
        self,
        tenant_id: str,
        report_type: str,  # "soc2" | "gdpr" | "custom"
        date_range: tuple[datetime, datetime]
    ) -> ComplianceReport:
        """
        Generate compliance report.

        Includes:
        - Summary of all AI actions taken
        - All data access events
        - All approval events
        - All rollback events
        - Any anomalies or security events
        """

API ENDPOINTS:

POST /api/audit/export
  - Export audit logs
  - Body: {
      format: "csv" | "json",
      filters: AuditFilters,
      include_metadata: bool
    }
  - Response: file download

POST /api/audit/compliance-report
  - Generate compliance report
  - Body: {
      report_type: "soc2" | "gdpr" | "custom",
      start_date: datetime,
      end_date: datetime
    }
  - Response: ComplianceReport

─────────────────────────────────────────────────────────────────────
SECTION 7: RETENTION POLICY
─────────────────────────────────────────────────────────────────────

Create: src/services/audit_retention_service.py

PURPOSE:
Manage audit log retention per compliance requirements.

RETENTION PERIODS:
- AI action events: 2 years (SOC2 requirement)
- Safety events: 1 year
- General audit events: 90 days
- GDPR deletion records: 7 years

IMPLEMENT:

class AuditRetentionService:

    async def archive_old_logs(self, cutoff_date: datetime) -> ArchiveResult:
        """
        Archive logs older than cutoff to cold storage.
        Does NOT delete - moves to archive table.
        """

    async def get_retention_policy(self, event_type: str) -> RetentionPolicy:
        """Get retention policy for event type."""

    async def check_retention_compliance(self, tenant_id: str) -> ComplianceStatus:
        """Check if tenant's audit logs meet retention requirements."""

DATABASE:
Create archive table: audit_logs_archive (same schema as audit_logs)

JOB:
Create scheduled job to run daily:
- Archive logs past retention period
- Generate retention compliance report
- Alert if any compliance issues

─────────────────────────────────────────────────────────────────────
SECTION 8: ACCOUNTABILITY CHAIN
─────────────────────────────────────────────────────────────────────

PURPOSE:
Track complete chain of accountability for every AI action.

CREATE: src/models/accountability_chain.py

@dataclass
class AccountabilityEntry:
    actor_type: str  # "user" | "system" | "scheduler"
    actor_id: str | None
    actor_role: str | None
    action: str
    timestamp: datetime
    metadata: dict

class AccountabilityChain:
    """
    Tracks who did what and when for an AI action.

    Example chain for an action:
    1. system: generated insight (job_id)
    2. system: created recommendation from insight
    3. user: accepted recommendation (user_id, role)
    4. user: approved action for execution (user_id, role)
    5. system: executed action (job_id)
    6. user: triggered rollback (user_id, role)
    """

    entries: list[AccountabilityEntry]

    def add_entry(self, entry: AccountabilityEntry) -> None
    def get_approvers(self) -> list[AccountabilityEntry]
    def get_triggering_user(self) -> AccountabilityEntry | None
    def to_dict(self) -> dict

STORE IN:
action.metadata["accountability_chain"] = chain.to_dict()

AUDIT QUERY:
Add endpoint: GET /api/actions/{action_id}/accountability
Returns the full accountability chain for the action.

─────────────────────────────────────────────────────────────────────
SECTION 9: CORRELATION ID PROPAGATION
─────────────────────────────────────────────────────────────────────

PURPOSE:
Ensure correlation_id flows through entire request lifecycle.

UPDATE: src/platform/middleware.py

class CorrelationIdMiddleware:
    """
    Middleware to propagate correlation_id.

    1. Check for X-Correlation-ID header
    2. If not present, generate new UUID
    3. Store in request.state.correlation_id
    4. Add to response headers
    5. Include in all logging
    """

UPDATE: All services to accept and propagate correlation_id:
- InsightGeneratorService
- RecommendationGeneratorService
- ActionExecutionService
- ActionRollbackService
- AuditLogService

LOGGING:
All log entries must include correlation_id:
logger.info("Action executed", extra={"correlation_id": correlation_id, ...})

─────────────────────────────────────────────────────────────────────
SECTION 10: DATABASE MIGRATIONS
─────────────────────────────────────────────────────────────────────

Create: backend/migrations/YYYYMMDD_audit_enhancements.sql

-- Add rollback tracking table
CREATE TABLE ai_rollbacks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(255) NOT NULL,
    action_id UUID NOT NULL REFERENCES ai_actions(id),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    triggered_by VARCHAR(255) NOT NULL,
    reason TEXT NOT NULL,
    rollback_params JSONB,
    before_state JSONB,
    after_state JSONB,
    error_details JSONB,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX ix_rollbacks_tenant ON ai_rollbacks(tenant_id);
CREATE INDEX ix_rollbacks_action ON ai_rollbacks(action_id);
CREATE INDEX ix_rollbacks_status ON ai_rollbacks(status);
CREATE UNIQUE INDEX ix_rollbacks_active ON ai_rollbacks(action_id)
    WHERE status IN ('pending', 'validating', 'executing');

-- Archive table for old audit logs
CREATE TABLE audit_logs_archive (
    LIKE audit_logs INCLUDING ALL
);

-- Add indexes for audit queries
CREATE INDEX ix_audit_logs_action ON audit_logs(action);
CREATE INDEX ix_audit_logs_resource ON audit_logs(resource_type, resource_id);
CREATE INDEX ix_audit_logs_correlation ON audit_logs(correlation_id);
CREATE INDEX ix_audit_logs_tenant_created ON audit_logs(tenant_id, created_at DESC);

-- NO DOWN MIGRATION (append-only schema)

─────────────────────────────────────────────────────────────────────
SECTION 11: TESTING REQUIREMENTS
─────────────────────────────────────────────────────────────────────

UNIT TESTS (tests/unit/):
- test_audit_events.py
  - All AI events have correct severity
  - Event names follow convention

- test_action_rollback_service.py
  - Rollback validation logic
  - Rollback execution flow
  - Error handling

- test_audit_export_service.py
  - CSV export format
  - JSON export format
  - Compliance report generation

- test_accountability_chain.py
  - Entry addition
  - Chain serialization
  - Approver extraction

INTEGRATION TESTS (tests/integration/):
- test_rollback_integration.py
  - Full rollback flow with mock platform
  - Rollback window expiration
  - Concurrent rollback prevention

- test_audit_query_integration.py
  - Query with filters
  - Pagination
  - Timeline generation

- test_correlation_propagation.py
  - Correlation ID flows through services
  - All audit logs have correlation ID

REGRESSION TESTS (tests/regression/):
- test_audit_regression.py
  - Audit logs are append-only (no updates/deletes)
  - All AI actions create audit entries
  - Correlation IDs are unique per request

─────────────────────────────────────────────────────────────────────
SECTION 12: INTEGRATION WITH EXISTING SYSTEMS
─────────────────────────────────────────────────────────────────────

UPDATE EXISTING SERVICES:

1. src/services/insight_generator_service.py
   - Add audit logging for insight generation
   - Propagate correlation_id

2. src/services/recommendation_generator_service.py
   - Add audit logging for recommendation creation
   - Track insight → recommendation linkage

3. src/services/action_execution_service.py
   - Enhance audit logging with full metadata
   - Build accountability chain during execution

4. src/jobs/action_job_worker.py
   - Pass correlation_id to all operations
   - Log job-level events to audit

5. src/governance/rollback_orchestrator.py
   - Connect to new ActionRollbackService
   - Add audit logging for state transitions

─────────────────────────────────────────────────────────────────────
IMPLEMENTATION ORDER
─────────────────────────────────────────────────────────────────────

1. Database migrations
2. AI audit events registration
3. Correlation ID middleware
4. Audit log enrichment
5. Accountability chain model
6. Action rollback service
7. Audit query service
8. Rollback API endpoints
9. Audit API endpoints
10. Audit export service
11. Retention service
12. Update existing services
13. Unit tests
14. Integration tests
15. Regression tests
```

---

## Part 4: Summary of Additional Tasks

### Story 8.6 — Added Tasks (Beyond Original Prompt)

| # | Task | Why It's Needed |
|---|------|-----------------|
| 1 | Database migrations for rate limits, cooldowns, safety events | Original had no schema |
| 2 | Sliding window rate limiting algorithm | Implementation detail |
| 3 | Cooldown manager service | Original was vague |
| 4 | Budget safeguard service | Financial protection missing |
| 5 | Circuit breaker for platform APIs | Prevent cascade failures |
| 6 | Concurrent execution prevention | Data integrity |
| 7 | Safety event logging service | Structured logging |
| 8 | API endpoints for safety status | Observability |
| 9 | Configuration management | Centralized limits |
| 10 | Unit/integration/regression tests | Quality assurance |
| 11 | Monitoring metrics and alerts | Production readiness |

### Story 8.7 — Added Tasks (Beyond Original Prompt)

| # | Task | Why It's Needed |
|---|------|-----------------|
| 1 | Rollback API endpoints | Original only mentioned logging |
| 2 | Rollback service implementation | Execution logic |
| 3 | Rollback preview endpoint | User safety |
| 4 | Audit query API | Retrieving audit data |
| 5 | Correlation ID middleware | Request tracing |
| 6 | Accountability chain model | Complete audit trail |
| 7 | Compliance export (CSV/JSON) | SOC2/GDPR requirements |
| 8 | Retention policy service | Compliance |
| 9 | Database migrations | Schema for rollbacks |
| 10 | Integration with existing services | Connect to codebase |
| 11 | Unit/integration/regression tests | Quality assurance |

---

## Part 5: Dependencies Between Stories

```
Story 8.6 (Safety)              Story 8.7 (Audit)
─────────────────              ─────────────────

Rate Limiter ──────────────────► Audit: AI_SAFETY_RATE_LIMITED
Cooldown Manager ──────────────► Audit: AI_SAFETY_COOLDOWN_ENFORCED
Kill Switch ───────────────────► Audit: AI_SAFETY_BLOCKED
Budget Safeguard ──────────────► Audit: AI_SAFETY_BUDGET_SAFEGUARD

                    ┌──────────────────────────┐
                    │  Both stories share:     │
                    │  - Correlation ID        │
                    │  - Tenant isolation      │
                    │  - Append-only logging   │
                    │  - Feature flags         │
                    └──────────────────────────┘
```

**Recommended Implementation Order:**
1. Story 8.6 first (safety gates must exist before rollback)
2. Story 8.7 second (rollback needs safety checks)
3. Final integration testing together

---

## Part 6: File Inventory

### New Files to Create

**Story 8.6:**
- `backend/migrations/YYYYMMDD_ai_safety_events.sql`
- `backend/src/services/ai_rate_limiter.py`
- `backend/src/services/cooldown_manager.py`
- `backend/src/services/budget_safeguard_service.py`
- `backend/src/services/circuit_breaker.py`
- `backend/src/services/safety_event_logger.py`
- `backend/src/config/safety_config.py`
- `backend/src/api/routes/safety.py`
- `backend/src/tests/unit/services/test_ai_rate_limiter.py`
- `backend/src/tests/unit/services/test_cooldown_manager.py`
- `backend/src/tests/unit/services/test_budget_safeguard_service.py`
- `backend/src/tests/unit/services/test_circuit_breaker.py`
- `backend/src/tests/integration/test_safety_integration.py`
- `backend/src/tests/regression/test_safety_regression.py`

**Story 8.7:**
- `backend/migrations/YYYYMMDD_audit_enhancements.sql`
- `backend/src/services/action_rollback_service.py` (enhance if exists)
- `backend/src/services/audit_export_service.py`
- `backend/src/services/audit_retention_service.py`
- `backend/src/models/accountability_chain.py`
- `backend/src/api/routes/rollback.py`
- `backend/src/api/routes/audit.py`
- `backend/src/tests/unit/services/test_action_rollback_service.py`
- `backend/src/tests/unit/services/test_audit_export_service.py`
- `backend/src/tests/integration/test_rollback_integration.py`
- `backend/src/tests/integration/test_audit_query_integration.py`
- `backend/src/tests/regression/test_audit_regression.py`

### Existing Files to Update

- `backend/src/platform/feature_flags.py` — Add new AI flags
- `backend/src/platform/audit_events.py` — Add AI events
- `backend/src/platform/middleware.py` — Add correlation ID middleware
- `backend/src/services/recommendation_generator_service.py` — Add limits
- `backend/src/services/action_execution_service.py` — Add safety checks
- `backend/src/services/platform_executors/*.py` — Add circuit breaker
- `backend/src/governance/rollback_orchestrator.py` — Connect to service
