"""
Retry policy and backoff calculation for ingestion jobs.

Implements error-aware retry logic:
- 4xx auth errors (401, 403) -> fail immediately (no retry)
- 429 rate limit -> retry with backoff (respect Retry-After)
- 5xx server errors -> retry with exponential backoff + jitter
- After max retries (5) -> move to dead letter queue

Backoff formula: base_delay * (2^attempt) + random_jitter
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

# Retry configuration constants
MAX_RETRIES = 5
BASE_DELAY_SECONDS = 60.0  # 1 minute base delay
MAX_DELAY_SECONDS = 3600.0  # 1 hour max delay
JITTER_FACTOR = 0.25  # +/- 25% jitter


class ErrorCategory(str, Enum):
    """Error classification for retry decisions."""
    AUTH_ERROR = "auth_error"  # 401, 403 - no retry
    RATE_LIMIT = "rate_limit"  # 429 - retry with Retry-After
    SERVER_ERROR = "server_error"  # 5xx - retry with backoff
    TIMEOUT = "timeout"  # Connection/read timeout - retry
    CONNECTION = "connection"  # Network errors - retry
    SYNC_FAILED = "sync_failed"  # Airbyte sync failure - retry
    UNKNOWN = "unknown"  # Unknown errors - limited retry


@dataclass(frozen=True)
class RetryPolicy:
    """
    Retry policy configuration.

    Attributes:
        max_retries: Maximum retry attempts before DLQ
        base_delay_seconds: Initial delay between retries
        max_delay_seconds: Maximum delay cap
        jitter_factor: Random jitter factor (0.25 = +/- 25%)
    """
    max_retries: int = MAX_RETRIES
    base_delay_seconds: float = BASE_DELAY_SECONDS
    max_delay_seconds: float = MAX_DELAY_SECONDS
    jitter_factor: float = JITTER_FACTOR


@dataclass
class RetryDecision:
    """
    Result of retry evaluation.

    Attributes:
        should_retry: Whether to retry the operation
        delay_seconds: Seconds to wait before retry (if retrying)
        next_retry_at: Absolute timestamp for next retry
        move_to_dlq: Whether to move to dead letter queue
        reason: Human-readable explanation
    """
    should_retry: bool
    delay_seconds: float
    next_retry_at: Optional[datetime]
    move_to_dlq: bool
    reason: str


def categorize_error(
    status_code: Optional[int],
    error_type: Optional[str] = None,
) -> ErrorCategory:
    """
    Categorize an error for retry decisions.

    Args:
        status_code: HTTP status code (if available)
        error_type: Error type string (for non-HTTP errors)

    Returns:
        ErrorCategory for the error
    """
    if status_code is not None:
        if status_code in (401, 403):
            return ErrorCategory.AUTH_ERROR
        if status_code == 429:
            return ErrorCategory.RATE_LIMIT
        if 500 <= status_code < 600:
            return ErrorCategory.SERVER_ERROR
        if 400 <= status_code < 500:
            # Other 4xx errors - don't retry
            return ErrorCategory.AUTH_ERROR

    if error_type:
        error_lower = error_type.lower()
        if "timeout" in error_lower:
            return ErrorCategory.TIMEOUT
        if "connection" in error_lower or "network" in error_lower:
            return ErrorCategory.CONNECTION
        if "auth" in error_lower:
            return ErrorCategory.AUTH_ERROR
        if "rate" in error_lower or "limit" in error_lower:
            return ErrorCategory.RATE_LIMIT
        if "sync" in error_lower:
            return ErrorCategory.SYNC_FAILED

    return ErrorCategory.UNKNOWN


def calculate_backoff(
    attempt: int,
    policy: RetryPolicy = RetryPolicy(),
    retry_after: Optional[int] = None,
) -> float:
    """
    Calculate backoff delay with exponential growth and jitter.

    Formula: min(base * 2^attempt + jitter, max_delay)

    Args:
        attempt: Current attempt number (0-indexed)
        policy: Retry policy configuration
        retry_after: Server-specified retry delay (overrides calculation)

    Returns:
        Delay in seconds before next retry
    """
    if retry_after is not None and retry_after > 0:
        # Respect server-specified Retry-After with small jitter
        jitter = random.uniform(-policy.jitter_factor * retry_after, policy.jitter_factor * retry_after) if policy.jitter_factor else 0
        return max(retry_after + jitter, 1.0)

    # Exponential backoff: base * 2^attempt
    delay = policy.base_delay_seconds * (2 ** attempt)

    # Add jitter (+/- jitter_factor)
    jitter_range = delay * policy.jitter_factor
    jitter = random.uniform(-jitter_range, jitter_range)
    delay = delay + jitter

    # Cap at maximum delay
    delay = min(delay, policy.max_delay_seconds)

    # Ensure minimum 1 second delay
    return max(delay, 1.0)


def should_retry(
    error_category: ErrorCategory,
    retry_count: int,
    policy: RetryPolicy = RetryPolicy(),
    retry_after: Optional[int] = None,
) -> RetryDecision:
    """
    Determine if an operation should be retried.

    Args:
        error_category: Classified error type
        retry_count: Current retry count (before this attempt)
        policy: Retry policy configuration
        retry_after: Server-specified retry delay in seconds

    Returns:
        RetryDecision with retry/DLQ recommendation
    """
    # Auth errors never retry
    if error_category == ErrorCategory.AUTH_ERROR:
        return RetryDecision(
            should_retry=False,
            delay_seconds=0,
            next_retry_at=None,
            move_to_dlq=True,
            reason="Authentication/authorization error - requires manual intervention"
        )

    # Check if max retries exceeded
    if retry_count >= policy.max_retries:
        return RetryDecision(
            should_retry=False,
            delay_seconds=0,
            next_retry_at=None,
            move_to_dlq=True,
            reason=f"Max retries ({policy.max_retries}) exceeded"
        )

    # Calculate backoff for retryable errors
    delay = calculate_backoff(
        attempt=retry_count,
        policy=policy,
        retry_after=retry_after,
    )
    next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)

    # Rate limit - always retry with appropriate backoff
    if error_category == ErrorCategory.RATE_LIMIT:
        return RetryDecision(
            should_retry=True,
            delay_seconds=delay,
            next_retry_at=next_retry,
            move_to_dlq=False,
            reason=f"Rate limited - retry in {delay:.0f}s (attempt {retry_count + 1}/{policy.max_retries})"
        )

    # Server errors, timeouts, connection errors - retry
    if error_category in (
        ErrorCategory.SERVER_ERROR,
        ErrorCategory.TIMEOUT,
        ErrorCategory.CONNECTION,
        ErrorCategory.SYNC_FAILED,
    ):
        return RetryDecision(
            should_retry=True,
            delay_seconds=delay,
            next_retry_at=next_retry,
            move_to_dlq=False,
            reason=f"Transient error ({error_category.value}) - retry in {delay:.0f}s (attempt {retry_count + 1}/{policy.max_retries})"
        )

    # Unknown errors - retry with caution
    if error_category == ErrorCategory.UNKNOWN:
        return RetryDecision(
            should_retry=True,
            delay_seconds=delay,
            next_retry_at=next_retry,
            move_to_dlq=False,
            reason=f"Unknown error - retry in {delay:.0f}s (attempt {retry_count + 1}/{policy.max_retries})"
        )

    # Fallback - don't retry
    return RetryDecision(
        should_retry=False,
        delay_seconds=0,
        next_retry_at=None,
        move_to_dlq=True,
        reason="Unhandled error category"
    )


def log_retry_decision(
    job_id: str,
    tenant_id: str,
    error_category: ErrorCategory,
    decision: RetryDecision,
) -> None:
    """
    Log retry decision for observability.

    Args:
        job_id: Job identifier
        tenant_id: Tenant identifier
        error_category: Classified error type
        decision: Retry decision made
    """
    log_extra = {
        "job_id": job_id,
        "tenant_id": tenant_id,
        "error_category": error_category.value,
        "should_retry": decision.should_retry,
        "delay_seconds": decision.delay_seconds,
        "move_to_dlq": decision.move_to_dlq,
        "reason": decision.reason,
    }

    if decision.next_retry_at:
        log_extra["next_retry_at"] = decision.next_retry_at.isoformat()

    if decision.move_to_dlq:
        logger.warning("Job moved to dead letter queue", extra=log_extra)
    elif decision.should_retry:
        logger.info("Job scheduled for retry", extra=log_extra)
    else:
        logger.error("Job failed without retry", extra=log_extra)
