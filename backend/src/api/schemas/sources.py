"""
Unified Source schemas for the Data Sources API.

Normalizes Shopify and ad platform connections into a single Source model.
Maps Airbyte source_type identifiers to platform keys and auth types.

Story 2.1.1 — Unified Source domain model
"""

from typing import Optional, List

from pydantic import BaseModel

from src.services.airbyte_service import ConnectionInfo


# =============================================================================
# Platform Mapping Constants
# =============================================================================

SOURCE_TYPE_TO_PLATFORM: dict[str, str] = {
    "shopify": "shopify",
    "source-shopify": "shopify",
    "source-facebook-marketing": "meta_ads",
    "source-google-ads": "google_ads",
    "source-tiktok-marketing": "tiktok_ads",
    "source-snapchat-marketing": "snapchat_ads",
    "source-klaviyo": "klaviyo",
    "source-attentive": "attentive",
    "source-postscript": "postscript",
    "source-smsbump": "smsbump",
}

PLATFORM_AUTH_TYPE: dict[str, str] = {
    "shopify": "oauth",
    "meta_ads": "oauth",
    "google_ads": "oauth",
    "tiktok_ads": "oauth",
    "snapchat_ads": "oauth",
    "klaviyo": "api_key",
    "shopify_email": "oauth",
    "attentive": "api_key",
    "postscript": "api_key",
    "smsbump": "api_key",
}

PLATFORM_DISPLAY_NAMES: dict[str, str] = {
    "shopify": "Shopify",
    "meta_ads": "Meta Ads",
    "google_ads": "Google Ads",
    "tiktok_ads": "TikTok Ads",
    "snapchat_ads": "Snapchat Ads",
    "klaviyo": "Klaviyo",
    "shopify_email": "Shopify Email",
    "attentive": "Attentive",
    "postscript": "Postscript",
    "smsbump": "SMSBump",
}


# =============================================================================
# Response Models
# =============================================================================

class SourceSummary(BaseModel):
    """Unified source connection summary."""

    id: str
    platform: str
    display_name: str
    auth_type: str
    status: str
    is_enabled: bool
    last_sync_at: Optional[str] = None
    last_sync_status: Optional[str] = None


class SourceListResponse(BaseModel):
    """Response for listing all sources."""

    sources: List[SourceSummary]
    total: int


# =============================================================================
# Catalog Models
# =============================================================================

PLATFORM_DESCRIPTIONS: dict[str, str] = {
    "shopify": "Connect your Shopify store to import orders, products, and customer data",
    "meta_ads": "Connect your Facebook and Instagram ad accounts for campaign analytics",
    "google_ads": "Connect your Google Ads account for search and display campaign data",
    "tiktok_ads": "Connect your TikTok Ads account for short-form video campaign data",
    "snapchat_ads": "Connect your Snapchat Ads account for Snap campaign analytics",
    "klaviyo": "Connect your Klaviyo account for email marketing analytics",
    "shopify_email": "Connect Shopify Email for email campaign performance data",
    "attentive": "Connect your Attentive account for SMS marketing analytics",
    "postscript": "Connect your Postscript account for SMS campaign data",
    "smsbump": "Connect your SMSBump account for SMS marketing metrics",
}

PLATFORM_CATEGORIES: dict[str, str] = {
    "shopify": "ecommerce",
    "meta_ads": "ads",
    "google_ads": "ads",
    "tiktok_ads": "ads",
    "snapchat_ads": "ads",
    "klaviyo": "email",
    "shopify_email": "email",
    "attentive": "sms",
    "postscript": "sms",
    "smsbump": "sms",
}


class SourceCatalogEntry(BaseModel):
    """A data source definition in the catalog."""

    id: str
    platform: str
    display_name: str
    description: str
    auth_type: str
    category: str
    is_enabled: bool


class SourceCatalogResponse(BaseModel):
    """Response for the source catalog."""

    sources: List[SourceCatalogEntry]
    total: int


# =============================================================================
# OAuth Models
# =============================================================================

class OAuthInitiateResponse(BaseModel):
    """Response from initiating OAuth flow."""

    authorization_url: str
    state: str
    connection_id: Optional[str] = None


class OAuthCallbackRequest(BaseModel):
    """Request body for OAuth callback."""

    code: str
    state: str


class OAuthCallbackResponse(BaseModel):
    """Response from OAuth callback."""

    success: bool
    connection_id: str
    message: str
    error: Optional[str] = None


# =============================================================================
# Source Management Models
# =============================================================================

class TestConnectionResponse(BaseModel):
    """Response from testing a connection."""

    success: bool
    message: str
    details: Optional[dict] = None


class UpdateSyncConfigRequest(BaseModel):
    """Request body for updating sync config."""

    sync_frequency: Optional[str] = None
    enabled_streams: Optional[List[str]] = None


# =============================================================================
# Global Sync Settings Models
# =============================================================================

class GlobalSyncSettingsResponse(BaseModel):
    """Response for global sync settings."""

    default_frequency: str
    pause_all_syncs: bool
    max_concurrent_syncs: int


class UpdateGlobalSyncSettingsRequest(BaseModel):
    """Request body for updating global sync settings."""

    default_frequency: Optional[str] = None
    pause_all_syncs: Optional[bool] = None
    max_concurrent_syncs: Optional[int] = None


# =============================================================================
# Normalizer
# =============================================================================

def normalize_connection_to_source(conn: ConnectionInfo) -> SourceSummary:
    """
    Normalize a ConnectionInfo (from AirbyteService) into a unified SourceSummary.

    Maps the Airbyte source_type to a platform key and derives auth_type.
    Works for both Shopify and ad platform connections.

    Args:
        conn: ConnectionInfo from AirbyteService.list_connections()

    Returns:
        SourceSummary with unified fields
    """
    platform = SOURCE_TYPE_TO_PLATFORM.get(
        conn.source_type or "", conn.source_type or "unknown"
    )
    auth_type = PLATFORM_AUTH_TYPE.get(platform, "api_key")
    display_name = conn.connection_name or PLATFORM_DISPLAY_NAMES.get(platform, platform)

    return SourceSummary(
        id=conn.id,
        platform=platform,
        display_name=display_name,
        auth_type=auth_type,
        status=conn.status,
        is_enabled=conn.is_enabled,
        last_sync_at=conn.last_sync_at.isoformat() if conn.last_sync_at else None,
        last_sync_status=conn.last_sync_status,
    )
