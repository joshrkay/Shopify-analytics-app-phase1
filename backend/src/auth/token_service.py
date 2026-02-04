"""
Token and session management service.

This module provides:
- Session tracking and validation
- Token/session revocation
- Revocation list management
- Session activity tracking

IMPORTANT: This does NOT issue tokens (Clerk is the auth authority).
This service manages the local state for:
- Tracking active sessions
- Revoking sessions before their natural expiration
- Maintaining a revocation list for security

Token Revocability:
Since JWTs are stateless, we maintain a revocation list to:
- Immediately invalidate sessions on logout
- Revoke sessions when user is deactivated
- Revoke sessions on security events (password change, etc.)
"""

import os
import time
import logging
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Set, List, Any
from threading import Lock
from enum import Enum

logger = logging.getLogger(__name__)


class RevocationReason(str, Enum):
    """Reasons for token/session revocation."""
    LOGOUT = "logout"
    USER_DEACTIVATED = "user_deactivated"
    SESSION_EXPIRED = "session_expired"
    SECURITY_EVENT = "security_event"
    ADMIN_REVOKE = "admin_revoke"
    PASSWORD_CHANGED = "password_changed"
    ALL_SESSIONS = "all_sessions"


@dataclass
class SessionInfo:
    """
    Information about an active session.

    Used for tracking session activity and revocation.
    """

    session_id: str
    clerk_user_id: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def idle_time_seconds(self) -> float:
        """Get seconds since last activity."""
        return (datetime.now(timezone.utc) - self.last_seen_at).total_seconds()


@dataclass
class RevocationEntry:
    """
    Entry in the revocation list.

    Can revoke:
    - Specific session (by session_id)
    - All sessions for a user (by clerk_user_id)
    - All sessions before a timestamp
    """

    identifier: str  # session_id or clerk_user_id
    identifier_type: str  # "session" or "user"
    revoked_at: datetime
    reason: RevocationReason
    revoked_by: Optional[str] = None  # clerk_user_id of admin who revoked
    revoke_tokens_before: Optional[datetime] = None  # For "all sessions" revocation


class TokenService:
    """
    Service for managing tokens and sessions.

    Features:
    - Session tracking with activity monitoring
    - Token/session revocation
    - Revocation list with TTL-based cleanup
    - Thread-safe operations

    Usage:
        token_service = TokenService()

        # Check if session is revoked
        if token_service.is_revoked(session_id=sid, clerk_user_id=user_id):
            raise AuthenticationError("Session has been revoked")

        # Record session activity
        token_service.record_activity(session_id=sid, clerk_user_id=user_id)

        # Revoke a session
        token_service.revoke_session(session_id=sid, reason=RevocationReason.LOGOUT)

        # Revoke all sessions for a user
        token_service.revoke_all_user_sessions(clerk_user_id=user_id)
    """

    # Default TTL for revocation entries (24 hours)
    # After this, the JWT would have expired anyway
    DEFAULT_REVOCATION_TTL = 86400

    # Cleanup interval for expired entries
    CLEANUP_INTERVAL = 3600  # 1 hour

    def __init__(
        self,
        revocation_ttl: int = DEFAULT_REVOCATION_TTL,
        use_redis: bool = False,
        redis_url: Optional[str] = None,
    ):
        """
        Initialize token service.

        Args:
            revocation_ttl: TTL for revocation entries in seconds
            use_redis: Whether to use Redis for storage (for distributed systems)
            redis_url: Redis URL (required if use_redis is True)
        """
        self._revocation_ttl = revocation_ttl
        self._use_redis = use_redis
        self._redis_url = redis_url or os.getenv("REDIS_URL")

        # In-memory storage (fallback or for single-instance deployments)
        self._revoked_sessions: Dict[str, RevocationEntry] = {}
        self._revoked_users: Dict[str, RevocationEntry] = {}
        self._active_sessions: Dict[str, SessionInfo] = {}
        self._lock = Lock()
        self._last_cleanup = time.time()

        # Redis client (lazy initialization)
        self._redis_client = None

        logger.info(
            "Initialized TokenService",
            extra={
                "use_redis": use_redis,
                "revocation_ttl": revocation_ttl,
            },
        )

    def _get_redis(self):
        """Get Redis client (lazy initialization)."""
        if not self._use_redis:
            return None

        if self._redis_client is None:
            try:
                import redis
                self._redis_client = redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                )
            except ImportError:
                logger.warning("redis package not installed, falling back to in-memory")
                self._use_redis = False
                return None
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                self._use_redis = False
                return None

        return self._redis_client

    def _session_key(self, session_id: str) -> str:
        """Generate storage key for session."""
        return f"revoked:session:{session_id}"

    def _user_key(self, clerk_user_id: str) -> str:
        """Generate storage key for user."""
        return f"revoked:user:{clerk_user_id}"

    def _maybe_cleanup(self) -> None:
        """Periodically cleanup expired entries."""
        now = time.time()
        if now - self._last_cleanup < self.CLEANUP_INTERVAL:
            return

        with self._lock:
            if now - self._last_cleanup < self.CLEANUP_INTERVAL:
                return  # Double-check after acquiring lock

            self._last_cleanup = now
            cutoff = datetime.now(timezone.utc) - timedelta(seconds=self._revocation_ttl)

            # Clean up revoked sessions
            expired = [
                sid for sid, entry in self._revoked_sessions.items()
                if entry.revoked_at < cutoff
            ]
            for sid in expired:
                del self._revoked_sessions[sid]

            # Clean up revoked users
            expired_users = [
                uid for uid, entry in self._revoked_users.items()
                if entry.revoked_at < cutoff
            ]
            for uid in expired_users:
                del self._revoked_users[uid]

            # Clean up expired sessions
            expired_active = [
                sid for sid, info in self._active_sessions.items()
                if info.is_expired
            ]
            for sid in expired_active:
                del self._active_sessions[sid]

            if expired or expired_users or expired_active:
                logger.debug(
                    "Cleaned up revocation entries",
                    extra={
                        "sessions_removed": len(expired),
                        "users_removed": len(expired_users),
                        "active_expired": len(expired_active),
                    },
                )

    def is_revoked(
        self,
        session_id: Optional[str] = None,
        clerk_user_id: Optional[str] = None,
        token_issued_at: Optional[datetime] = None,
    ) -> bool:
        """
        Check if a session or user has been revoked.

        Args:
            session_id: Session ID to check
            clerk_user_id: User ID to check (for all-session revocation)
            token_issued_at: Token issue time (for checking revoke-before)

        Returns:
            True if revoked, False otherwise
        """
        self._maybe_cleanup()

        redis = self._get_redis()

        # Check session-specific revocation
        if session_id:
            if redis:
                if redis.exists(self._session_key(session_id)):
                    return True
            else:
                with self._lock:
                    if session_id in self._revoked_sessions:
                        return True

        # Check user-level revocation
        if clerk_user_id:
            if redis:
                key = self._user_key(clerk_user_id)
                revoke_data = redis.hgetall(key)
                if revoke_data:
                    # Check if token was issued before revocation
                    revoke_before = revoke_data.get("revoke_tokens_before")
                    if revoke_before and token_issued_at:
                        revoke_dt = datetime.fromisoformat(revoke_before)
                        if token_issued_at < revoke_dt:
                            return True
                    elif not revoke_before:
                        # All sessions revoked without time check
                        return True
            else:
                with self._lock:
                    if clerk_user_id in self._revoked_users:
                        entry = self._revoked_users[clerk_user_id]
                        if entry.revoke_tokens_before and token_issued_at:
                            if token_issued_at < entry.revoke_tokens_before:
                                return True
                        elif not entry.revoke_tokens_before:
                            return True

        return False

    def revoke_session(
        self,
        session_id: str,
        reason: RevocationReason = RevocationReason.LOGOUT,
        revoked_by: Optional[str] = None,
    ) -> None:
        """
        Revoke a specific session.

        Args:
            session_id: Session ID to revoke
            reason: Reason for revocation
            revoked_by: clerk_user_id of user/admin who initiated revocation
        """
        entry = RevocationEntry(
            identifier=session_id,
            identifier_type="session",
            revoked_at=datetime.now(timezone.utc),
            reason=reason,
            revoked_by=revoked_by,
        )

        redis = self._get_redis()

        if redis:
            key = self._session_key(session_id)
            redis.hset(key, mapping={
                "revoked_at": entry.revoked_at.isoformat(),
                "reason": reason.value,
                "revoked_by": revoked_by or "",
            })
            redis.expire(key, self._revocation_ttl)
        else:
            with self._lock:
                self._revoked_sessions[session_id] = entry
                # Remove from active sessions
                self._active_sessions.pop(session_id, None)

        logger.info(
            "Revoked session",
            extra={
                "session_id": session_id[:20] + "..." if len(session_id) > 20 else session_id,
                "reason": reason.value,
            },
        )

    def revoke_all_user_sessions(
        self,
        clerk_user_id: str,
        reason: RevocationReason = RevocationReason.ALL_SESSIONS,
        revoked_by: Optional[str] = None,
        revoke_tokens_before: Optional[datetime] = None,
    ) -> None:
        """
        Revoke all sessions for a user.

        Args:
            clerk_user_id: User ID to revoke all sessions for
            reason: Reason for revocation
            revoked_by: clerk_user_id of admin who initiated
            revoke_tokens_before: Only revoke tokens issued before this time
        """
        revoke_before = revoke_tokens_before or datetime.now(timezone.utc)

        entry = RevocationEntry(
            identifier=clerk_user_id,
            identifier_type="user",
            revoked_at=datetime.now(timezone.utc),
            reason=reason,
            revoked_by=revoked_by,
            revoke_tokens_before=revoke_before,
        )

        redis = self._get_redis()

        if redis:
            key = self._user_key(clerk_user_id)
            redis.hset(key, mapping={
                "revoked_at": entry.revoked_at.isoformat(),
                "reason": reason.value,
                "revoked_by": revoked_by or "",
                "revoke_tokens_before": revoke_before.isoformat(),
            })
            redis.expire(key, self._revocation_ttl)
        else:
            with self._lock:
                self._revoked_users[clerk_user_id] = entry
                # Remove all active sessions for user
                to_remove = [
                    sid for sid, info in self._active_sessions.items()
                    if info.clerk_user_id == clerk_user_id
                ]
                for sid in to_remove:
                    del self._active_sessions[sid]

        logger.info(
            "Revoked all sessions for user",
            extra={
                "clerk_user_id": clerk_user_id[:20] + "...",
                "reason": reason.value,
            },
        )

    def record_activity(
        self,
        session_id: str,
        clerk_user_id: str,
        expires_at: datetime,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> None:
        """
        Record session activity for tracking.

        Args:
            session_id: Session ID
            clerk_user_id: User ID
            expires_at: Token expiration time
            ip_address: Client IP address
            user_agent: Client user agent
        """
        now = datetime.now(timezone.utc)

        with self._lock:
            if session_id in self._active_sessions:
                # Update existing session
                self._active_sessions[session_id].last_seen_at = now
                if ip_address:
                    self._active_sessions[session_id].ip_address = ip_address
            else:
                # Create new session record
                self._active_sessions[session_id] = SessionInfo(
                    session_id=session_id,
                    clerk_user_id=clerk_user_id,
                    created_at=now,
                    last_seen_at=now,
                    expires_at=expires_at,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )

    def get_active_sessions(
        self,
        clerk_user_id: str,
    ) -> List[SessionInfo]:
        """
        Get all active sessions for a user.

        Args:
            clerk_user_id: User ID

        Returns:
            List of active SessionInfo objects
        """
        self._maybe_cleanup()

        with self._lock:
            return [
                info for info in self._active_sessions.values()
                if info.clerk_user_id == clerk_user_id and not info.is_expired
            ]

    def get_session_info(
        self,
        session_id: str,
    ) -> Optional[SessionInfo]:
        """
        Get information about a specific session.

        Args:
            session_id: Session ID

        Returns:
            SessionInfo or None if not found
        """
        with self._lock:
            return self._active_sessions.get(session_id)

    def clear_revocation_list(self) -> None:
        """
        Clear all revocation entries (for testing).

        WARNING: This should only be used in tests!
        """
        redis = self._get_redis()

        if redis:
            # Clear Redis keys matching our patterns
            for key in redis.scan_iter("revoked:*"):
                redis.delete(key)
        else:
            with self._lock:
                self._revoked_sessions.clear()
                self._revoked_users.clear()

        logger.warning("Cleared all revocation entries")


# Singleton instance
_token_service: Optional[TokenService] = None
_token_service_lock = Lock()


def get_token_service() -> TokenService:
    """
    Get the singleton TokenService instance.

    Returns:
        TokenService instance
    """
    global _token_service

    with _token_service_lock:
        if _token_service is None:
            use_redis = os.getenv("USE_REDIS_REVOCATION", "false").lower() == "true"
            _token_service = TokenService(use_redis=use_redis)
        return _token_service
