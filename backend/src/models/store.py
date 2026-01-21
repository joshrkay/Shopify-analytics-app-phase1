"""
ShopifyStore model - Links Shopify shop to Frontegg tenant.

SECURITY: tenant_id is ONLY extracted from JWT, never from client input.
"""

import uuid
from sqlalchemy import Column, String, Enum
from sqlalchemy.dialects.postgresql import UUID
import enum

from src.repositories.base_repo import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class StoreStatus(str, enum.Enum):
    """Shopify store status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    UNINSTALLED = "uninstalled"


class ShopifyStore(Base, TimestampMixin, TenantScopedMixin):
    """
    Shopify store linked to a Frontegg tenant.
    
    Maps a Shopify shop domain to a tenant_id (from JWT org_id).
    Stores encrypted access token for Shopify API calls.
    """
    
    __tablename__ = "shopify_stores"
    
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )
    
    shop_domain = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Shopify shop domain (e.g., 'example.myshopify.com')"
    )
    
    access_token_encrypted = Column(
        String(2048),
        nullable=False,
        comment="Encrypted Shopify access token. Must be encrypted at rest."
    )
    
    status = Column(
        Enum(StoreStatus),
        nullable=False,
        default=StoreStatus.ACTIVE,
        index=True,
        comment="Store status: active, inactive, suspended, uninstalled"
    )
    
    def __repr__(self) -> str:
        return f"<ShopifyStore(id={self.id}, shop_domain={self.shop_domain}, tenant_id={self.tenant_id})>"
