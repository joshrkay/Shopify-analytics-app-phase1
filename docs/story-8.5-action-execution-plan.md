# Story 8.5 — Action Execution (Scoped & Reversible)

## Implementation Plan

**Date:** 2026-01-28
**Story:** 8.5 - Action Execution
**Status:** Planning

---

## 1. Context & Overview

Story 8.5 builds on the foundation of Stories 8.1 (Insights) and 8.3 (Recommendations) to enable **actual execution** of approved actions via external platform APIs.

### Key Differences from Previous Stories

| Aspect | 8.1 Insights | 8.3 Recommendations | 8.5 Actions |
|--------|--------------|---------------------|-------------|
| Data Flow | Read-only | Advisory-only | **Read-Write** |
| External APIs | None | None | **Meta, Google, Shopify** |
| Side Effects | None | None | **Modifies campaigns** |
| Rollback | N/A | N/A | **Required** |
| Idempotency | Content hash | Content hash | **Idempotency keys** |

### Critical Principles

1. **External platform is source of truth** — Internal state updated only after confirmation
2. **No blind retries** — Failure requires human review or explicit re-approval
3. **Full auditability** — Log request, response, before_state, after_state
4. **Reversibility** — Store rollback instructions for every executed action

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              STORY 8.5 ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────────────┐│
│  │   Frontend   │────▶│   REST API   │────▶│  ActionApprovalService       ││
│  │  (Polaris)   │     │  /actions/*  │     │  - Validate action           ││
│  └──────────────┘     └──────────────┘     │  - Check entitlements        ││
│                                            │  - Create ActionJob (QUEUED) ││
│                                            └──────────────────────────────┘│
│                                                         │                   │
│                                                         ▼                   │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                         ACTION JOB QUEUE                              │  │
│  │  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌─────────┐               │  │
│  │  │ QUEUED  │──▶│ RUNNING │──▶│ SUCCESS │   │ FAILED  │               │  │
│  │  └─────────┘   └─────────┘   └─────────┘   └─────────┘               │  │
│  │                     │             │             │                     │  │
│  │                     │        ┌────┴────┐   ┌────┴────┐               │  │
│  │                     │        │PARTIALLY│   │ROLLBACK │               │  │
│  │                     │        │EXECUTED │   │ PENDING │               │  │
│  │                     │        └─────────┘   └─────────┘               │  │
│  └─────────────────────┼────────────────────────────────────────────────┘  │
│                        │                                                    │
│                        ▼                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    ACTION EXECUTION SERVICE                           │  │
│  │                                                                       │  │
│  │  1. Capture before_state from platform API                           │  │
│  │  2. Generate idempotency_key                                         │  │
│  │  3. Execute via PlatformExecutor                                     │  │
│  │  4. Capture after_state from platform API                            │  │
│  │  5. Store execution_log (request, response, states)                  │  │
│  │  6. Generate rollback_instructions                                   │  │
│  │  7. Update action status based on platform confirmation              │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                        │                                                    │
│                        ▼                                                    │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                    PLATFORM EXECUTORS                                 │  │
│  │                                                                       │  │
│  │  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐          │  │
│  │  │  MetaExecutor  │  │ GoogleExecutor │  │ShopifyExecutor │          │  │
│  │  │                │  │                │  │                │          │  │
│  │  │ - Pause camp.  │  │ - Pause camp.  │  │ - Discount     │          │  │
│  │  │ - Adjust budget│  │ - Adjust budget│  │   adjustments  │          │  │
│  │  │ - Update bid   │  │ - Update bid   │  │ - Product      │          │  │
│  │  │ - Scale        │  │ - Scale        │  │   updates      │          │  │
│  │  └────────────────┘  └────────────────┘  └────────────────┘          │  │
│  │                                                                       │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Database Schema

### 3.1 New Tables Required

#### `ai_actions` — Stores executable actions derived from recommendations

```sql
-- Action execution status (extended lifecycle)
CREATE TYPE action_status AS ENUM (
    'pending_approval',   -- Waiting for user approval
    'approved',           -- User approved, ready for execution
    'queued',            -- In execution queue
    'executing',         -- Currently being executed
    'succeeded',         -- Execution confirmed by platform
    'failed',            -- Execution failed
    'partially_executed', -- Some operations succeeded, some failed
    'rolled_back',       -- Successfully rolled back
    'rollback_failed'    -- Rollback attempted but failed
);

-- Action types (maps to recommendation types + execution specifics)
CREATE TYPE action_type AS ENUM (
    'pause_campaign',
    'resume_campaign',
    'adjust_budget',
    'adjust_bid',
    'update_targeting',
    'update_schedule'
);

CREATE TABLE ai_actions (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,

    -- Link to source recommendation
    recommendation_id VARCHAR(255) NOT NULL REFERENCES ai_recommendations(id),

    -- Action specification
    action_type action_type NOT NULL,
    platform VARCHAR(50) NOT NULL,  -- 'meta', 'google', 'shopify'
    target_entity_id VARCHAR(255) NOT NULL,  -- campaign_id, ad_set_id, etc.
    target_entity_type VARCHAR(50) NOT NULL, -- 'campaign', 'ad_set', 'ad'

    -- Action parameters (JSONB for flexibility)
    action_params JSONB NOT NULL DEFAULT '{}',
    -- Example: {"new_budget": 500.00, "currency": "USD"}
    -- Example: {"status": "PAUSED"}

    -- Status tracking
    status action_status NOT NULL DEFAULT 'pending_approval',

    -- Approval tracking
    approved_by VARCHAR(255),  -- User ID who approved
    approved_at TIMESTAMP WITH TIME ZONE,

    -- Execution tracking
    idempotency_key VARCHAR(255) UNIQUE,  -- For safe retries
    execution_started_at TIMESTAMP WITH TIME ZONE,
    execution_completed_at TIMESTAMP WITH TIME ZONE,

    -- State capture (for audit and rollback)
    before_state JSONB,  -- Platform state before execution
    after_state JSONB,   -- Platform state after execution

    -- Rollback support
    rollback_instructions JSONB,  -- How to reverse this action
    rollback_executed_at TIMESTAMP WITH TIME ZONE,

    -- Error tracking
    error_message TEXT,
    error_code VARCHAR(50),
    retry_count INTEGER DEFAULT 0,

    -- Job reference
    job_id VARCHAR(255),

    -- Metadata
    content_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

#### `action_execution_logs` — Detailed audit trail

```sql
CREATE TYPE log_event_type AS ENUM (
    'created',
    'approved',
    'execution_started',
    'state_captured',
    'api_request_sent',
    'api_response_received',
    'execution_succeeded',
    'execution_failed',
    'rollback_started',
    'rollback_succeeded',
    'rollback_failed'
);

CREATE TABLE action_execution_logs (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    action_id VARCHAR(255) NOT NULL REFERENCES ai_actions(id),

    event_type log_event_type NOT NULL,
    event_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Full audit data
    request_payload JSONB,   -- What we sent to the platform
    response_payload JSONB,  -- What the platform returned

    -- State snapshots
    state_snapshot JSONB,    -- Platform state at this point

    -- Error details if applicable
    error_details JSONB,

    -- Actor tracking
    triggered_by VARCHAR(255),  -- 'system', 'user:<id>', 'worker:<id>'

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

#### `action_jobs` — Job queue for action execution

```sql
CREATE TYPE action_job_status AS ENUM (
    'queued',
    'running',
    'succeeded',
    'failed',
    'partially_succeeded'
);

CREATE TABLE action_jobs (
    job_id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,

    status action_job_status NOT NULL DEFAULT 'queued',

    -- What actions are being processed
    action_ids JSONB NOT NULL DEFAULT '[]',  -- Array of action IDs

    -- Results tracking
    actions_attempted INTEGER DEFAULT 0,
    actions_succeeded INTEGER DEFAULT 0,
    actions_failed INTEGER DEFAULT 0,

    -- Timing
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,

    -- Error summary
    error_summary JSONB,

    -- Metadata
    job_metadata JSONB DEFAULT '{}',

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);
```

### 3.2 Indexes

```sql
-- ai_actions indexes
CREATE INDEX ix_ai_actions_tenant_id ON ai_actions(tenant_id);
CREATE INDEX ix_ai_actions_status ON ai_actions(status);
CREATE INDEX ix_ai_actions_tenant_status ON ai_actions(tenant_id, status);
CREATE INDEX ix_ai_actions_recommendation ON ai_actions(recommendation_id);
CREATE INDEX ix_ai_actions_idempotency ON ai_actions(idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_ai_actions_platform ON ai_actions(platform);

-- Partial unique: only one executing action per target entity
CREATE UNIQUE INDEX ix_ai_actions_executing_unique
    ON ai_actions(tenant_id, platform, target_entity_id)
    WHERE status IN ('queued', 'executing');

-- action_execution_logs indexes
CREATE INDEX ix_action_logs_action_id ON action_execution_logs(action_id);
CREATE INDEX ix_action_logs_tenant_timestamp ON action_execution_logs(tenant_id, event_timestamp DESC);

-- action_jobs indexes
CREATE INDEX ix_action_jobs_tenant_status ON action_jobs(tenant_id, status);
CREATE UNIQUE INDEX ix_action_jobs_active_unique
    ON action_jobs(tenant_id)
    WHERE status IN ('queued', 'running');
```

---

## 4. Service Layer Architecture

### 4.1 New Services Required

```
backend/src/services/
├── action_execution_service.py      # Core execution logic
├── action_job_runner.py             # Job lifecycle management
├── action_job_dispatcher.py         # Job creation & scheduling
├── action_approval_service.py       # Approval workflow
├── action_rollback_service.py       # Rollback execution
└── platform_executors/
    ├── __init__.py
    ├── base_executor.py             # Abstract base class
    ├── meta_executor.py             # Meta Ads API executor
    ├── google_executor.py           # Google Ads API executor
    └── shopify_executor.py          # Shopify API executor
```

### 4.2 ActionExecutionService

```python
class ActionExecutionService:
    """
    Core service for executing approved actions.

    SECURITY:
    - Tenant isolation via tenant_id from JWT only
    - Entitlement checking before execution
    - All external calls logged for audit

    PRINCIPLES:
    - External platform is source of truth
    - No blind retries on failure
    - Full before/after state capture
    """

    def execute_action(self, action_id: str) -> ExecutionResult:
        """
        Execute a single approved action.

        Flow:
        1. Validate action is approved and ready
        2. Generate idempotency_key if not exists
        3. Capture before_state from platform
        4. Execute via platform executor
        5. Capture after_state from platform
        6. Generate rollback_instructions
        7. Update action status
        8. Log all events
        """
        pass

    def capture_platform_state(self, action: AIAction) -> dict:
        """Capture current state from external platform."""
        pass

    def generate_rollback_instructions(
        self,
        action: AIAction,
        before_state: dict
    ) -> dict:
        """Generate instructions to reverse this action."""
        pass
```

### 4.3 Platform Executors (Strategy Pattern)

```python
# base_executor.py
class BasePlatformExecutor(ABC):
    """
    Abstract base class for platform-specific executors.

    Each platform executor handles:
    - API authentication
    - Rate limiting
    - Retry logic (with exponential backoff)
    - State capture
    - Action execution
    """

    @abstractmethod
    async def get_entity_state(
        self,
        entity_id: str,
        entity_type: str
    ) -> dict:
        """Get current state of target entity from platform."""
        pass

    @abstractmethod
    async def execute_action(
        self,
        action_type: ActionType,
        entity_id: str,
        params: dict,
        idempotency_key: str
    ) -> ExecutionResult:
        """Execute action on platform. Returns success/failure with details."""
        pass

    @abstractmethod
    def generate_rollback_params(
        self,
        action_type: ActionType,
        before_state: dict
    ) -> dict:
        """Generate parameters to reverse the action."""
        pass


# meta_executor.py
class MetaAdsExecutor(BasePlatformExecutor):
    """
    Executor for Meta (Facebook) Ads API.

    Supported actions:
    - pause_campaign: Set campaign status to PAUSED
    - resume_campaign: Set campaign status to ACTIVE
    - adjust_budget: Update daily/lifetime budget
    - adjust_bid: Update bid amount/strategy
    """

    API_VERSION = "v18.0"
    BASE_URL = "https://graph.facebook.com"

    async def execute_action(self, ...):
        # Implementation with retry logic
        pass


# google_executor.py
class GoogleAdsExecutor(BasePlatformExecutor):
    """
    Executor for Google Ads API.

    Supported actions:
    - pause_campaign: Set campaign status to PAUSED
    - resume_campaign: Set campaign status to ENABLED
    - adjust_budget: Update campaign budget
    - adjust_bid: Update bidding strategy
    """
    pass
```

---

## 5. REST API Specification

### 5.1 Endpoints

```
POST   /api/actions/approve/{recommendation_id}  # Create action from recommendation
GET    /api/actions                              # List actions with filters
GET    /api/actions/{id}                         # Get action details
POST   /api/actions/{id}/execute                 # Trigger execution (manual)
POST   /api/actions/{id}/rollback                # Trigger rollback
GET    /api/actions/{id}/logs                    # Get execution logs
DELETE /api/actions/{id}                         # Cancel pending action
```

### 5.2 Request/Response Examples

#### POST /api/actions/approve/{recommendation_id}

```json
// Request
{
    "override_params": {  // Optional: override default action params
        "new_budget": 450.00
    }
}

// Response
{
    "id": "act_123",
    "recommendation_id": "rec_456",
    "action_type": "adjust_budget",
    "platform": "meta",
    "target_entity_id": "camp_789",
    "status": "approved",
    "action_params": {
        "new_budget": 450.00,
        "currency": "USD"
    },
    "created_at": "2026-01-28T10:00:00Z",
    "approved_at": "2026-01-28T10:00:00Z"
}
```

#### GET /api/actions/{id}

```json
{
    "id": "act_123",
    "tenant_id": "tenant_001",
    "recommendation_id": "rec_456",
    "action_type": "adjust_budget",
    "platform": "meta",
    "target_entity_id": "camp_789",
    "target_entity_type": "campaign",
    "status": "succeeded",
    "action_params": {
        "new_budget": 450.00,
        "currency": "USD"
    },
    "before_state": {
        "budget": 500.00,
        "currency": "USD",
        "status": "ACTIVE",
        "captured_at": "2026-01-28T10:01:00Z"
    },
    "after_state": {
        "budget": 450.00,
        "currency": "USD",
        "status": "ACTIVE",
        "captured_at": "2026-01-28T10:01:05Z"
    },
    "rollback_instructions": {
        "action_type": "adjust_budget",
        "params": {
            "new_budget": 500.00,
            "currency": "USD"
        }
    },
    "execution_started_at": "2026-01-28T10:01:00Z",
    "execution_completed_at": "2026-01-28T10:01:05Z",
    "created_at": "2026-01-28T10:00:00Z"
}
```

---

## 6. Worker Infrastructure

### 6.1 Worker CLI

```
backend/scripts/action_worker.py

Commands:
  dispatch   Create action jobs for approved actions
  process    Execute queued action jobs
  rollback   Process pending rollback requests

Usage:
  python -m scripts.action_worker dispatch
  python -m scripts.action_worker process --limit 10
  python -m scripts.action_worker rollback --limit 5
```

### 6.2 Cron Schedule

```
# Execute approved actions (every 5 minutes)
*/5 * * * * python -m scripts.action_worker process --limit 10

# Process rollback requests (every 10 minutes)
*/10 * * * * python -m scripts.action_worker rollback --limit 5
```

---

## 7. Idempotency & Safety

### 7.1 Idempotency Key Generation

```python
def generate_idempotency_key(action: AIAction) -> str:
    """
    Generate deterministic idempotency key for safe retries.

    Format: {tenant_id}:{action_id}:{timestamp_bucket}

    Timestamp bucket = floor(created_at / 1 hour) to allow
    retries within the same hour.
    """
    timestamp_bucket = int(action.created_at.timestamp() // 3600)
    content = f"{action.tenant_id}:{action.id}:{timestamp_bucket}"
    return hashlib.sha256(content.encode()).hexdigest()[:32]
```

### 7.2 Execution Safety Rules

1. **Pre-execution checks:**
   - Verify action is in `approved` or `queued` status
   - Verify no other action is executing for same target entity
   - Verify platform credentials are valid
   - Verify entitlement for ai_actions feature

2. **During execution:**
   - Use idempotency key for all platform API calls
   - Capture before_state BEFORE any modification
   - Log every API request/response

3. **Post-execution:**
   - Verify change via GET request to platform (source of truth)
   - Only mark as `succeeded` if platform confirms change
   - Generate rollback instructions from before_state

4. **On failure:**
   - Do NOT retry automatically
   - Mark as `failed` with error details
   - Require manual review or re-approval

---

## 8. Rollback Support

### 8.1 Rollback Instructions Format

```json
{
    "action_type": "adjust_budget",
    "platform": "meta",
    "target_entity_id": "camp_789",
    "params": {
        "new_budget": 500.00,  // Original value
        "currency": "USD"
    },
    "generated_at": "2026-01-28T10:01:05Z",
    "valid_until": "2026-01-29T10:01:05Z"  // 24-hour validity
}
```

### 8.2 Rollback Service

```python
class ActionRollbackService:
    """
    Service for executing action rollbacks.

    CONSTRAINTS:
    - Rollback only available for 24 hours after execution
    - Some actions may not be reversible (deleted entities)
    - Rollback is also logged as an action
    """

    def execute_rollback(self, action_id: str) -> RollbackResult:
        """
        Execute rollback using stored instructions.

        Flow:
        1. Validate rollback is available
        2. Capture current state
        3. Execute reverse action
        4. Verify state matches original before_state
        5. Update action status to rolled_back
        """
        pass
```

---

## 9. Billing & Entitlements

### 9.1 Feature Configuration

The `ai_actions` feature is already defined in `plan_features`:

| Plan | ai_actions | Monthly Limit |
|------|------------|---------------|
| Free | ❌ | 0 |
| Growth | ❌ | 0 |
| Pro | ✅ | 100 |
| Enterprise | ✅ | Unlimited |

### 9.2 Entitlement Checks

```python
# In ActionApprovalService
def approve_action(self, recommendation_id: str) -> AIAction:
    # Check feature entitlement
    if not self.billing_service.check_feature_entitlement(
        self.tenant_id,
        BillingFeature.AI_ACTIONS
    ):
        raise HTTPException(
            status_code=402,
            detail="AI Actions requires Pro or Enterprise plan"
        )

    # Check monthly limit
    monthly_limit = self.billing_service.get_feature_limit(
        self.tenant_id,
        "ai_actions_per_month"
    )
    current_count = self._get_monthly_action_count()

    if monthly_limit and current_count >= monthly_limit:
        raise HTTPException(
            status_code=402,
            detail=f"Monthly action limit ({monthly_limit}) reached"
        )
```

---

## 10. Testing Strategy

### 10.1 Unit Tests

```
tests/unit/services/
├── test_action_execution_service.py
├── test_action_approval_service.py
├── test_action_rollback_service.py
└── test_platform_executors/
    ├── test_meta_executor.py
    ├── test_google_executor.py
    └── test_shopify_executor.py
```

### 10.2 Integration Tests

```
tests/integration/
├── test_action_api_endpoints.py
├── test_action_job_workflow.py
└── test_platform_integration.py  # With mocked external APIs
```

### 10.3 Test Scenarios

1. **Happy path:** Approve → Execute → Verify → Success
2. **Partial failure:** Multi-action job with one failure
3. **Rollback:** Execute → Rollback → Verify original state
4. **Idempotency:** Same action executed twice → Same result
5. **Rate limiting:** Handle 429 responses gracefully
6. **Auth failure:** Handle expired tokens
7. **Entity not found:** Handle deleted campaigns

---

## 11. Implementation Tasks

### Phase 1: Database & Models (Foundation)

| # | Task | Priority | Depends On |
|---|------|----------|------------|
| 1.1 | Create `ai_actions_schema.sql` migration | High | - |
| 1.2 | Create `AIAction` SQLAlchemy model | High | 1.1 |
| 1.3 | Create `ActionExecutionLog` model | High | 1.1 |
| 1.4 | Create `ActionJob` model | High | 1.1 |
| 1.5 | Add action enums (ActionType, ActionStatus) | High | 1.1 |
| 1.6 | Update billing seed for ai_actions limits | Medium | - |

### Phase 2: Platform Executors (External Integration)

| # | Task | Priority | Depends On |
|---|------|----------|------------|
| 2.1 | Create `BasePlatformExecutor` abstract class | High | 1.2 |
| 2.2 | Implement `MetaAdsExecutor` | High | 2.1 |
| 2.3 | Implement `GoogleAdsExecutor` | High | 2.1 |
| 2.4 | Implement `ShopifyExecutor` (optional) | Low | 2.1 |
| 2.5 | Add platform credential management | High | 2.1 |
| 2.6 | Implement retry with exponential backoff | High | 2.1 |

### Phase 3: Core Services (Business Logic)

| # | Task | Priority | Depends On |
|---|------|----------|------------|
| 3.1 | Create `ActionApprovalService` | High | 1.2, 1.5 |
| 3.2 | Create `ActionExecutionService` | High | 2.2, 2.3 |
| 3.3 | Create `ActionRollbackService` | High | 3.2 |
| 3.4 | Create `ActionJobRunner` | High | 3.2 |
| 3.5 | Create `ActionJobDispatcher` | High | 1.4 |
| 3.6 | Implement idempotency key generation | High | 3.2 |
| 3.7 | Implement before/after state capture | High | 3.2 |
| 3.8 | Implement execution logging | High | 1.3, 3.2 |

### Phase 4: API Layer (REST Endpoints)

| # | Task | Priority | Depends On |
|---|------|----------|------------|
| 4.1 | Create `/api/actions` route module | High | 3.1-3.5 |
| 4.2 | Implement `POST /approve/{rec_id}` | High | 4.1, 3.1 |
| 4.3 | Implement `GET /actions` (list) | High | 4.1 |
| 4.4 | Implement `GET /actions/{id}` | High | 4.1 |
| 4.5 | Implement `POST /actions/{id}/execute` | High | 4.1, 3.2 |
| 4.6 | Implement `POST /actions/{id}/rollback` | High | 4.1, 3.3 |
| 4.7 | Implement `GET /actions/{id}/logs` | Medium | 4.1 |
| 4.8 | Implement `DELETE /actions/{id}` | Medium | 4.1 |
| 4.9 | Add request/response schemas (Pydantic) | High | 4.1 |

### Phase 5: Worker Infrastructure (Background Jobs)

| # | Task | Priority | Depends On |
|---|------|----------|------------|
| 5.1 | Create `action_worker.py` CLI script | High | 3.4, 3.5 |
| 5.2 | Implement `dispatch` command | High | 5.1 |
| 5.3 | Implement `process` command | High | 5.1 |
| 5.4 | Implement `rollback` command | Medium | 5.1 |
| 5.5 | Add cron job configuration docs | Low | 5.1-5.4 |

### Phase 6: Testing & Documentation

| # | Task | Priority | Depends On |
|---|------|----------|------------|
| 6.1 | Unit tests for ActionExecutionService | High | 3.2 |
| 6.2 | Unit tests for platform executors | High | 2.2, 2.3 |
| 6.3 | Integration tests for API endpoints | High | 4.1-4.8 |
| 6.4 | Integration tests for job workflow | High | 5.1-5.4 |
| 6.5 | API documentation (OpenAPI) | Medium | 4.1-4.8 |
| 6.6 | Runbook for operations | Low | All |

---

## 12. Acceptance Criteria Checklist

| Criteria | Implementation | Test Coverage |
|----------|----------------|---------------|
| ✅ Execution confirmed externally | Platform executor verifies via GET after mutation | test_execution_verified_externally |
| ✅ Partial failures handled | ActionJob tracks succeeded/failed counts, status = partially_succeeded | test_partial_failure_handling |
| ✅ Rollback possible | rollback_instructions stored, ActionRollbackService | test_rollback_execution |

---

## 13. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Platform API credentials leaked | Encrypt at rest, decrypt only when needed, rotate regularly |
| Unintended campaign changes | Require explicit approval, capture before_state, provide rollback |
| Rate limiting from platforms | Exponential backoff, respect Retry-After, queue throttling |
| Partial execution failures | Track individual action status, allow selective retry |
| Rollback window expiry | 24-hour validity, warn user if approaching expiry |
| Concurrent actions on same entity | Database constraint prevents, UI shows warning |

---

## 14. Future Enhancements (Out of Scope for 8.5)

1. **Scheduled actions** — Execute at specific time
2. **Conditional actions** — Execute only if metrics meet threshold
3. **Batch actions** — Multiple entities in one action
4. **Approval workflows** — Multi-user approval for high-risk actions
5. **Action templates** — Reusable action configurations

---

## Appendix A: File Structure

```
backend/
├── migrations/
│   └── ai_actions_schema.sql           # NEW
├── src/
│   ├── models/
│   │   ├── ai_action.py                # NEW
│   │   ├── action_execution_log.py     # NEW
│   │   └── action_job.py               # NEW
│   ├── services/
│   │   ├── action_approval_service.py  # NEW
│   │   ├── action_execution_service.py # NEW
│   │   ├── action_job_dispatcher.py    # NEW
│   │   ├── action_job_runner.py        # NEW
│   │   ├── action_rollback_service.py  # NEW
│   │   └── platform_executors/         # NEW
│   │       ├── __init__.py
│   │       ├── base_executor.py
│   │       ├── meta_executor.py
│   │       └── google_executor.py
│   └── api/
│       └── routes/
│           └── actions.py              # NEW
├── scripts/
│   └── action_worker.py                # NEW
└── tests/
    ├── unit/
    │   └── services/
    │       ├── test_action_execution_service.py    # NEW
    │       ├── test_action_approval_service.py     # NEW
    │       └── test_platform_executors/            # NEW
    └── integration/
        ├── test_action_api_endpoints.py            # NEW
        └── test_action_job_workflow.py             # NEW
```

---

## Appendix B: Sequence Diagram — Action Execution

```
User          API              ApprovalSvc      ExecutionSvc     MetaExecutor     Meta API
 │              │                   │                │                │              │
 │──approve────▶│                   │                │                │              │
 │              │──create_action───▶│                │                │              │
 │              │                   │──check_entitl──│                │              │
 │              │                   │◀─────OK────────│                │              │
 │              │◀──action_created──│                │                │              │
 │◀──200 OK─────│                   │                │                │              │
 │              │                   │                │                │              │
 │              │    [Worker runs every 5 min]      │                │              │
 │              │                   │                │                │              │
 │              │                   │──execute──────▶│                │              │
 │              │                   │                │──get_state────▶│              │
 │              │                   │                │                │──GET────────▶│
 │              │                   │                │                │◀──state──────│
 │              │                   │                │◀─before_state──│              │
 │              │                   │                │                │              │
 │              │                   │                │──execute──────▶│              │
 │              │                   │                │                │──POST───────▶│
 │              │                   │                │                │◀──200 OK─────│
 │              │                   │                │                │              │
 │              │                   │                │──verify───────▶│              │
 │              │                   │                │                │──GET────────▶│
 │              │                   │                │                │◀──new_state──│
 │              │                   │                │◀─after_state───│              │
 │              │                   │                │                │              │
 │              │                   │◀──succeeded────│                │              │
```

---

*End of Implementation Plan*
