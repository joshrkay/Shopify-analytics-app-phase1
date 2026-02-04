"""
Organization model for multi-tenant SaaS platform.

Organization represents a parent entity (e.g., agency group) that can own
multiple tenants. This enables agency-style hierarchies where one organization
manages multiple client stores.

SECURITY: Organizations are not tenant-scoped themselves - they ARE the
top-level entity. Access control is enforced via UserTenantRole relationships.
"""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Column, String, Boolean, Index
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin

if TYPE_CHECKING:
    from src.models.tenant import Tenant


class Organization(Base, TimestampMixin):
    """
    Parent entity for grouping multiple tenants.

    Use cases:
    - Agency managing multiple client stores
    - Enterprise with multiple brands/regions
    - Holding company structure

    An Organization can have zero or more Tenants.
    Tenants can exist without an Organization (standalone merchants).
    """

    __tablename__ = "organizations"

    # Primary Key
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Internal UUID primary key"
    )

    # Clerk Organization ID (external reference)
    clerk_org_id = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        comment="Clerk Organization ID for SSO/identity linking"
    )

    # Organization Details
    name = Column(
        String(255),
        nullable=False,
        comment="Display name of the organization"
    )

    slug = Column(
        String(100),
        nullable=True,
        unique=True,
        index=True,
        comment="URL-friendly identifier (e.g., 'acme-agency')"
    )

    # Status
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether the organization is active"
    )

    # Metadata / Settings
    settings = Column(
        JSON,
        nullable=True,
        comment="Organization-level settings and configuration"
    )

    # Relationships
    tenants = relationship(
        "Tenant",
        back_populates="organization",
        lazy="dynamic",
        cascade="save-update, merge"
    )

    # Additional indexes (is_active already has index=True on column)
    __table_args__ = (
        Index("ix_organizations_name", "name"),
    )

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name}, is_active={self.is_active})>"

    @property
    def tenant_count(self) -> int:
        """Get the number of tenants in this organization."""
        return self.tenants.count()
