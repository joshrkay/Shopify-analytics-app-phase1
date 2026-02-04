"""
Base mixins for database models.

Provides common functionality:
- TimestampMixin: created_at, updated_at timestamps
- TenantScopedMixin: tenant_id for multi-tenant isolation
- generate_uuid: UUID generation for primary keys
- GUID: Cross-database compatible UUID type
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, String, DateTime, func, TypeDecorator
from sqlalchemy.types import CHAR
from sqlalchemy.orm import declared_attr


class GUID(TypeDecorator):
    """
    Platform-independent GUID type.

    Uses CHAR(36) for storage, works with PostgreSQL, SQLite, and other databases.
    Stores UUID as string and converts to/from Python uuid.UUID on access.
    """
    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            if not isinstance(value, uuid.UUID):
                return uuid.UUID(value)
            return value
        return value


def generate_uuid() -> str:
    """Generate a UUID4 string for use as a primary key default."""
    return str(uuid.uuid4())


class TimestampMixin:
    """Mixin that adds created_at and updated_at timestamp columns."""
    
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="Timestamp when record was created"
    )
    
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="Timestamp when record was last updated"
    )


class TenantScopedMixin:
    """
    Mixin that adds tenant_id column for multi-tenant isolation.
    
    SECURITY: tenant_id is ONLY extracted from JWT (org_id).
    NEVER accept tenant_id from client input (body/query/path).
    """
    
    @declared_attr
    def tenant_id(cls):
        return Column(
            String(255),
            nullable=False,
            index=True,
            comment="Tenant identifier from JWT org_id. NEVER from client input."
        )
