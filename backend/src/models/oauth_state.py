"""
OAuth state model for Shopify OAuth flow.

Stores temporary state/nonce pairs for CSRF protection during OAuth installation.
States expire after 10 minutes and are single-use.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, String, Text, DateTime, Index

from src.db_base import Base
from src.models.base import TimestampMixin


class OAuthState(Base, TimestampMixin):
    """
    OAuth state for CSRF protection during Shopify OAuth flow.
    
    States are:
    - Single-use (marked used after consumption)
    - Short-lived (10-minute TTL)
    - Cryptographically secure (32-byte random)
    """
    
    __tablename__ = "oauth_states"
    
    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Primary key (UUID)"
    )
    
    shop_domain = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Shopify shop domain (mystore.myshopify.com)"
    )
    
    state = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Cryptographically secure state parameter (32 bytes)"
    )
    
    nonce = Column(
        String(255),
        nullable=False,
        comment="Nonce for additional security"
    )
    
    scopes = Column(
        Text,
        nullable=False,
        comment="OAuth scopes requested"
    )
    
    redirect_uri = Column(
        Text,
        nullable=False,
        comment="OAuth redirect URI"
    )
    
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When this state expires (10 minutes from creation)"
    )
    
    used_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="When this state was consumed (single-use)"
    )
    
    # Table constraints and indexes
    # Note: Indexes are created in migration 0002_oauth_states.sql
    # We don't define them here to avoid conflicts during test setup
    __table_args__ = ()
    
    def __repr__(self) -> str:
        return f"<OAuthState(id={self.id}, shop_domain={self.shop_domain}, state={self.state[:8]}...)>"
    
    @property
    def is_expired(self) -> bool:
        """Check if state has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_used(self) -> bool:
        """Check if state has been consumed."""
        return self.used_at is not None
    
    @property
    def is_valid(self) -> bool:
        """Check if state is valid (not expired and not used)."""
        return not self.is_expired and not self.is_used
