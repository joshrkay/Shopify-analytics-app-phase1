"""
JWT Token Generation for Embedded Superset Dashboards.

Generates short-lived tokens for Shopify Admin iframe embedding.
Handles token refresh logic and validation.

Security Requirements:
- JWT lifetime: 1 hour (configurable)
- Silent refresh before expiry
- Tenant isolation via JWT claims
- CSP enforcement for Shopify Admin only
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional

import jwt
from pydantic import BaseModel

from src.platform.tenant_context import TenantContext

logger = logging.getLogger(__name__)


class EmbedTokenConfig(BaseModel):
    """Configuration for embed token generation."""
    jwt_secret: str
    algorithm: str = "HS256"
    default_lifetime_minutes: int = 60
    refresh_threshold_minutes: int = 5
    issuer: str = "ai-growth-analytics"


class EmbedTokenPayload(BaseModel):
    """Decoded embed token payload."""
    sub: str  # user_id
    tenant_id: str
    roles: list[str]
    allowed_tenants: list[str]
    dashboard_id: Optional[str] = None
    iss: str
    iat: int
    exp: int


class EmbedTokenResult(BaseModel):
    """Result of embed token generation."""
    jwt_token: str
    expires_at: datetime
    refresh_before: datetime
    dashboard_url: str


class EmbedTokenError(Exception):
    """Base exception for embed token errors."""
    pass


class TokenExpiredError(EmbedTokenError):
    """Token has expired and cannot be refreshed."""
    pass


class TokenValidationError(EmbedTokenError):
    """Token validation failed."""
    pass


class EmbedTokenService:
    """
    Service for generating and managing Superset embed tokens.

    Tokens include:
    - User identity (sub)
    - Tenant isolation (tenant_id, allowed_tenants)
    - Role-based access (roles)
    - Dashboard scoping (dashboard_id)
    """

    def __init__(self, config: Optional[EmbedTokenConfig] = None):
        """
        Initialize embed token service.

        Args:
            config: Token configuration. If not provided, loads from environment.
        """
        if config:
            self.config = config
        else:
            jwt_secret = os.getenv("SUPERSET_JWT_SECRET")
            if not jwt_secret:
                raise ValueError("SUPERSET_JWT_SECRET environment variable is required")

            self.config = EmbedTokenConfig(
                jwt_secret=jwt_secret,
                default_lifetime_minutes=int(os.getenv("EMBED_TOKEN_LIFETIME_MINUTES", "60")),
                refresh_threshold_minutes=int(os.getenv("EMBED_TOKEN_REFRESH_THRESHOLD_MINUTES", "5")),
            )

        self.superset_base_url = os.getenv("SUPERSET_EMBED_URL", "https://analytics.example.com")

    def generate_embed_token(
        self,
        tenant_context: TenantContext,
        dashboard_id: str,
        lifetime_minutes: Optional[int] = None,
    ) -> EmbedTokenResult:
        """
        Generate JWT token for Superset embedding.

        Args:
            tenant_context: Current tenant context from authenticated request
            dashboard_id: Superset dashboard ID to embed
            lifetime_minutes: Optional custom token lifetime

        Returns:
            EmbedTokenResult with JWT and metadata
        """
        lifetime = lifetime_minutes or self.config.default_lifetime_minutes
        now = datetime.utcnow()
        exp = now + timedelta(minutes=lifetime)
        refresh_before = exp - timedelta(minutes=self.config.refresh_threshold_minutes)

        payload = {
            "sub": tenant_context.user_id,
            "tenant_id": tenant_context.tenant_id,
            "roles": tenant_context.roles,
            "allowed_tenants": tenant_context.allowed_tenants,
            "dashboard_id": dashboard_id,
            "iss": self.config.issuer,
            "iat": int(now.timestamp()),
            "exp": int(exp.timestamp()),
            # Superset-specific claims
            "resources": {
                "dashboard": [dashboard_id]
            },
            # RLS filter context
            "rls_filter": tenant_context.get_rls_clause(),
        }

        token = jwt.encode(
            payload,
            self.config.jwt_secret,
            algorithm=self.config.algorithm
        )

        # Build dashboard URL with embedded mode parameters
        dashboard_url = self._build_dashboard_url(dashboard_id, token)

        logger.info(
            "Generated embed token",
            extra={
                "tenant_id": tenant_context.tenant_id,
                "user_id": tenant_context.user_id,
                "dashboard_id": dashboard_id,
                "expires_at": exp.isoformat(),
            }
        )

        return EmbedTokenResult(
            jwt_token=token,
            expires_at=exp,
            refresh_before=refresh_before,
            dashboard_url=dashboard_url,
        )

    def _build_dashboard_url(self, dashboard_id: str, token: str) -> str:
        """
        Build Superset dashboard URL with embedded mode parameters.

        Hides Superset chrome (navigation, headers, etc.)
        """
        # Superset embed URL format with parameters to hide UI chrome
        params = [
            f"token={token}",
            "standalone=1",  # Hide navigation
            "show_filters=0",  # Hide filter bar
            "show_title=0",  # Hide dashboard title
        ]
        return f"{self.superset_base_url}/superset/dashboard/{dashboard_id}/?{'&'.join(params)}"

    def validate_token(self, token: str) -> EmbedTokenPayload:
        """
        Validate and decode an embed token.

        Args:
            token: JWT token string

        Returns:
            Decoded token payload

        Raises:
            TokenExpiredError: If token has expired
            TokenValidationError: If token is invalid
        """
        try:
            payload = jwt.decode(
                token,
                self.config.jwt_secret,
                algorithms=[self.config.algorithm],
                issuer=self.config.issuer,
            )
            return EmbedTokenPayload(**payload)
        except jwt.ExpiredSignatureError:
            raise TokenExpiredError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise TokenValidationError(f"Invalid token: {str(e)}")

    def should_refresh(self, token: str) -> bool:
        """
        Check if token should be refreshed.

        Returns True if token will expire within refresh threshold.
        """
        try:
            payload = self.validate_token(token)
            now = datetime.utcnow().timestamp()
            minutes_remaining = (payload.exp - now) / 60
            return minutes_remaining <= self.config.refresh_threshold_minutes
        except EmbedTokenError:
            # Refresh on any validation error
            return True

    def refresh_token(
        self,
        old_token: str,
        tenant_context: TenantContext,
        lifetime_minutes: Optional[int] = None,
    ) -> EmbedTokenResult:
        """
        Refresh an embed token.

        Validates old token (allows expired within grace period),
        then generates new token with same dashboard scope.

        Args:
            old_token: Previous JWT token
            tenant_context: Current tenant context for validation
            lifetime_minutes: Optional custom lifetime for new token

        Returns:
            New EmbedTokenResult

        Raises:
            TokenValidationError: If old token cannot be validated
        """
        try:
            # Try normal validation first
            payload = self.validate_token(old_token)
        except TokenExpiredError:
            # Allow refresh of recently expired tokens (grace period)
            try:
                payload_dict = jwt.decode(
                    old_token,
                    self.config.jwt_secret,
                    algorithms=[self.config.algorithm],
                    options={"verify_exp": False},
                    issuer=self.config.issuer,
                )
                payload = EmbedTokenPayload(**payload_dict)

                # Check grace period (max 10 minutes past expiry)
                now = datetime.utcnow().timestamp()
                grace_period_seconds = 10 * 60
                if now - payload.exp > grace_period_seconds:
                    raise TokenExpiredError("Token expired beyond grace period")

            except jwt.InvalidTokenError as e:
                raise TokenValidationError(f"Cannot refresh invalid token: {str(e)}")

        # Verify tenant context matches token
        if payload.tenant_id != tenant_context.tenant_id:
            logger.warning(
                "Token refresh attempted with mismatched tenant",
                extra={
                    "token_tenant_id": payload.tenant_id,
                    "context_tenant_id": tenant_context.tenant_id,
                    "user_id": tenant_context.user_id,
                }
            )
            raise TokenValidationError("Token tenant does not match current context")

        # Generate new token
        dashboard_id = payload.dashboard_id or "default"

        logger.info(
            "Refreshing embed token",
            extra={
                "tenant_id": tenant_context.tenant_id,
                "user_id": tenant_context.user_id,
                "dashboard_id": dashboard_id,
            }
        )

        return self.generate_embed_token(
            tenant_context=tenant_context,
            dashboard_id=dashboard_id,
            lifetime_minutes=lifetime_minutes,
        )


def get_embed_token_service() -> EmbedTokenService:
    """
    Factory function to get embed token service instance.

    Returns configured service or raises if not configured.
    """
    return EmbedTokenService()
