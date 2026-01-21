"""
Base model classes and mixins for billing models.

Provides common functionality for all SQLAlchemy models:
- TimestampMixin: created_at/updated_at tracking
- TenantScopedMixin: tenant isolation enforcement
"""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, String, DateTime, Index
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import declarative_base

# Base class for all models
Base = declarative_base()


def generate_uuid() -> str:
    """Generate a UUID string for primary keys."""
    return str(uuid4())


class TimestampMixin:
    """
    Mixin that adds created_at and updated_at timestamps.

    Automatically sets created_at on insert and updated_at on update.
    """

    @declared_attr
    def created_at(cls):
        return Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            nullable=False
        )

    @declared_attr
    def updated_at(cls):
        return Column(
            DateTime(timezone=True),
            default=lambda: datetime.now(timezone.utc),
            onupdate=lambda: datetime.now(timezone.utc),
            nullable=False
        )


class TenantScopedMixin:
    """
    Mixin for tenant-scoped models.

    CRITICAL: All tenant-scoped models MUST include tenant_id.
    This enables strict multi-tenant isolation at the database level.

    The tenant_id should ALWAYS come from JWT context, never from request body.
    """

    @declared_attr
    def tenant_id(cls):
        return Column(
            String(255),
            nullable=False,
            index=True,
            comment="Tenant identifier from Frontegg org_id"
        )

    @declared_attr
    def __table_args__(cls):
        """Add tenant_id index for query performance."""
        return (
            Index(f"ix_{cls.__tablename__}_tenant_id", "tenant_id"),
        )
