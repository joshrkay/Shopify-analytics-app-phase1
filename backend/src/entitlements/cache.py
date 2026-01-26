"""
Entitlement Cache - Redis-backed cache with real-time invalidation.

Provides:
- EntitlementCache: Redis cache for tenant entitlements
- Real-time invalidation on billing state changes
- TTL-based expiration for automatic refresh

CRITICAL: Billing state changes MUST invalidate cached entitlements immediately.
"""

import json
import logging
import os
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List
from threading import Lock
import hashlib

logger = logging.getLogger(__name__)

# Cache configuration
DEFAULT_CACHE_TTL_SECONDS = 300  # 5 minutes
SHORT_CACHE_TTL_SECONDS = 60  # 1 minute for grace period states
INVALIDATION_CHANNEL = "entitlements:invalidations"


@dataclass
class CachedEntitlement:
    """Cached entitlement data for a tenant."""

    tenant_id: str
    plan_id: str
    plan_name: str
    billing_state: str
    access_level: str
    enabled_features: List[str]
    restricted_features: List[str]
    limits: Dict[str, int]
    warnings: List[str]
    grace_period_ends_on: Optional[str] = None
    current_period_end: Optional[str] = None
    cached_at: str = ""
    version: str = "1"

    def to_json(self) -> str:
        """Serialize to JSON."""
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str) -> 'CachedEntitlement':
        """Deserialize from JSON."""
        return cls(**json.loads(data))

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if cache entry has expired."""
        if not self.cached_at:
            return True
        cached_time = datetime.fromisoformat(self.cached_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        return (now - cached_time).total_seconds() > ttl_seconds


class RedisClient:
    """
    Redis client wrapper with connection pooling and fallback.

    Provides graceful degradation when Redis is unavailable.
    """

    _instance: Optional['RedisClient'] = None
    _lock = Lock()

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._redis = None
        self._available = False
        self._connect()
        self._initialized = True

    def _connect(self) -> None:
        """Connect to Redis if configured."""
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            logger.info("REDIS_URL not configured - entitlement caching disabled")
            return

        try:
            import redis
            self._redis = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0,
            )
            # Test connection
            self._redis.ping()
            self._available = True
            logger.info("Redis connection established for entitlement cache")
        except ImportError:
            logger.warning("redis package not installed - caching disabled")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e} - caching disabled")

    @property
    def available(self) -> bool:
        """Check if Redis is available."""
        return self._available and self._redis is not None

    def get(self, key: str) -> Optional[str]:
        """Get value from Redis."""
        if not self.available:
            return None
        try:
            return self._redis.get(key)
        except Exception as e:
            logger.warning(f"Redis GET failed: {e}")
            return None

    def set(self, key: str, value: str, ttl_seconds: int) -> bool:
        """Set value in Redis with TTL."""
        if not self.available:
            return False
        try:
            self._redis.setex(key, ttl_seconds, value)
            return True
        except Exception as e:
            logger.warning(f"Redis SET failed: {e}")
            return False

    def delete(self, *keys: str) -> int:
        """Delete keys from Redis."""
        if not self.available or not keys:
            return 0
        try:
            return self._redis.delete(*keys)
        except Exception as e:
            logger.warning(f"Redis DELETE failed: {e}")
            return 0

    def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching pattern."""
        if not self.available:
            return 0
        try:
            keys = list(self._redis.scan_iter(pattern))
            if keys:
                return self._redis.delete(*keys)
            return 0
        except Exception as e:
            logger.warning(f"Redis DELETE pattern failed: {e}")
            return 0

    def publish(self, channel: str, message: str) -> int:
        """Publish message to channel."""
        if not self.available:
            return 0
        try:
            return self._redis.publish(channel, message)
        except Exception as e:
            logger.warning(f"Redis PUBLISH failed: {e}")
            return 0


class InMemoryCache:
    """
    In-memory fallback cache when Redis is unavailable.

    Thread-safe with basic TTL support.
    """

    def __init__(self, max_size: int = 10000):
        self._cache: Dict[str, tuple[str, datetime]] = {}
        self._lock = Lock()
        self._max_size = max_size

    def get(self, key: str, ttl_seconds: int) -> Optional[str]:
        """Get value if not expired."""
        with self._lock:
            if key not in self._cache:
                return None
            value, cached_at = self._cache[key]
            if (datetime.now(timezone.utc) - cached_at).total_seconds() > ttl_seconds:
                del self._cache[key]
                return None
            return value

    def set(self, key: str, value: str) -> None:
        """Set value with current timestamp."""
        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self._max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (value, datetime.now(timezone.utc))

    def delete(self, key: str) -> bool:
        """Delete a key."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def delete_pattern(self, pattern: str) -> int:
        """Delete keys matching pattern (simple prefix match)."""
        import fnmatch
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if fnmatch.fnmatch(k, pattern)]
            for key in keys_to_delete:
                del self._cache[key]
            return len(keys_to_delete)

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()


class EntitlementCache:
    """
    Caching layer for tenant entitlements.

    Uses Redis when available, falls back to in-memory cache.
    Provides real-time invalidation via Redis pub/sub or direct deletion.

    Usage:
        cache = EntitlementCache()

        # Get cached entitlement
        cached = cache.get(tenant_id)
        if cached:
            return cached

        # Compute and cache
        entitlement = compute_entitlement(tenant_id)
        cache.set(tenant_id, entitlement)

        # Invalidate on billing state change
        cache.invalidate(tenant_id)
    """

    CACHE_KEY_PREFIX = "entitlement:"
    FEATURE_FLAGS_PREFIX = "feature_flags:"

    def __init__(self):
        """Initialize cache with Redis or in-memory fallback."""
        self._redis = RedisClient()
        self._memory_cache = InMemoryCache()
        self._ttl_seconds = int(os.getenv("ENTITLEMENT_CACHE_TTL", DEFAULT_CACHE_TTL_SECONDS))

    def _cache_key(self, tenant_id: str) -> str:
        """Generate cache key for tenant."""
        return f"{self.CACHE_KEY_PREFIX}{tenant_id}"

    def _feature_flags_key(self, tenant_id: str) -> str:
        """Generate feature flags override key."""
        return f"{self.FEATURE_FLAGS_PREFIX}{tenant_id}"

    def _get_ttl(self, billing_state: str) -> int:
        """Get TTL based on billing state (shorter for volatile states)."""
        volatile_states = {"grace_period", "past_due", "frozen"}
        if billing_state in volatile_states:
            return SHORT_CACHE_TTL_SECONDS
        return self._ttl_seconds

    def get(self, tenant_id: str) -> Optional[CachedEntitlement]:
        """
        Get cached entitlement for tenant.

        Args:
            tenant_id: Tenant identifier

        Returns:
            CachedEntitlement or None if not cached/expired
        """
        key = self._cache_key(tenant_id)

        # Try Redis first
        if self._redis.available:
            data = self._redis.get(key)
            if data:
                try:
                    cached = CachedEntitlement.from_json(data)
                    logger.debug(f"Cache hit (Redis) for tenant {tenant_id}")
                    return cached
                except Exception as e:
                    logger.warning(f"Failed to deserialize cached entitlement: {e}")

        # Fall back to in-memory
        data = self._memory_cache.get(key, self._ttl_seconds)
        if data:
            try:
                cached = CachedEntitlement.from_json(data)
                logger.debug(f"Cache hit (memory) for tenant {tenant_id}")
                return cached
            except Exception as e:
                logger.warning(f"Failed to deserialize memory cached entitlement: {e}")

        logger.debug(f"Cache miss for tenant {tenant_id}")
        return None

    def set(self, tenant_id: str, entitlement: CachedEntitlement) -> bool:
        """
        Cache entitlement for tenant.

        Args:
            tenant_id: Tenant identifier
            entitlement: Entitlement data to cache

        Returns:
            True if cached successfully
        """
        key = self._cache_key(tenant_id)
        entitlement.cached_at = datetime.now(timezone.utc).isoformat()

        try:
            data = entitlement.to_json()
            ttl = self._get_ttl(entitlement.billing_state)

            # Cache in Redis
            if self._redis.available:
                self._redis.set(key, data, ttl)

            # Also cache in memory for redundancy
            self._memory_cache.set(key, data)

            logger.debug(f"Cached entitlement for tenant {tenant_id} (TTL: {ttl}s)")
            return True

        except Exception as e:
            logger.error(f"Failed to cache entitlement: {e}")
            return False

    def invalidate(self, tenant_id: str, reason: Optional[str] = None) -> bool:
        """
        Invalidate cached entitlement for tenant.

        CRITICAL: Must be called whenever billing state changes.

        Args:
            tenant_id: Tenant identifier
            reason: Optional reason for audit logging

        Returns:
            True if invalidation was successful
        """
        key = self._cache_key(tenant_id)
        deleted = False

        # Delete from Redis
        if self._redis.available:
            count = self._redis.delete(key)
            if count > 0:
                deleted = True
                # Publish invalidation event
                self._redis.publish(
                    INVALIDATION_CHANNEL,
                    json.dumps({
                        "tenant_id": tenant_id,
                        "reason": reason,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                )

        # Delete from memory
        if self._memory_cache.delete(key):
            deleted = True

        if deleted:
            logger.info(
                f"Invalidated entitlement cache for tenant {tenant_id}",
                extra={"reason": reason}
            )

        return deleted

    def invalidate_all(self, reason: Optional[str] = None) -> int:
        """
        Invalidate all cached entitlements.

        Use with caution - only for config reloads or emergencies.

        Args:
            reason: Reason for mass invalidation

        Returns:
            Number of entries invalidated
        """
        count = 0

        # Clear Redis
        if self._redis.available:
            count = self._redis.delete_pattern(f"{self.CACHE_KEY_PREFIX}*")
            self._redis.publish(
                INVALIDATION_CHANNEL,
                json.dumps({
                    "tenant_id": "*",
                    "reason": reason or "mass_invalidation",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
            )

        # Clear memory
        self._memory_cache.clear()

        logger.warning(
            f"Mass invalidation of entitlement cache ({count} entries)",
            extra={"reason": reason}
        )

        return count

    def get_feature_flags_override(self, tenant_id: str) -> Dict[str, bool]:
        """
        Get feature flag overrides for tenant (admin-only emergency overrides).

        Args:
            tenant_id: Tenant identifier

        Returns:
            Dict of feature_key -> enabled
        """
        key = self._feature_flags_key(tenant_id)

        if self._redis.available:
            data = self._redis.get(key)
            if data:
                try:
                    return json.loads(data)
                except Exception:
                    pass

        return {}

    def set_feature_flag_override(
        self,
        tenant_id: str,
        feature_key: str,
        enabled: bool,
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        """
        Set emergency feature flag override (admin-only).

        Args:
            tenant_id: Tenant identifier
            feature_key: Feature to override
            enabled: Whether to enable or disable
            ttl_seconds: Optional TTL (defaults to 24 hours)

        Returns:
            True if set successfully
        """
        if not self._redis.available:
            logger.warning("Feature flag overrides require Redis")
            return False

        key = self._feature_flags_key(tenant_id)
        ttl = ttl_seconds or 86400  # 24 hours default

        # Get existing overrides
        overrides = self.get_feature_flags_override(tenant_id)
        overrides[feature_key] = enabled

        try:
            self._redis.set(key, json.dumps(overrides), ttl)

            # Invalidate entitlement cache to pick up the override
            self.invalidate(tenant_id, reason=f"feature_flag_override:{feature_key}={enabled}")

            logger.info(
                f"Set feature flag override: {feature_key}={enabled} for tenant {tenant_id}",
                extra={"ttl_seconds": ttl}
            )
            return True

        except Exception as e:
            logger.error(f"Failed to set feature flag override: {e}")
            return False

    def clear_feature_flag_override(
        self,
        tenant_id: str,
        feature_key: Optional[str] = None,
    ) -> bool:
        """
        Clear feature flag override(s).

        Args:
            tenant_id: Tenant identifier
            feature_key: Specific feature to clear (None = clear all)

        Returns:
            True if cleared successfully
        """
        if not self._redis.available:
            return False

        key = self._feature_flags_key(tenant_id)

        if feature_key is None:
            # Clear all overrides
            self._redis.delete(key)
        else:
            # Clear specific override
            overrides = self.get_feature_flags_override(tenant_id)
            if feature_key in overrides:
                del overrides[feature_key]
                if overrides:
                    self._redis.set(key, json.dumps(overrides), 86400)
                else:
                    self._redis.delete(key)

        # Invalidate entitlement cache
        self.invalidate(tenant_id, reason=f"feature_flag_override_cleared:{feature_key or 'all'}")

        return True


# Module-level singleton
_cache_instance: Optional[EntitlementCache] = None
_cache_lock = Lock()


def get_entitlement_cache() -> EntitlementCache:
    """Get the singleton EntitlementCache instance."""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = EntitlementCache()
    return _cache_instance


def invalidate_tenant_entitlements(tenant_id: str, reason: Optional[str] = None) -> bool:
    """
    Convenience function to invalidate tenant entitlements.

    Call this whenever billing state changes.

    Args:
        tenant_id: Tenant identifier
        reason: Reason for invalidation

    Returns:
        True if invalidation was successful
    """
    return get_entitlement_cache().invalidate(tenant_id, reason)


def on_billing_state_change(
    tenant_id: str,
    old_state: str,
    new_state: str,
    plan_id: Optional[str] = None,
) -> None:
    """
    Handle billing state change by invalidating cache.

    CRITICAL: This MUST be called from webhook handlers and billing service
    whenever subscription status changes.

    Args:
        tenant_id: Tenant identifier
        old_state: Previous billing state
        new_state: New billing state
        plan_id: Optional plan ID if changed
    """
    reason = f"billing_state_change:{old_state}->{new_state}"
    if plan_id:
        reason += f":plan={plan_id}"

    invalidate_tenant_entitlements(tenant_id, reason)

    logger.info(
        "Billing state change - cache invalidated",
        extra={
            "tenant_id": tenant_id,
            "old_state": old_state,
            "new_state": new_state,
            "plan_id": plan_id,
        }
    )
