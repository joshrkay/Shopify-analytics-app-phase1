"""
Entitlement models — canonical types for the plan-based entitlement system.

Provides:
- FeatureGrant: Single resolved feature with source tracking
- TenantOverride: Per-tenant feature override with mandatory expiry
- ResolvedEntitlement: Fully resolved entitlement snapshot for a tenant
- TenantEntitlementOverride: SQLAlchemy model for persistent overrides
- resolve_features(): Deterministic override → plan → deny resolution

Resolution order (deterministic):
    1. Per-tenant override (if not expired)  → granted/denied by override
    2. Plan default from config/plans.json   → granted/denied by plan
    3. Deny                                  → feature unknown = denied

CRITICAL: Overrides never mutate plan defaults. Resolution always deep-copies.
"""

import uuid
import logging
from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Any
import json

from sqlalchemy import (
    Column, String, Boolean, DateTime, Text, Index,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSON

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical enums — single source of truth, import from here
# ---------------------------------------------------------------------------

class BillingState(str, Enum):
    """All possible billing states for entitlement evaluation."""
    ACTIVE = "active"
    PAST_DUE = "past_due"
    GRACE_PERIOD = "grace_period"
    CANCELED = "canceled"
    EXPIRED = "expired"
    FROZEN = "frozen"
    PENDING = "pending"
    TRIALING = "trialing"
    NONE = "none"

    @classmethod
    def from_subscription_status(
        cls,
        status: str,
        grace_period_ends_on: Optional[datetime] = None,
        current_period_end: Optional[datetime] = None,
    ) -> "BillingState":
        """Map subscription status + dates to billing state."""
        status_lower = (status or "").lower()
        now = datetime.now(timezone.utc)

        if status_lower == "frozen":
            if grace_period_ends_on and now <= grace_period_ends_on:
                return cls.GRACE_PERIOD
            return cls.FROZEN

        if status_lower in ("cancelled", "canceled"):
            if current_period_end and now <= current_period_end:
                return cls.CANCELED
            return cls.EXPIRED

        direct = {
            "active": cls.ACTIVE,
            "pending": cls.PENDING,
            "trialing": cls.TRIALING,
            "trial_active": cls.TRIALING,
            "expired": cls.EXPIRED,
            "trial_expired": cls.EXPIRED,
            "declined": cls.EXPIRED,
            "past_due": cls.PAST_DUE,
        }
        return direct.get(status_lower, cls.NONE)


class AccessLevel(str, Enum):
    """Access levels derived from billing state."""
    FULL = "full"
    READ_ONLY = "read_only"
    READ_ONLY_ANALYTICS = "read_only_analytics"
    LIMITED = "limited"
    FULL_UNTIL_PERIOD_END = "full_until_period_end"
    NONE = "none"

    def allows_writes(self) -> bool:
        return self in (AccessLevel.FULL, AccessLevel.FULL_UNTIL_PERIOD_END)

    def allows_reads(self) -> bool:
        return self != AccessLevel.NONE


class FeatureSource(str, Enum):
    """Where a feature grant originated."""
    OVERRIDE = "override"
    PLAN = "plan"
    DENY = "deny"


# ---------------------------------------------------------------------------
# Value objects (frozen dataclasses)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FeatureGrant:
    """
    A single resolved feature entitlement with provenance.

    Immutable — safe to cache and share across threads.
    """
    feature_key: str
    granted: bool
    source: str  # FeatureSource value
    limit_value: Optional[int] = None
    expires_at: Optional[str] = None  # ISO-8601 string for serialisation

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TenantOverride:
    """
    In-memory representation of a per-tenant feature override.

    expires_at is MANDATORY — overrides without expiry are rejected.
    """
    tenant_id: str
    feature_key: str
    enabled: bool
    expires_at: datetime
    reason: str
    created_by: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        if self.expires_at is None:
            raise ValueError("TenantOverride.expires_at is mandatory")
        if not isinstance(self.expires_at, datetime):
            raise TypeError(f"expires_at must be datetime, got {type(self.expires_at)}")

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["expires_at"] = self.expires_at.isoformat()
        d["created_at"] = self.created_at.isoformat()
        return d


@dataclass(frozen=True)
class ResolvedEntitlement:
    """
    Complete resolved entitlement snapshot for a tenant.

    Immutable — safe to cache, serialise, and return from APIs.
    """
    tenant_id: str
    plan_id: str
    plan_name: str
    billing_state: str  # BillingState value
    access_level: str   # AccessLevel value
    features: Dict[str, FeatureGrant]
    limits: Dict[str, int]
    overrides_applied: List[str]
    warnings: List[str]
    resolved_at: str  # ISO-8601
    source: str  # "cache" or "computed"

    def has_feature(self, feature_key: str) -> bool:
        grant = self.features.get(feature_key)
        return grant is not None and grant.granted

    def get_feature(self, feature_key: str) -> Optional[FeatureGrant]:
        return self.features.get(feature_key)

    def get_limit(self, limit_key: str) -> Optional[int]:
        return self.limits.get(limit_key)

    def is_limit_exceeded(self, limit_key: str, current_usage: int) -> bool:
        limit = self.limits.get(limit_key)
        if limit is None or limit == -1:
            return False
        return current_usage >= limit

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "plan_id": self.plan_id,
            "plan_name": self.plan_name,
            "billing_state": self.billing_state,
            "access_level": self.access_level,
            "features": {k: v.to_dict() for k, v in self.features.items()},
            "limits": self.limits,
            "overrides_applied": self.overrides_applied,
            "warnings": self.warnings,
            "resolved_at": self.resolved_at,
            "source": self.source,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResolvedEntitlement":
        features = {
            k: FeatureGrant(**v) for k, v in data.get("features", {}).items()
        }
        return cls(
            tenant_id=data["tenant_id"],
            plan_id=data["plan_id"],
            plan_name=data["plan_name"],
            billing_state=data["billing_state"],
            access_level=data["access_level"],
            features=features,
            limits=data.get("limits", {}),
            overrides_applied=data.get("overrides_applied", []),
            warnings=data.get("warnings", []),
            resolved_at=data["resolved_at"],
            source=data.get("source", "cache"),
        )

    @classmethod
    def from_json(cls, raw: str) -> "ResolvedEntitlement":
        return cls.from_dict(json.loads(raw))


# ---------------------------------------------------------------------------
# SQLAlchemy model — persistent per-tenant overrides
# ---------------------------------------------------------------------------

class TenantEntitlementOverride(Base, TimestampMixin, TenantScopedMixin):
    """
    Persistent per-tenant entitlement override.

    Overrides allow granting or revoking individual features for a specific
    tenant independent of their plan.  Every override MUST have an expiry
    date — open-ended overrides are not allowed.

    Overrides never mutate the plan config; they are evaluated at resolution
    time and layered on top of plan defaults.
    """

    __tablename__ = "tenant_entitlement_overrides"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)",
    )

    feature_key = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Feature key being overridden",
    )

    enabled = Column(
        Boolean,
        nullable=False,
        comment="True = grant feature, False = revoke feature",
    )

    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Mandatory expiry timestamp — override becomes inactive after this",
    )

    reason = Column(
        Text,
        nullable=False,
        comment="Human-readable reason for the override",
    )

    created_by = Column(
        String(255),
        nullable=False,
        comment="User/system that created the override",
    )

    metadata_json = Column(
        "metadata",
        JSON,
        nullable=True,
        comment="Additional metadata about the override",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "feature_key",
            name="uq_tenant_override_tenant_feature",
        ),
        Index(
            "idx_tenant_overrides_expiry",
            "expires_at",
        ),
        Index(
            "idx_tenant_overrides_tenant_active",
            "tenant_id",
            "expires_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TenantEntitlementOverride("
            f"tenant_id={self.tenant_id}, "
            f"feature_key={self.feature_key}, "
            f"enabled={self.enabled}, "
            f"expires_at={self.expires_at}"
            f")>"
        )

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now > self.expires_at

    def to_domain(self) -> TenantOverride:
        """Convert to domain value object."""
        return TenantOverride(
            tenant_id=self.tenant_id,
            feature_key=self.feature_key,
            enabled=self.enabled,
            expires_at=self.expires_at,
            reason=self.reason,
            created_by=self.created_by,
            created_at=self.created_at,
        )


# ---------------------------------------------------------------------------
# Resolution logic
# ---------------------------------------------------------------------------

def resolve_features(
    plan_features: Dict[str, Any],
    active_overrides: List[TenantOverride],
) -> Dict[str, FeatureGrant]:
    """
    Deterministic feature resolution: override → plan → deny.

    Args:
        plan_features: Deep-copy of plan feature config from loader
                       (keys → bool|"limited"|int).
        active_overrides: Non-expired tenant overrides.

    Returns:
        Dict of feature_key → FeatureGrant with source tracking.

    CRITICAL: This function never mutates plan_features. Callers should
    pass a deep-copy if plan_features is shared state.
    """
    features = deepcopy(plan_features)
    grants: Dict[str, FeatureGrant] = {}

    # Index overrides by feature_key for O(1) lookup
    override_map: Dict[str, TenantOverride] = {}
    now = datetime.now(timezone.utc)
    for override in active_overrides:
        if not override.is_expired(now):
            override_map[override.feature_key] = override

    # Resolve each plan feature
    for key, value in features.items():
        if key in override_map:
            ov = override_map[key]
            grants[key] = FeatureGrant(
                feature_key=key,
                granted=ov.enabled,
                source=FeatureSource.OVERRIDE.value,
                expires_at=ov.expires_at.isoformat(),
            )
        else:
            # Plan value: True, False, or "limited" (treated as granted)
            granted = value is True or value == "limited"
            limit = None
            if isinstance(value, int) and not isinstance(value, bool):
                limit = value
                granted = value > 0
            grants[key] = FeatureGrant(
                feature_key=key,
                granted=granted,
                source=FeatureSource.PLAN.value,
                limit_value=limit,
            )

    # Overrides for features NOT in the plan (additive grants)
    for key, ov in override_map.items():
        if key not in grants:
            grants[key] = FeatureGrant(
                feature_key=key,
                granted=ov.enabled,
                source=FeatureSource.OVERRIDE.value,
                expires_at=ov.expires_at.isoformat(),
            )

    return grants
