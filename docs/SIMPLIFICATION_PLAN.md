# Codebase Simplification Plan

## Executive Summary

This document outlines a plan to reduce complexity and "AI slop" in the Shopify Analytics App codebase. The goal is to achieve **30-40% code reduction** while maintaining all functionality and ensuring non-breaking changes through comprehensive automated testing.

**Current State:**
- Backend: ~9,400 lines across 121 files
- Platform layer alone: 3,400+ lines
- Governance module: 2,800 lines
- Custom exception classes: 11+ (mostly redundant)
- Excessive docstrings averaging 15-25 lines per module

**Target State:**
- Backend: ~6,000-7,000 lines
- Platform layer: ~1,500-2,000 lines
- Governance module: ~500-800 lines (or removed entirely if unused)
- Exception classes: 4-5 core classes
- Concise docstrings: 1-3 lines where needed

---

## Phase 1: Documentation Cleanup (Low Risk)

### 1.1 Trim Module Docstrings

**Problem:** Every module has 15-30 line docstrings explaining requirements, constraints, and usage patterns that belong in external documentation, not inline.

**Files to modify:**
- `backend/src/platform/errors.py` - 18 line docstring → 2 lines
- `backend/src/platform/audit.py` - 19 line docstring → 2 lines
- `backend/src/platform/rbac.py` - 27 line docstring → 3 lines
- `backend/src/platform/secrets.py` - 27 line docstring → 3 lines
- `backend/src/repositories/base_repo.py` - 6 line docstring → 1 line
- `backend/src/platform/audit_events.py` - 30 line docstring → 3 lines

**Before (errors.py):**
```python
"""
Consistent error handling for AI Growth Analytics.

All API errors MUST use these standard error classes and shapes.
Stack traces are NEVER returned to clients.

Standard HTTP status codes:
- 400: Bad Request (validation errors)
- 401: Unauthorized (auth failures - no/expired token)
- 402: Payment Required (paywalled features)
- 403: Forbidden (permission denied, cross-tenant access)
- 404: Not Found
- 409: Conflict (duplicate, concurrency error)
- 422: Unprocessable Entity (semantic validation errors)
- 429: Too Many Requests (rate limit)
- 500: Internal Server Error
- 503: Service Unavailable
"""
```

**After:**
```python
"""Application error classes with consistent API response format."""
```

**Estimated reduction:** ~200 lines

---

### 1.2 Trim Function/Method Docstrings

**Problem:** Most functions have verbose docstrings with Args/Returns/Raises sections that duplicate type hints.

**Before:**
```python
def has_permission(tenant_context: TenantContext, permission: Permission) -> bool:
    """
    Check if tenant context has the specified permission.

    Args:
        tenant_context: The current tenant context from JWT
        permission: The permission to check

    Returns:
        True if any of the user's roles grant this permission
    """
    return roles_have_permission(tenant_context.roles, permission)
```

**After:**
```python
def has_permission(tenant_context: TenantContext, permission: Permission) -> bool:
    """Check if tenant context has the specified permission."""
    return roles_have_permission(tenant_context.roles, permission)
```

**Files to modify:** All platform/*.py, repositories/*.py, services/*.py

**Estimated reduction:** ~400 lines

---

## Phase 2: Exception Consolidation (Medium Risk)

### 2.1 Consolidate Platform Exceptions

**Problem:** 11 exception classes that mostly just set a status code and message.

**Current exceptions in `errors.py`:**
1. `AppError` (base)
2. `ValidationError` → 400
3. `AuthenticationError` → 401
4. `PaymentRequiredError` → 402
5. `PermissionDeniedError` → 403
6. `TenantIsolationError` → 403
7. `NotFoundError` → 404
8. `ConflictError` → 409
9. `RateLimitError` → 429
10. `ServiceUnavailableError` → 503
11. `FeatureDisabledError` → 503

**Additional exceptions scattered elsewhere:**
- `BillingServiceError`, `PlanNotFoundError`, `StoreNotFoundError`, `SubscriptionError` in billing_service.py
- `AirbyteError` + 5 subclasses in airbyte/exceptions.py
- `TenantIsolationError` (duplicate!) in base_repo.py
- `EncryptionError` in secrets.py
- `RBACError` in rbac.py

**Proposed consolidation:**

Keep 5 core exceptions:
```python
class AppError(Exception):
    """Base error with code, message, status_code, details."""

class ValidationError(AppError):
    """400 Bad Request - input validation failures."""

class AuthError(AppError):
    """401/403 - authentication/authorization failures."""

class NotFoundError(AppError):
    """404 - resource not found."""

class ServiceError(AppError):
    """500/503 - internal/external service failures."""
```

**Migration path:**
1. Keep old classes as aliases initially: `PaymentRequiredError = AuthError`
2. Update imports gradually
3. Remove aliases after all code migrated

**Breaking change risk:** LOW - error response format unchanged

**Required tests:** Verify API error responses remain identical

---

### 2.2 Remove Duplicate TenantIsolationError

**Problem:** `TenantIsolationError` defined in both `errors.py` and `base_repo.py`.

**Action:** Remove from `base_repo.py`, import from `errors.py`.

---

## Phase 3: RBAC Simplification (Medium Risk)

### 3.1 Consolidate Permission Functions

**Problem:** 9 nearly-identical permission checking functions/decorators with repetitive logging.

**Current functions:**
1. `has_permission()` - single permission check
2. `has_any_permission()` - OR check
3. `has_all_permissions()` - AND check
4. `has_role()` - role check
5. `require_permission()` - decorator
6. `require_any_permission()` - decorator
7. `require_all_permissions()` - decorator
8. `require_role()` - decorator
9. `require_admin()` - decorator
10. `check_permission_or_raise()` - programmatic check

**Proposed consolidation:**

```python
def check_permission(
    context: TenantContext,
    *,
    permission: Permission | None = None,
    permissions: list[Permission] | None = None,
    any_of: bool = False,
    role: Role | None = None,
) -> bool:
    """Single unified permission checker."""

def require_permission(
    *,
    permission: Permission | None = None,
    permissions: list[Permission] | None = None,
    any_of: bool = False,
    role: Role | None = None,
) -> Callable:
    """Single unified permission decorator."""

# Convenience aliases for backwards compatibility
require_admin = lambda f: require_permission(role=Role.ADMIN)(f)
```

**Estimated reduction:** ~150 lines

**Required tests:** All existing RBAC tests must pass

---

### 3.2 Reduce Logging Verbosity

**Problem:** Every permission check logs 6-8 fields at WARNING level on denial and DEBUG on success.

**Before:**
```python
logger.warning(
    "Permission denied",
    extra={
        "tenant_id": tenant_context.tenant_id,
        "user_id": tenant_context.user_id,
        "required_permission": permission.value,
        "user_roles": tenant_context.roles,
        "path": request.url.path,
        "method": request.method,
    }
)
```

**After:**
```python
logger.debug(f"Permission denied: {permission.value} for {tenant_context.user_id}")
```

**Rationale:** Permission denials are normal operations (e.g., hiding UI elements), not warnings. Excessive logging creates noise.

---

## Phase 4: Audit System Consolidation (High Risk)

### 4.1 Merge audit.py and audit_events.py

**Problem:** Two separate audit systems with overlapping functionality.

- `audit.py` (400 lines): AuditAction enum, AuditLog model, write functions, decorator
- `audit_events.py` (840 lines): AUDITABLE_EVENTS dict, categories, severity, validation

**Proposed structure:**

Keep `audit.py` as the single audit module:
```python
# audit.py (~200 lines)
"""Audit logging system."""

class AuditAction(str, Enum):
    """Auditable actions."""
    # Keep existing enum values

class AuditLog(Base):
    """Audit log database model."""
    # Keep existing model

async def log_audit(db, action, **kwargs):
    """Log an audit event."""
    # Simplified single function

# Move event metadata schema to config/audit_schema.yaml if needed
```

**Remove from `audit_events.py`:**
- AUDITABLE_EVENTS dict (move to YAML config if needed for validation)
- EVENT_CATEGORIES (use action prefix: `auth.*`, `billing.*`)
- EVENT_SEVERITY (move to alerting config)
- Utility functions (inline where needed)

**Estimated reduction:** ~600 lines

**Required tests:** Audit log format, database writes, decorator behavior

---

## Phase 5: Secrets Module Cleanup (Low Risk)

### 5.1 Simplify Secret Detection

**Problem:** 18 regex patterns for secret detection is overkill.

**Before:**
```python
SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key)", re.IGNORECASE),
    re.compile(r"(secret[_-]?key)", re.IGNORECASE),
    # ... 16 more patterns
]
```

**After:**
```python
SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key|secret|token|password|credential)", re.IGNORECASE),
]
```

**Estimated reduction:** ~30 lines

---

### 5.2 Remove Unused Features

**Problem:** `SecretRedactingFilter` logging filter appears unused.

**Action:** Remove if not attached to any logger. Verify with grep.

---

## Phase 6: Repository Layer Simplification (Medium Risk)

### 6.1 Inline Tenant Validation

**Problem:** `_validate_tenant_id()` called redundantly in every method.

**Before (359 lines):**
```python
def get_by_id(self, entity_id: str, tenant_id: Optional[str] = None) -> Optional[T]:
    self._validate_tenant_id(tenant_id, "get_by_id")
    query = self.db_session.query(self._model_class)
    query = self._enforce_tenant_scope(query)
    return query.filter(self._model_class.id == entity_id).first()
```

**After (~150 lines):**
```python
def get_by_id(self, entity_id: str) -> Optional[T]:
    return (
        self.db_session.query(self._model_class)
        .filter(self._model_class.tenant_id == self.tenant_id)
        .filter(self._model_class.id == entity_id)
        .first()
    )
```

**Changes:**
1. Remove `tenant_id` parameter from all methods (constructor already enforces)
2. Inline tenant filtering (remove `_enforce_tenant_scope`)
3. Remove verbose logging on every CRUD operation

**Estimated reduction:** ~150 lines

**Required tests:** All repository operations maintain tenant isolation

---

## Phase 7: Governance Module Evaluation (High Impact)

### 7.1 Assess Actual Usage

**Current state:** 2,800 lines across 7 files:
- `ai_guardrails.py` - 520 lines
- `approval_gate.py` - 497 lines
- `pre_deploy_validator.py` - 533 lines
- `rollback_orchestrator.py` - 567 lines
- `metric_versioning.py` - 498 lines
- `base.py` - 155 lines

**Question:** Is this module actually used in production, or is it speculative future-proofing?

**Action items:**
1. Grep for imports of governance module across codebase
2. Check if any API routes use these classes
3. Review git history for actual usage

**If unused:** Remove entirely (save 2,800 lines)

**If partially used:** Keep only used components

---

## Testing Strategy

### Regression Test Suite

Create `backend/src/tests/regression/test_simplification.py` to verify:

```python
"""
Regression tests to ensure simplification changes are non-breaking.

These tests verify public API contracts remain unchanged.
"""

class TestErrorResponseFormat:
    """Verify error responses maintain exact format."""

    def test_validation_error_format(self):
        """ValidationError returns expected JSON structure."""

    def test_all_error_types_have_code_message_details(self):
        """All errors have consistent structure."""

class TestRBACBehavior:
    """Verify RBAC behavior unchanged."""

    def test_permission_checks_return_same_results(self):
        """Permission logic unchanged after refactor."""

    def test_decorator_raises_403_unchanged(self):
        """Decorators raise HTTPException(403) as before."""

class TestAuditLogFormat:
    """Verify audit log format unchanged."""

    def test_audit_log_has_required_fields(self):
        """Audit logs contain all required fields."""

    def test_audit_action_values_unchanged(self):
        """AuditAction enum values unchanged."""

class TestTenantIsolation:
    """Verify tenant isolation unchanged."""

    def test_repository_enforces_tenant_scope(self):
        """Repository queries always include tenant filter."""

class TestSecretRedaction:
    """Verify secret redaction unchanged."""

    def test_redact_secrets_catches_all_patterns(self):
        """Known secret patterns are redacted."""
```

### Contract Tests

Create snapshot tests for API responses:

```python
class TestAPIContracts:
    """Snapshot tests for API response contracts."""

    def test_error_response_snapshot(self, snapshot):
        """Error response matches snapshot."""
        error = ValidationError("test", {"field": "name"})
        assert error.to_dict() == snapshot

    def test_audit_log_snapshot(self, snapshot):
        """Audit log entry matches snapshot."""
```

### Pre-Commit Hook

Add a pre-commit check that runs the regression suite:

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: regression-tests
      name: Run regression tests
      entry: pytest backend/src/tests/regression/ -v
      language: system
      pass_filenames: false
```

---

## Implementation Order

### Week 1: Safe Changes (Low Risk)
1. Trim all module docstrings
2. Trim function docstrings
3. Remove duplicate TenantIsolationError
4. Simplify secret patterns

### Week 2: Medium Risk Changes
1. Create regression test suite FIRST
2. Consolidate RBAC functions
3. Simplify repository layer
4. Run all tests, fix any regressions

### Week 3: High Risk Changes
1. Evaluate governance module usage
2. Remove or simplify governance
3. Merge audit systems
4. Final test pass

---

## Metrics & Success Criteria

| Metric | Before | Target | Measurement |
|--------|--------|--------|-------------|
| Total Python lines | ~9,400 | ~6,500 | `find backend -name '*.py' | xargs wc -l` |
| Platform layer lines | ~3,400 | ~1,800 | `wc -l backend/src/platform/*.py` |
| Exception classes | 15+ | 5 | Count in errors.py |
| Average docstring lines | 15-25 | 1-3 | Manual review |
| Test coverage | Current | >=Current | pytest --cov |
| All existing tests | Pass | Pass | pytest |

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Breaking error format | Low | High | Snapshot tests |
| RBAC logic change | Medium | Critical | Exhaustive permission tests |
| Audit data loss | Low | High | Database migration tests |
| Removed needed code | Medium | Medium | Feature flags, gradual rollout |

---

## Appendix: Files to Modify

### Definitely Modify
- `backend/src/platform/errors.py`
- `backend/src/platform/rbac.py`
- `backend/src/platform/audit.py`
- `backend/src/platform/secrets.py`
- `backend/src/repositories/base_repo.py`

### Possibly Remove
- `backend/src/platform/audit_events.py` (merge into audit.py)
- `backend/src/governance/` (if unused)

### Create New
- `backend/src/tests/regression/test_simplification.py`
- `backend/src/tests/regression/test_api_contracts.py`
