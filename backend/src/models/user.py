"""
User model for multi-tenant SaaS platform.

User represents a local user record synced from Clerk. This model stores
profile information and links to tenant access via UserTenantRole.

CRITICAL SECURITY:
- NO PASSWORDS are stored locally - Clerk is the source of truth for auth
- clerk_user_id is the unique identifier from Clerk
- User data is synced via Clerk webhooks (user.created, user.updated, etc.)
- Local id is for internal database references only

A User can belong to multiple tenants via UserTenantRole relationships.
"""

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from src.db_base import Base
from src.models.base import TimestampMixin

if TYPE_CHECKING:
    from src.models.user_tenant_roles import UserTenantRole
    from src.models.tenant import Tenant


class User(Base, TimestampMixin):
    """
    Local user record synced from Clerk.

    SECURITY: NO PASSWORDS - Clerk handles all authentication.

    Key concepts:
    - clerk_user_id is the unique identifier from Clerk (source of truth)
    - id is the internal UUID for database relationships
    - Users access tenants via UserTenantRole (many-to-many with role)
    - Profile data (email, name, avatar) synced from Clerk webhooks

    Sync mechanisms:
    - Clerk webhooks: Real-time sync on user.created, user.updated, user.deleted
    - Lazy sync: Create/update on first authenticated request if webhook missed
    """

    __tablename__ = "users"

    # Internal Primary Key
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Internal UUID primary key"
    )

    # Clerk User ID - SOURCE OF TRUTH
    clerk_user_id = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Clerk user ID - source of truth for authentication"
    )

    # Profile Information (synced from Clerk)
    email = Column(
        String(255),
        nullable=True,
        index=True,
        comment="User email address (from Clerk)"
    )

    first_name = Column(
        String(255),
        nullable=True,
        comment="User first name (from Clerk)"
    )

    last_name = Column(
        String(255),
        nullable=True,
        comment="User last name (from Clerk)"
    )

    # Profile image URL (from Clerk)
    avatar_url = Column(
        String(500),
        nullable=True,
        comment="Profile image URL (from Clerk)"
    )

    # Sync tracking
    last_synced_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When user data was last synced from Clerk"
    )

    # Active status
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether the user is active (false = soft deleted)"
    )

    # Additional metadata from Clerk (named extra_metadata to avoid SQLAlchemy conflict)
    extra_metadata = Column(
        "metadata",  # Column name in database is still 'metadata'
        JSON,
        nullable=True,
        comment="Additional user metadata from Clerk"
    )

    # Relationships
    tenant_roles = relationship(
        "UserTenantRole",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    # Note: Indexes are defined via index=True on columns above
    # SQLAlchemy auto-generates index names like ix_users_email, ix_users_is_active, etc.

    def __repr__(self) -> str:
        return f"<User(id={self.id}, clerk_user_id={self.clerk_user_id}, email={self.email})>"

    @property
    def full_name(self) -> str:
        """
        Return full name or email if no name is set.

        Handles cases where:
        - Both first and last name are set
        - Only first name is set
        - Only last name is set
        - No name is set (falls back to email)
        """
        if self.first_name or self.last_name:
            parts = []
            if self.first_name:
                parts.append(self.first_name)
            if self.last_name:
                parts.append(self.last_name)
            return " ".join(parts)
        return self.email or ""

    @property
    def display_name(self) -> str:
        """
        Return the best available display name.

        Priority: full_name > email > clerk_user_id
        """
        if self.first_name or self.last_name:
            return self.full_name
        if self.email:
            return self.email
        return self.clerk_user_id

    @property
    def tenant_count(self) -> int:
        """Get the number of tenants this user has access to."""
        return self.tenant_roles.filter_by(is_active=True).count()

    def get_active_tenant_roles(self) -> List["UserTenantRole"]:
        """Get all active tenant role assignments."""
        return self.tenant_roles.filter_by(is_active=True).all()

    def get_tenants(self) -> List["Tenant"]:
        """Get all tenants this user has access to."""
        from src.models.tenant import Tenant
        from src.models.user_tenant_roles import UserTenantRole

        return [role.tenant for role in self.tenant_roles.filter_by(is_active=True).all()]

    def has_access_to_tenant(self, tenant_id: str) -> bool:
        """Check if user has any active access to a tenant."""
        return self.tenant_roles.filter_by(
            tenant_id=tenant_id,
            is_active=True
        ).first() is not None

    def get_role_for_tenant(self, tenant_id: str) -> Optional[str]:
        """Get user's role for a specific tenant."""
        role = self.tenant_roles.filter_by(
            tenant_id=tenant_id,
            is_active=True
        ).first()
        return role.role if role else None

    def mark_synced(self) -> None:
        """Update the last_synced_at timestamp."""
        self.last_synced_at = datetime.now(timezone.utc)
