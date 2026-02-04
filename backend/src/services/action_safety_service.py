"""
Action Safety Service for Story 8.6.

Implements rate limiting, cooldowns, and safety guardrails for AI actions.

SAFETY REQUIREMENTS:
- Rate limits prevent overwhelming external platforms
- Cooldown windows prevent rapid consecutive actions on same entity
- All blocked/suppressed actions are logged for audit
- Kill switch integration via feature flags

PRINCIPLES:
- Fail closed: If safety check fails, block the action
- Log all safety events for compliance and debugging
- Tenant isolation: All limits are per-tenant

Story 8.6 - Safety, Limits & Guardrails
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import Column, String, Integer, DateTime, Text, Index, UniqueConstraint, JSON
from sqlalchemy.orm import Session

from src.db_base import Base
from src.models.base import TenantScopedMixin, GUID

logger = logging.getLogger(__name__)


# =============================================================================
# Models
# =============================================================================


class AIRateLimit(Base, TenantScopedMixin):
    """Tracks rate limit usage per tenant and operation type."""

    __tablename__ = "ai_rate_limits"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    operation_type = Column(String(50), nullable=False)
    window_start = Column(DateTime(timezone=True), nullable=False)
    window_type = Column(String(20), nullable=False, default="hourly")
    count = Column(Integer, nullable=False, default=0)
    limit_value = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("tenant_id", "operation_type", "window_start", "window_type"),
        Index("ix_ai_rate_limits_tenant_operation", "tenant_id", "operation_type"),
        {"extend_existing": True},
    )


class AICooldown(Base, TenantScopedMixin):
    """Tracks cooldown periods per entity to prevent rapid actions."""

    __tablename__ = "ai_cooldowns"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(255), nullable=False)
    action_type = Column(String(50), nullable=False)
    last_action_at = Column(DateTime(timezone=True), nullable=False)
    cooldown_until = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("tenant_id", "platform", "entity_type", "entity_id", "action_type"),
        Index("ix_ai_cooldowns_tenant_entity", "tenant_id", "platform", "entity_id"),
        {"extend_existing": True},
    )


class AISafetyEvent(Base, TenantScopedMixin):
    """Append-only log of safety events (rate limits, cooldowns, blocks)."""

    __tablename__ = "ai_safety_events"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    event_type = Column(String(50), nullable=False)
    operation_type = Column(String(50), nullable=False)
    entity_id = Column(String(255), nullable=True)
    action_id = Column(String(255), nullable=True)
    reason = Column(Text, nullable=False)
    event_metadata = Column(JSON, nullable=False, default=dict)
    correlation_id = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_ai_safety_events_tenant", "tenant_id"),
        Index("ix_ai_safety_events_type", "event_type"),
        Index("ix_ai_safety_events_tenant_created", "tenant_id", "created_at"),
        {"extend_existing": True},
    )


# =============================================================================
# Configuration
# =============================================================================


# Default rate limits per billing tier (actions per hour)
DEFAULT_RATE_LIMITS = {
    "free": {
        "action_execution": 0,  # No actions on free tier
        "insight_generation": 10,
        "recommendation_generation": 5,
    },
    "growth": {
        "action_execution": 50,
        "insight_generation": 100,
        "recommendation_generation": 50,
    },
    "enterprise": {
        "action_execution": -1,  # Unlimited
        "insight_generation": -1,
        "recommendation_generation": -1,
    },
}

# Cooldown periods in seconds per action type
DEFAULT_COOLDOWNS = {
    "pause_campaign": 14400,  # 4 hours
    "resume_campaign": 14400,  # 4 hours
    "adjust_budget": 3600,  # 1 hour
    "adjust_bid": 3600,  # 1 hour
    "update_targeting": 7200,  # 2 hours
    "update_schedule": 7200,  # 2 hours
    "default": 1800,  # 30 minutes
}

# Maximum recommendations to generate per run
MAX_RECOMMENDATIONS_PER_RUN = 25


# =============================================================================
# Result Types
# =============================================================================


@dataclass
class SafetyCheckResult:
    """Result of a safety check."""

    allowed: bool
    reason: Optional[str] = None
    retry_after_seconds: Optional[int] = None


@dataclass
class RateLimitStatus:
    """Current rate limit status for a tenant/operation."""

    count: int
    limit: int
    remaining: int
    reset_at: datetime
    is_limited: bool


# =============================================================================
# Service
# =============================================================================


class ActionSafetyService:
    """
    Service for enforcing AI action safety guardrails.

    Provides:
    - Rate limiting per tenant/operation type
    - Cooldown windows per entity
    - Safety event logging

    SECURITY: All checks are per-tenant, tenant_id from JWT only.
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
        billing_tier: str = "free",
    ):
        """
        Initialize safety service.

        Args:
            db_session: Database session
            tenant_id: Tenant ID (from JWT only)
            billing_tier: Tenant's billing tier for limit lookup
        """
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id
        self.billing_tier = billing_tier

    # =========================================================================
    # Rate Limiting
    # =========================================================================

    def check_rate_limit(
        self,
        operation_type: str,
        correlation_id: Optional[str] = None,
    ) -> SafetyCheckResult:
        """
        Check if operation is within rate limits.

        Does NOT consume quota - use consume_rate_limit() after successful operation.

        Args:
            operation_type: Type of operation (action_execution, insight_generation, etc.)
            correlation_id: Optional correlation ID for tracing

        Returns:
            SafetyCheckResult indicating if operation is allowed
        """
        limit = self._get_limit(operation_type)

        # Unlimited
        if limit == -1:
            return SafetyCheckResult(allowed=True)

        # Not allowed for tier
        if limit == 0:
            self._log_safety_event(
                event_type="rate_limit_hit",
                operation_type=operation_type,
                reason=f"Operation '{operation_type}' not available on {self.billing_tier} tier",
                correlation_id=correlation_id,
            )
            return SafetyCheckResult(
                allowed=False,
                reason=f"Operation not available on your plan",
            )

        # Get current count
        window_start = self._get_window_start()
        rate_limit = self._get_or_create_rate_limit(operation_type, window_start, limit)

        if rate_limit.count >= limit:
            retry_after = int((window_start + timedelta(hours=1) - datetime.now(timezone.utc)).total_seconds())
            self._log_safety_event(
                event_type="rate_limit_hit",
                operation_type=operation_type,
                reason=f"Rate limit exceeded: {rate_limit.count}/{limit} per hour",
                event_metadata={"count": rate_limit.count, "limit": limit},
                correlation_id=correlation_id,
            )
            return SafetyCheckResult(
                allowed=False,
                reason=f"Rate limit exceeded ({rate_limit.count}/{limit} per hour)",
                retry_after_seconds=max(retry_after, 0),
            )

        return SafetyCheckResult(allowed=True)

    def consume_rate_limit(self, operation_type: str) -> None:
        """
        Consume one unit of rate limit quota.

        Call this AFTER a successful operation.

        Args:
            operation_type: Type of operation
        """
        limit = self._get_limit(operation_type)
        if limit == -1:
            return  # Unlimited, no tracking needed

        window_start = self._get_window_start()
        rate_limit = self._get_or_create_rate_limit(operation_type, window_start, limit)

        rate_limit.count += 1
        rate_limit.updated_at = datetime.now(timezone.utc)
        self.db.flush()

    def get_rate_limit_status(self, operation_type: str) -> RateLimitStatus:
        """
        Get current rate limit status.

        Args:
            operation_type: Type of operation

        Returns:
            RateLimitStatus with current usage
        """
        limit = self._get_limit(operation_type)
        window_start = self._get_window_start()
        reset_at = window_start + timedelta(hours=1)

        if limit == -1:
            return RateLimitStatus(
                count=0,
                limit=-1,
                remaining=-1,
                reset_at=reset_at,
                is_limited=False,
            )

        rate_limit = (
            self.db.query(AIRateLimit)
            .filter(
                AIRateLimit.tenant_id == self.tenant_id,
                AIRateLimit.operation_type == operation_type,
                AIRateLimit.window_start == window_start,
            )
            .first()
        )

        count = rate_limit.count if rate_limit else 0
        return RateLimitStatus(
            count=count,
            limit=limit,
            remaining=max(limit - count, 0),
            reset_at=reset_at,
            is_limited=count >= limit,
        )

    def _get_limit(self, operation_type: str) -> int:
        """Get rate limit for operation type based on billing tier."""
        tier_limits = DEFAULT_RATE_LIMITS.get(self.billing_tier, DEFAULT_RATE_LIMITS["free"])
        return tier_limits.get(operation_type, 0)

    def _get_window_start(self) -> datetime:
        """Get the start of the current hourly window."""
        now = datetime.now(timezone.utc)
        return now.replace(minute=0, second=0, microsecond=0)

    def _get_or_create_rate_limit(
        self,
        operation_type: str,
        window_start: datetime,
        limit: int,
    ) -> AIRateLimit:
        """Get or create rate limit record for current window."""
        rate_limit = (
            self.db.query(AIRateLimit)
            .filter(
                AIRateLimit.tenant_id == self.tenant_id,
                AIRateLimit.operation_type == operation_type,
                AIRateLimit.window_start == window_start,
            )
            .first()
        )

        if not rate_limit:
            rate_limit = AIRateLimit(
                tenant_id=self.tenant_id,
                operation_type=operation_type,
                window_start=window_start,
                window_type="hourly",
                count=0,
                limit_value=limit,
            )
            self.db.add(rate_limit)
            self.db.flush()

        return rate_limit

    # =========================================================================
    # Cooldown Management
    # =========================================================================

    def check_cooldown(
        self,
        platform: str,
        entity_type: str,
        entity_id: str,
        action_type: str,
        correlation_id: Optional[str] = None,
    ) -> SafetyCheckResult:
        """
        Check if entity is in cooldown for this action type.

        Args:
            platform: Target platform (meta, google, shopify)
            entity_type: Entity type (campaign, ad_set, ad)
            entity_id: Entity ID on external platform
            action_type: Type of action
            correlation_id: Optional correlation ID

        Returns:
            SafetyCheckResult indicating if action is allowed
        """
        cooldown = (
            self.db.query(AICooldown)
            .filter(
                AICooldown.tenant_id == self.tenant_id,
                AICooldown.platform == platform,
                AICooldown.entity_type == entity_type,
                AICooldown.entity_id == entity_id,
                AICooldown.action_type == action_type,
            )
            .first()
        )

        if cooldown and cooldown.cooldown_until > datetime.now(timezone.utc):
            remaining = int((cooldown.cooldown_until - datetime.now(timezone.utc)).total_seconds())
            self._log_safety_event(
                event_type="cooldown_enforced",
                operation_type="action_execution",
                entity_id=entity_id,
                reason=f"Entity in cooldown until {cooldown.cooldown_until.isoformat()}",
                event_metadata={
                    "platform": platform,
                    "entity_type": entity_type,
                    "action_type": action_type,
                    "remaining_seconds": remaining,
                },
                correlation_id=correlation_id,
            )
            return SafetyCheckResult(
                allowed=False,
                reason=f"Entity in cooldown ({remaining}s remaining)",
                retry_after_seconds=remaining,
            )

        return SafetyCheckResult(allowed=True)

    def record_action(
        self,
        platform: str,
        entity_type: str,
        entity_id: str,
        action_type: str,
    ) -> None:
        """
        Record an action and set cooldown.

        Call this AFTER a successful action execution.

        Args:
            platform: Target platform
            entity_type: Entity type
            entity_id: Entity ID
            action_type: Type of action executed
        """
        cooldown_seconds = DEFAULT_COOLDOWNS.get(action_type, DEFAULT_COOLDOWNS["default"])
        now = datetime.now(timezone.utc)
        cooldown_until = now + timedelta(seconds=cooldown_seconds)

        cooldown = (
            self.db.query(AICooldown)
            .filter(
                AICooldown.tenant_id == self.tenant_id,
                AICooldown.platform == platform,
                AICooldown.entity_type == entity_type,
                AICooldown.entity_id == entity_id,
                AICooldown.action_type == action_type,
            )
            .first()
        )

        if cooldown:
            cooldown.last_action_at = now
            cooldown.cooldown_until = cooldown_until
        else:
            cooldown = AICooldown(
                tenant_id=self.tenant_id,
                platform=platform,
                entity_type=entity_type,
                entity_id=entity_id,
                action_type=action_type,
                last_action_at=now,
                cooldown_until=cooldown_until,
            )
            self.db.add(cooldown)

        self.db.flush()

    # =========================================================================
    # Combined Safety Check
    # =========================================================================

    def check_action_safety(
        self,
        platform: str,
        entity_type: str,
        entity_id: str,
        action_type: str,
        action_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> SafetyCheckResult:
        """
        Perform all safety checks for an action.

        Checks:
        1. Rate limits
        2. Cooldown windows

        Args:
            platform: Target platform
            entity_type: Entity type
            entity_id: Entity ID
            action_type: Type of action
            action_id: Optional action ID for logging
            correlation_id: Optional correlation ID

        Returns:
            SafetyCheckResult - allowed only if ALL checks pass
        """
        # Check rate limit
        rate_result = self.check_rate_limit("action_execution", correlation_id)
        if not rate_result.allowed:
            if action_id:
                self._log_safety_event(
                    event_type="action_blocked",
                    operation_type="action_execution",
                    entity_id=entity_id,
                    action_id=action_id,
                    reason=f"Rate limit: {rate_result.reason}",
                    correlation_id=correlation_id,
                )
            return rate_result

        # Check cooldown
        cooldown_result = self.check_cooldown(
            platform, entity_type, entity_id, action_type, correlation_id
        )
        if not cooldown_result.allowed:
            if action_id:
                self._log_safety_event(
                    event_type="action_blocked",
                    operation_type="action_execution",
                    entity_id=entity_id,
                    action_id=action_id,
                    reason=f"Cooldown: {cooldown_result.reason}",
                    correlation_id=correlation_id,
                )
            return cooldown_result

        return SafetyCheckResult(allowed=True)

    def record_action_execution(
        self,
        platform: str,
        entity_type: str,
        entity_id: str,
        action_type: str,
    ) -> None:
        """
        Record successful action execution.

        Updates rate limit counter and cooldown.

        Args:
            platform: Target platform
            entity_type: Entity type
            entity_id: Entity ID
            action_type: Type of action
        """
        self.consume_rate_limit("action_execution")
        self.record_action(platform, entity_type, entity_id, action_type)

    # =========================================================================
    # Safety Event Logging
    # =========================================================================

    def _log_safety_event(
        self,
        event_type: str,
        operation_type: str,
        reason: str,
        entity_id: Optional[str] = None,
        action_id: Optional[str] = None,
        event_metadata: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        Log a safety event (append-only).

        Args:
            event_type: Type of event (rate_limit_hit, cooldown_enforced, action_blocked)
            operation_type: Type of operation
            reason: Human-readable reason
            entity_id: Optional entity ID
            action_id: Optional action ID
            event_metadata: Optional additional data
            correlation_id: Optional correlation ID
        """
        event = AISafetyEvent(
            tenant_id=self.tenant_id,
            event_type=event_type,
            operation_type=operation_type,
            entity_id=entity_id,
            action_id=action_id,
            reason=reason,
            event_metadata=event_metadata or {},
            correlation_id=correlation_id,
        )
        self.db.add(event)
        self.db.flush()

        logger.info(
            f"Safety event: {event_type}",
            extra={
                "tenant_id": self.tenant_id,
                "event_type": event_type,
                "operation_type": operation_type,
                "entity_id": entity_id,
                "action_id": action_id,
                "reason": reason,
                "correlation_id": correlation_id,
            },
        )

    def log_action_blocked(
        self,
        action_id: str,
        reason: str,
        blocked_by: str,
        event_metadata: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        Log an action that was blocked by safety guardrails.

        Args:
            action_id: ID of the blocked action
            reason: Why action was blocked
            blocked_by: What blocked it (rate_limit, cooldown, kill_switch, etc.)
            event_metadata: Additional context
            correlation_id: Optional correlation ID
        """
        self._log_safety_event(
            event_type="action_blocked",
            operation_type="action_execution",
            action_id=action_id,
            reason=reason,
            event_metadata={"blocked_by": blocked_by, **(event_metadata or {})},
            correlation_id=correlation_id,
        )

    def log_action_suppressed(
        self,
        reason: str,
        event_metadata: Optional[dict] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """
        Log an action that was suppressed before creation.

        Args:
            reason: Why action was suppressed
            event_metadata: Additional context
            correlation_id: Optional correlation ID
        """
        self._log_safety_event(
            event_type="action_suppressed",
            operation_type="action_execution",
            reason=reason,
            event_metadata=event_metadata,
            correlation_id=correlation_id,
        )
