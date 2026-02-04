"""
Tenant model for multi-tenant SaaS platform.

Tenant represents a Shopify store or logical customer boundary. This is the
core entity that tenant_id references across all tenant-scoped models.

The Tenant.id becomes the tenant_id used throughout the application for:
- Data isolation (TenantScopedMixin)
- Row-level security
- Billing and entitlements
- Analytics scoping

SECURITY: tenant_id is ONLY extracted from JWT, never from client input.
"""

import uuid
import enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, String, Boolean, Enum, Index, ForeignKey
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin

if TYPE_CHECKING:
    from src.models.organization import Organization
    from src.models.user_tenant_roles import UserTenantRole


class TenantStatus(str, enum.Enum):
    """Tenant lifecycle status."""
    ACTIVE = "active"
    SUSPENDED = "suspended"      # Temporarily disabled (e.g., billing issue)
    DEACTIVATED = "deactivated"  # Permanently disabled


class Tenant(Base, TimestampMixin):
    """
    Tenant represents a Shopify store or logical customer boundary.

    Key concepts:
    - Tenant.id IS the tenant_id used across all tenant-scoped models
    - A Tenant can optionally belong to an Organization (for agencies)
    - A Tenant can have multiple users via UserTenantRole
    - Each Tenant has a billing_tier that determines entitlements

    Relationship to Clerk:
    - clerk_org_id links to Clerk Organization for SSO
    - Users are synced via Clerk webhooks
    - Membership changes create/update UserTenantRole records
    """

    __tablename__ = "tenants"

    # Primary Key - THIS IS THE tenant_id USED EVERYWHERE
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key - this IS the tenant_id used across all models"
    )

    # Organization relationship (optional - for agencies)
    organization_id = Column(
        String(255),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Parent organization ID (nullable for standalone merchants)"
    )

    # Clerk Organization ID (for direct Clerk org mapping)
    clerk_org_id = Column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        comment="Clerk Organization ID for identity linking"
    )

    # Tenant Details
    name = Column(
        String(255),
        nullable=False,
        comment="Display name of the tenant (store name)"
    )

    slug = Column(
        String(100),
        nullable=True,
        unique=True,
        index=True,
        comment="URL-friendly identifier (e.g., 'acme-store')"
    )

    # Billing
    billing_tier = Column(
        String(50),
        nullable=False,
        default="free",
        index=True,
        comment="Billing tier: free, growth, enterprise"
    )

    # Status
    status = Column(
        Enum(TenantStatus, name="tenant_status", create_constraint=True),
        nullable=False,
        default=TenantStatus.ACTIVE,
        index=True,
        comment="Tenant lifecycle status"
    )

    # Metadata / Settings
    settings = Column(
        JSON,
        nullable=True,
        comment="Tenant-level settings and configuration"
    )

    # Relationships
    organization = relationship(
        "Organization",
        back_populates="tenants",
        lazy="joined"
    )

    user_roles = relationship(
        "UserTenantRole",
        back_populates="tenant",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    # Composite indexes (simple column indexes defined via index=True above)
    __table_args__ = (
        Index("ix_tenants_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, name={self.name}, status={self.status.value})>"

    @property
    def is_active(self) -> bool:
        """Check if tenant is currently active."""
        return self.status == TenantStatus.ACTIVE

    @property
    def is_standalone(self) -> bool:
        """Check if tenant is standalone (no parent organization)."""
        return self.organization_id is None

    @property
    def member_count(self) -> int:
        """Get the number of users with access to this tenant."""
        return self.user_roles.filter_by(is_active=True).count()

    def get_organization_name(self) -> Optional[str]:
        """Get parent organization name if exists."""
        if self.organization:
            return self.organization.name
        return None
