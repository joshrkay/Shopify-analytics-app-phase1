"""
ShopifyStore model for linking Shopify stores to Frontegg tenants.

CRITICAL DESIGN DECISIONS:
- tenant_id comes from Frontegg JWT (org_id)
- shop_domain is the canonical Shopify identifier (mystore.myshopify.com)
- access_token is encrypted at rest
- A Frontegg tenant can have MULTIPLE Shopify stores
"""

from sqlalchemy import (
    Column, String, Text, DateTime, Enum, Index,
    UniqueConstraint
)
from sqlalchemy.orm import relationship

from src.models.base import Base, TimestampMixin, TenantScopedMixin, generate_uuid


class StoreStatus(str):
    """Store installation status values."""
    INSTALLING = "installing"
    ACTIVE = "active"
    UNINSTALLED = "uninstalled"
    SUSPENDED = "suspended"


class ShopifyStore(Base, TimestampMixin, TenantScopedMixin):
    """
    Links a Shopify store to a Frontegg tenant.

    SECURITY:
    - tenant_id is from Frontegg JWT, NEVER from request
    - access_token_encrypted must be decrypted only when making API calls
    - shop_domain is unique (one app install per store)
    """

    __tablename__ = "shopify_stores"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid,
        comment="UUID primary key"
    )

    # Shopify identifiers
    shop_domain = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Shopify store domain (mystore.myshopify.com)"
    )
    shop_id = Column(
        String(50),
        nullable=True,
        comment="Shopify shop GID (gid://shopify/Shop/12345)"
    )

    # OAuth tokens (encrypted at rest)
    access_token_encrypted = Column(
        Text,
        nullable=True,
        comment="Encrypted Shopify access token"
    )
    scopes = Column(
        Text,
        nullable=True,
        comment="JSON array of granted OAuth scopes"
    )

    # Store metadata from Shopify
    shop_name = Column(
        String(255),
        nullable=True,
        comment="Store display name"
    )
    shop_email = Column(
        String(255),
        nullable=True,
        comment="Store contact email"
    )
    shop_owner = Column(
        String(255),
        nullable=True,
        comment="Store owner name"
    )
    currency = Column(
        String(10),
        default="USD",
        comment="Store's primary currency"
    )
    timezone = Column(
        String(100),
        nullable=True,
        comment="Store timezone (e.g., America/New_York)"
    )
    country_code = Column(
        String(10),
        nullable=True,
        comment="Store country code (e.g., US)"
    )

    # Installation status
    status = Column(
        Enum(
            "installing", "active", "uninstalled", "suspended",
            name="store_status"
        ),
        default="installing",
        nullable=False,
        index=True,
        comment="Current installation status"
    )
    installed_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the app was installed"
    )
    uninstalled_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the app was uninstalled"
    )

    # Relationships (defined here, back_populates in related models)
    subscription = relationship(
        "Subscription",
        back_populates="store",
        uselist=False,
        lazy="selectin"
    )
    usage_records = relationship(
        "UsageRecord",
        back_populates="store",
        lazy="dynamic"
    )
    billing_events = relationship(
        "BillingEvent",
        back_populates="store",
        lazy="dynamic"
    )

    # Table constraints and indexes
    __table_args__ = (
        Index("ix_shopify_stores_tenant_status", "tenant_id", "status"),
        Index("ix_shopify_stores_tenant_domain", "tenant_id", "shop_domain"),
        UniqueConstraint("shop_domain", name="uq_shopify_stores_shop_domain"),
    )

    def __repr__(self) -> str:
        return f"<ShopifyStore(id={self.id}, shop_domain={self.shop_domain}, tenant_id={self.tenant_id})>"

    @property
    def is_active(self) -> bool:
        """Check if store is currently active."""
        return self.status == StoreStatus.ACTIVE

    @property
    def has_valid_token(self) -> bool:
        """Check if store has a valid access token."""
        return bool(self.access_token_encrypted) and self.is_active
