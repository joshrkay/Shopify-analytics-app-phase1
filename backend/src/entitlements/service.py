"""
Entitlement Service — single entry point for all entitlement operations.

Provides:
- get_entitlements(tenant_id)  → ResolvedEntitlement
- check_feature(tenant_id, feature_key) → FeatureGrant
- invalidate_entitlements(tenant_id, reason)
- Override CRUD (create / delete / cleanup expired)

Architecture:
- Fail-CLOSED: any evaluation error denies access and emits alert
- Single-flight: concurrent cache misses for the same tenant share one DB query
- Deterministic subscription selection: highest-tier active subscription wins
- Resolution order: override → plan → deny

CRITICAL: This is the ONLY module that should be used to query entitlements.
Do NOT call loader, cache, or policy directly for tenant-scoped lookups.
"""

import logging
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from src.entitlements.models import (
    BillingState,
    AccessLevel,
    FeatureGrant,
    FeatureSource,
    TenantOverride,
    ResolvedEntitlement,
    TenantEntitlementOverride,
    resolve_features,
)
from src.entitlements.loader import (
    EntitlementLoader,
    PlanEntitlements,
    get_entitlement_loader,
)
from src.entitlements.cache import (
    EntitlementCache,
    get_entitlement_cache,
    INVALIDATION_CHANNEL,
)
from src.entitlements.audit import (
    EntitlementAuditLogger,
    AccessDenialEvent,
    get_audit_logger,
)
from src.entitlements.errors import EntitlementError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors specific to this service
# ---------------------------------------------------------------------------

class EntitlementEvaluationError(EntitlementError):
    """
    Raised when entitlement evaluation fails (fail-closed).

    Carries a machine-readable error_code for the UI to display.
    """

    def __init__(
        self,
        tenant_id: str,
        detail: str,
        cause: Optional[Exception] = None,
    ):
        self.tenant_id = tenant_id
        self.detail = detail
        self.cause = cause
        self.error_code = "ENTITLEMENT_EVAL_FAILED"
        super().__init__(f"Entitlement evaluation failed for {tenant_id}: {detail}")

    def to_dict(self) -> dict:
        return {
            "error": self.error_code,
            "message": self.detail,
            "tenant_id": self.tenant_id,
        }


# ---------------------------------------------------------------------------
# Single-flight lock registry — prevents cache stampede (EC7)
# ---------------------------------------------------------------------------

class _SingleFlightRegistry:
    """
    Prevents N concurrent cache misses for the same tenant from all hitting
    the database.  The first caller acquires a per-tenant lock, computes the
    result, and caches it.  Subsequent callers wait on the lock and read from
    cache.
    """

    def __init__(self):
        self._locks: Dict[str, Lock] = {}
        self._registry_lock = Lock()

    def get_lock(self, key: str) -> Lock:
        with self._registry_lock:
            if key not in self._locks:
                self._locks[key] = Lock()
            return self._locks[key]

    def release(self, key: str) -> None:
        with self._registry_lock:
            self._locks.pop(key, None)


_single_flight = _SingleFlightRegistry()


# ---------------------------------------------------------------------------
# Access-level derivation from billing state + config
# ---------------------------------------------------------------------------

# Default mapping when config doesn't specify access rules for a state.
_DEFAULT_ACCESS_LEVELS: Dict[str, AccessLevel] = {
    BillingState.ACTIVE.value: AccessLevel.FULL,
    BillingState.TRIALING.value: AccessLevel.FULL,
    BillingState.GRACE_PERIOD.value: AccessLevel.FULL,
    BillingState.CANCELED.value: AccessLevel.FULL_UNTIL_PERIOD_END,
    BillingState.PAST_DUE.value: AccessLevel.READ_ONLY,
    BillingState.FROZEN.value: AccessLevel.LIMITED,
    BillingState.EXPIRED.value: AccessLevel.READ_ONLY_ANALYTICS,
    BillingState.PENDING.value: AccessLevel.NONE,
    BillingState.NONE.value: AccessLevel.NONE,
}


def _access_level_for_state(
    billing_state: BillingState,
    loader: EntitlementLoader,
) -> AccessLevel:
    rule = loader.get_access_rule(billing_state.value)
    if rule:
        try:
            return AccessLevel(rule.access_level)
        except ValueError:
            pass
    return _DEFAULT_ACCESS_LEVELS.get(billing_state, AccessLevel.NONE)


def _warnings_for_state(
    billing_state: BillingState,
    loader: EntitlementLoader,
) -> List[str]:
    rule = loader.get_access_rule(billing_state.value)
    if rule:
        return list(rule.warnings)
    return []


# ---------------------------------------------------------------------------
# EntitlementService
# ---------------------------------------------------------------------------

class EntitlementService:
    """
    Central entitlement service.

    One instance per request / job.  Stateless between calls except for
    injected collaborators (db, cache, loader, audit).
    """

    def __init__(
        self,
        db_session: Session,
        cache: Optional[EntitlementCache] = None,
        loader: Optional[EntitlementLoader] = None,
        audit_logger: Optional[EntitlementAuditLogger] = None,
    ):
        self.db = db_session
        self._cache = cache or get_entitlement_cache()
        self._loader = loader or get_entitlement_loader()
        self._audit = audit_logger or get_audit_logger()

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def get_entitlements(self, tenant_id: str) -> ResolvedEntitlement:
        """
        Resolve the current entitlements for a tenant.

        1. Check cache → return on hit
        2. Acquire single-flight lock (prevents stampede)
        3. Re-check cache (another thread may have populated it)
        4. Compute from DB (subscription + plan + overrides)
        5. Cache result
        6. Return

        On ANY failure → raise EntitlementEvaluationError (fail-closed).
        """
        if not tenant_id:
            raise EntitlementEvaluationError(tenant_id or "", "tenant_id is required")

        # 1. Cache hit
        try:
            cached = self._read_from_cache(tenant_id)
            if cached is not None:
                return cached
        except Exception as exc:
            logger.warning("Cache read failed, computing fresh", extra={
                "tenant_id": tenant_id, "error": str(exc),
            })

        # 2. Single-flight lock
        lock = _single_flight.get_lock(tenant_id)
        acquired = lock.acquire(timeout=5.0)
        if not acquired:
            raise EntitlementEvaluationError(
                tenant_id, "Timed out waiting for entitlement computation"
            )

        try:
            # 3. Re-check cache (winner may have populated it)
            try:
                cached = self._read_from_cache(tenant_id)
                if cached is not None:
                    return cached
            except Exception:
                pass

            # 4. Compute from DB
            resolved = self._compute_entitlements(tenant_id)

            # 5. Cache
            try:
                self._write_to_cache(tenant_id, resolved)
            except Exception as exc:
                logger.warning("Failed to cache entitlements", extra={
                    "tenant_id": tenant_id, "error": str(exc),
                })

            return resolved

        except EntitlementEvaluationError:
            raise
        except Exception as exc:
            self._emit_support_alert(tenant_id, exc)
            raise EntitlementEvaluationError(
                tenant_id,
                "Internal error during entitlement evaluation",
                cause=exc,
            )
        finally:
            lock.release()
            _single_flight.release(tenant_id)

    def check_feature(
        self,
        tenant_id: str,
        feature_key: str,
    ) -> FeatureGrant:
        """
        Check a single feature entitlement for a tenant.

        Convenience wrapper — delegates to get_entitlements().
        Returns a DENY grant if the feature is not in the resolved set.
        """
        resolved = self.get_entitlements(tenant_id)
        grant = resolved.features.get(feature_key)
        if grant is not None:
            return grant
        # Unknown feature key → explicit deny
        return FeatureGrant(
            feature_key=feature_key,
            granted=False,
            source=FeatureSource.DENY.value,
        )

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------

    def invalidate_entitlements(
        self,
        tenant_id: str,
        reason: Optional[str] = None,
    ) -> bool:
        """
        Invalidate cached entitlements for a tenant.

        Call this on:
        - Shopify billing webhook receipt
        - Override create / update / delete
        - Override expiry
        """
        deleted = self._cache.invalidate(tenant_id, reason)
        logger.info("Entitlements invalidated", extra={
            "tenant_id": tenant_id,
            "reason": reason,
            "cache_deleted": deleted,
        })
        return deleted

    # ------------------------------------------------------------------
    # Override CRUD
    # ------------------------------------------------------------------

    def create_override(
        self,
        tenant_id: str,
        feature_key: str,
        enabled: bool,
        expires_at: datetime,
        reason: str,
        created_by: str,
    ) -> TenantOverride:
        """
        Create or update a per-tenant feature override.

        Validates:
        - expires_at must be in the future
        - expires_at must be timezone-aware

        Persists to DB, invalidates cache, logs audit event.
        """
        now = datetime.now(timezone.utc)

        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if expires_at <= now:
            raise ValueError("expires_at must be in the future")

        # Upsert — update if (tenant_id, feature_key) exists
        existing = self.db.query(TenantEntitlementOverride).filter(
            TenantEntitlementOverride.tenant_id == tenant_id,
            TenantEntitlementOverride.feature_key == feature_key,
        ).first()

        if existing:
            existing.enabled = enabled
            existing.expires_at = expires_at
            existing.reason = reason
            existing.created_by = created_by
        else:
            override_row = TenantEntitlementOverride(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                feature_key=feature_key,
                enabled=enabled,
                expires_at=expires_at,
                reason=reason,
                created_by=created_by,
            )
            self.db.add(override_row)

        self.db.flush()

        # Invalidate cache so next request recomputes with new override
        self.invalidate_entitlements(
            tenant_id, f"override_created:{feature_key}={enabled}"
        )

        self._audit.log_denial(AccessDenialEvent(
            tenant_id=tenant_id,
            feature_name=f"override:{feature_key}",
            billing_state="n/a",
            reason=f"Override {'created' if not existing else 'updated'}: "
                   f"{feature_key}={enabled}, expires={expires_at.isoformat()}",
            endpoint="entitlement_service",
            method="CREATE_OVERRIDE",
            extra_metadata={"created_by": created_by},
        ))

        return TenantOverride(
            tenant_id=tenant_id,
            feature_key=feature_key,
            enabled=enabled,
            expires_at=expires_at,
            reason=reason,
            created_by=created_by,
        )

    def delete_override(
        self,
        tenant_id: str,
        feature_key: str,
    ) -> bool:
        """Delete a per-tenant override. Returns True if it existed."""
        deleted_count = self.db.query(TenantEntitlementOverride).filter(
            TenantEntitlementOverride.tenant_id == tenant_id,
            TenantEntitlementOverride.feature_key == feature_key,
        ).delete()

        if deleted_count > 0:
            self.db.flush()
            self.invalidate_entitlements(
                tenant_id, f"override_deleted:{feature_key}"
            )
            return True
        return False

    def cleanup_expired_overrides(self) -> int:
        """
        Delete all expired overrides and invalidate affected tenants.

        Returns the number of overrides cleaned up.
        """
        now = datetime.now(timezone.utc)

        expired = self.db.query(TenantEntitlementOverride).filter(
            TenantEntitlementOverride.expires_at < now,
        ).all()

        if not expired:
            return 0

        affected_tenants = set()
        for override in expired:
            affected_tenants.add(override.tenant_id)
            self.db.delete(override)

        self.db.flush()

        for tid in affected_tenants:
            self.invalidate_entitlements(tid, "override_expired")

        logger.info("Cleaned up expired overrides", extra={
            "count": len(expired),
            "tenants_affected": len(affected_tenants),
        })

        return len(expired)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_entitlements(self, tenant_id: str) -> ResolvedEntitlement:
        """
        Full entitlement computation from database.

        Steps:
        1. Find the deterministic active subscription
        2. Derive billing state
        3. Load plan config (deep copy, never mutate original)
        4. Load non-expired overrides
        5. Resolve features
        6. Assemble ResolvedEntitlement
        """
        from src.models.subscription import Subscription, SubscriptionStatus
        from src.models.plan import Plan

        now = datetime.now(timezone.utc)

        # --- 1. Deterministic subscription selection (EC3, EC10) ---
        # Highest-tier active subscription wins.
        subscription = (
            self.db.query(Subscription)
            .join(Plan, Subscription.plan_id == Plan.id)
            .filter(
                Subscription.tenant_id == tenant_id,
                Subscription.status.in_([
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.FROZEN.value,
                    SubscriptionStatus.PENDING.value,
                ]),
            )
            .order_by(Plan.tier.desc(), Subscription.created_at.desc())
            .first()
        )

        # --- 2. Billing state ---
        if subscription:
            billing_state = BillingState.from_subscription_status(
                status=subscription.status,
                grace_period_ends_on=getattr(subscription, "grace_period_ends_on", None),
                current_period_end=getattr(subscription, "current_period_end", None),
            )
            plan_id = subscription.plan_id
        else:
            # No subscription → free tier, always active (EC5)
            billing_state = BillingState.ACTIVE
            plan_id = "plan_free"

        # --- 3. Plan config (deep copy to prevent mutation) ---
        plan_entitlements = self._loader.get_plan(plan_id)
        if plan_entitlements is None:
            # Fallback to free plan if plan_id not in config
            plan_entitlements = self._loader.get_free_plan()
        if plan_entitlements is None:
            raise EntitlementEvaluationError(
                tenant_id, f"Plan config not found for {plan_id}"
            )

        plan_features_copy: Dict = deepcopy(
            {k: v.enabled for k, v in plan_entitlements.features.items()}
        )

        # --- 4. Non-expired overrides ---
        overrides = self._load_active_overrides(tenant_id, now)

        # --- 5. Resolve features ---
        features = resolve_features(plan_features_copy, overrides)

        # --- 6. Access level + warnings ---
        access_level = _access_level_for_state(billing_state, self._loader)
        warnings = _warnings_for_state(billing_state, self._loader)

        # --- 7. Limits (deep copy) ---
        limits = {}
        if plan_entitlements.limits:
            pl = plan_entitlements.limits
            limits = {
                "max_dashboards": pl.max_dashboards,
                "max_users": pl.max_users,
                "api_calls_per_month": pl.api_calls_per_month,
                "ai_insights_per_month": pl.ai_insights_per_month,
                "data_retention_days": pl.data_retention_days,
                "export_rows_per_request": pl.export_rows_per_request,
            }

        overrides_applied = [
            o.feature_key for o in overrides
        ]

        return ResolvedEntitlement(
            tenant_id=tenant_id,
            plan_id=plan_entitlements.plan_id,
            plan_name=plan_entitlements.display_name,
            billing_state=billing_state.value,
            access_level=access_level.value,
            features=features,
            limits=limits,
            overrides_applied=overrides_applied,
            warnings=warnings,
            resolved_at=now.isoformat(),
            source="computed",
        )

    def _load_active_overrides(
        self,
        tenant_id: str,
        now: datetime,
    ) -> List[TenantOverride]:
        """Load non-expired overrides from DB."""
        rows = (
            self.db.query(TenantEntitlementOverride)
            .filter(
                TenantEntitlementOverride.tenant_id == tenant_id,
                TenantEntitlementOverride.expires_at > now,
            )
            .all()
        )
        return [row.to_domain() for row in rows]

    def _read_from_cache(self, tenant_id: str) -> Optional[ResolvedEntitlement]:
        """Read ResolvedEntitlement from cache."""
        cached = self._cache.get(tenant_id)
        if cached is None:
            return None
        # CachedEntitlement → ResolvedEntitlement adaptation
        # The cache stores CachedEntitlement; convert to ResolvedEntitlement.
        try:
            features: Dict[str, FeatureGrant] = {}
            for fk in cached.enabled_features:
                features[fk] = FeatureGrant(
                    feature_key=fk,
                    granted=True,
                    source=FeatureSource.PLAN.value,
                )
            for fk in cached.restricted_features:
                features[fk] = FeatureGrant(
                    feature_key=fk,
                    granted=False,
                    source=FeatureSource.PLAN.value,
                )

            return ResolvedEntitlement(
                tenant_id=cached.tenant_id,
                plan_id=cached.plan_id,
                plan_name=cached.plan_name,
                billing_state=cached.billing_state,
                access_level=cached.access_level,
                features=features,
                limits=cached.limits,
                overrides_applied=[],
                warnings=cached.warnings,
                resolved_at=cached.cached_at or datetime.now(timezone.utc).isoformat(),
                source="cache",
            )
        except Exception as exc:
            logger.warning("Failed to convert cached entitlement", extra={
                "tenant_id": tenant_id, "error": str(exc),
            })
            return None

    def _write_to_cache(self, tenant_id: str, resolved: ResolvedEntitlement) -> None:
        """Write ResolvedEntitlement to cache via CachedEntitlement."""
        from src.entitlements.cache import CachedEntitlement

        enabled = [k for k, v in resolved.features.items() if v.granted]
        restricted = [k for k, v in resolved.features.items() if not v.granted]

        cached = CachedEntitlement(
            tenant_id=resolved.tenant_id,
            plan_id=resolved.plan_id,
            plan_name=resolved.plan_name,
            billing_state=resolved.billing_state,
            access_level=resolved.access_level,
            enabled_features=enabled,
            restricted_features=restricted,
            limits=resolved.limits,
            warnings=resolved.warnings,
            resolved_at=resolved.resolved_at,
            cached_at=datetime.now(timezone.utc).isoformat(),
        )

        self._cache.set(tenant_id, cached)

    def _emit_support_alert(self, tenant_id: str, exc: Exception) -> None:
        """
        Emit a support alert for entitlement evaluation failure.

        Logs at CRITICAL level with structured payload so monitoring
        (Datadog, CloudWatch, PagerDuty) can trigger alerts.
        """
        logger.critical(
            "ENTITLEMENT_EVAL_FAILED — support alert",
            extra={
                "alert_type": "entitlement_eval_failed",
                "tenant_id": tenant_id,
                "error_type": type(exc).__name__,
                "error_detail": str(exc),
                "action_required": "Investigate entitlement evaluation failure",
            },
        )

        self._audit.log_denial(AccessDenialEvent(
            tenant_id=tenant_id,
            feature_name="*",
            billing_state="unknown",
            reason=f"Entitlement evaluation failed: {exc}",
            endpoint="entitlement_service",
            method="GET_ENTITLEMENTS",
            extra_metadata={
                "error_type": type(exc).__name__,
                "support_alert": True,
            },
        ))


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def get_entitlements(tenant_id: str, db_session: Session) -> ResolvedEntitlement:
    """
    Module-level convenience for get_entitlements.

    Creates a service instance with default singletons.
    """
    service = EntitlementService(db_session)
    return service.get_entitlements(tenant_id)


def invalidate_entitlements(tenant_id: str, reason: Optional[str] = None) -> bool:
    """
    Module-level convenience for cache invalidation.

    Does not require a DB session (cache-only operation).
    """
    cache = get_entitlement_cache()
    deleted = cache.invalidate(tenant_id, reason)
    logger.info("Entitlements invalidated (module-level)", extra={
        "tenant_id": tenant_id, "reason": reason,
    })
    return deleted
