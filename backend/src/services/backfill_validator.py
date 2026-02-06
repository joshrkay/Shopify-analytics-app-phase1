"""
Backfill request validation service.

Validates tenant existence, date ranges against billing tier limits,
overlapping backfills, and idempotency.

Story 3.4 - Backfill Request API
"""

import hashlib
import logging
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

from src.models.tenant import Tenant, TenantStatus
from src.models.historical_backfill import (
    HistoricalBackfillRequest,
    ACTIVE_BACKFILL_STATUSES,
)

logger = logging.getLogger(__name__)

# Billing tier -> max backfill window in days
TIER_MAX_BACKFILL_DAYS = {
    "free": 90,
    "growth": 90,
    "enterprise": 365,
}

DEFAULT_MAX_BACKFILL_DAYS = 90


class BackfillValidationError(Exception):
    """Base validation error with structured error code."""
    def __init__(self, message: str, error_code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.error_code = error_code


class TenantNotFoundError(BackfillValidationError):
    def __init__(self, tenant_id: str):
        super().__init__(
            f"Tenant '{tenant_id}' not found",
            error_code="TENANT_NOT_FOUND",
        )


class TenantNotActiveError(BackfillValidationError):
    def __init__(self, tenant_id: str, status: str):
        super().__init__(
            f"Tenant '{tenant_id}' is not active (status: {status})",
            error_code="TENANT_NOT_ACTIVE",
        )


class DateRangeExceededError(BackfillValidationError):
    def __init__(self, days: int, max_days: int, tier: str):
        super().__init__(
            f"Date range ({days} days) exceeds maximum ({max_days} days) "
            f"for '{tier}' tier",
            error_code="DATE_RANGE_EXCEEDED",
        )


class OverlappingBackfillError(BackfillValidationError):
    def __init__(self, existing_id: str):
        super().__init__(
            f"An overlapping active backfill already exists (id: {existing_id})",
            error_code="OVERLAPPING_BACKFILL",
        )


def compute_idempotency_key(
    tenant_id: str,
    source_system: str,
    start_date: date,
    end_date: date,
) -> str:
    """Compute deterministic SHA-256 idempotency key from request parameters."""
    canonical = (
        f"{tenant_id}|{source_system}|"
        f"{start_date.isoformat()}|{end_date.isoformat()}"
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class BackfillValidator:
    """
    Validates backfill requests against business rules.

    Checks:
    1. Target tenant exists and is active
    2. Date range within billing tier limit
    3. No overlapping active backfills for same tenant+source
    4. Idempotency (returns existing if duplicate)
    """

    def __init__(self, db_session: Session):
        self.db = db_session

    def validate_tenant(self, tenant_id: str) -> Tenant:
        """Validate target tenant exists and is active. Returns the Tenant."""
        tenant = (
            self.db.query(Tenant)
            .filter(Tenant.id == tenant_id)
            .first()
        )
        if not tenant:
            raise TenantNotFoundError(tenant_id)

        if tenant.status != TenantStatus.ACTIVE:
            raise TenantNotActiveError(tenant_id, tenant.status.value)

        return tenant

    def validate_date_range(
        self, start_date: date, end_date: date, billing_tier: str
    ) -> int:
        """Validate date range is within billing tier limits. Returns day count."""
        days = (end_date - start_date).days + 1
        max_days = TIER_MAX_BACKFILL_DAYS.get(
            billing_tier, DEFAULT_MAX_BACKFILL_DAYS
        )

        if days > max_days:
            raise DateRangeExceededError(days, max_days, billing_tier)

        return days

    def check_overlapping_backfills(
        self,
        tenant_id: str,
        source_system: str,
        start_date: date,
        end_date: date,
    ) -> None:
        """Reject if an overlapping active backfill exists for same tenant+source."""
        overlapping = (
            self.db.query(HistoricalBackfillRequest)
            .filter(
                HistoricalBackfillRequest.tenant_id == tenant_id,
                HistoricalBackfillRequest.source_system == source_system,
                HistoricalBackfillRequest.status.in_(ACTIVE_BACKFILL_STATUSES),
                HistoricalBackfillRequest.start_date <= end_date,
                HistoricalBackfillRequest.end_date >= start_date,
            )
            .first()
        )

        if overlapping:
            raise OverlappingBackfillError(overlapping.id)

    def find_idempotent_match(
        self, idempotency_key: str
    ) -> Optional[HistoricalBackfillRequest]:
        """Find existing request with same idempotency key."""
        return (
            self.db.query(HistoricalBackfillRequest)
            .filter(
                HistoricalBackfillRequest.idempotency_key == idempotency_key,
            )
            .first()
        )

    def validate_and_prepare(
        self,
        tenant_id: str,
        source_system: str,
        start_date: date,
        end_date: date,
    ) -> tuple[Optional[HistoricalBackfillRequest], bool]:
        """
        Run full validation pipeline.

        Returns:
            (existing_request, False) if idempotent match found
            (None, True) if all validations pass and new record should be created

        Raises:
            TenantNotFoundError, TenantNotActiveError,
            DateRangeExceededError, OverlappingBackfillError
        """
        idempotency_key = compute_idempotency_key(
            tenant_id, source_system, start_date, end_date
        )

        # Check idempotency first (cheapest check)
        existing = self.find_idempotent_match(idempotency_key)
        if existing:
            logger.info(
                "Idempotent backfill request matched",
                extra={
                    "existing_id": existing.id,
                    "idempotency_key": idempotency_key,
                    "tenant_id": tenant_id,
                },
            )
            return existing, False

        # Validate tenant exists and is active
        tenant = self.validate_tenant(tenant_id)

        # Validate date range against billing tier
        self.validate_date_range(start_date, end_date, tenant.billing_tier)

        # Check for overlapping active backfills
        self.check_overlapping_backfills(
            tenant_id, source_system, start_date, end_date
        )

        return None, True
