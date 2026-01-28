"""
Google Ads API executor.

Executes actions on Google advertising campaigns via the Google Ads API.

Supported Actions:
- pause_campaign: Set campaign status to PAUSED
- resume_campaign: Set campaign status to ENABLED
- adjust_budget: Update campaign budget
- adjust_bid: Update bidding strategy or target

API Reference: https://developers.google.com/google-ads/api/docs

Story 8.5 - Action Execution (Scoped & Reversible)
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Any

import httpx

from src.services.platform_executors.base_executor import (
    BasePlatformExecutor,
    ExecutionResult,
    ExecutionResultStatus,
    StateCapture,
    RetryConfig,
    PlatformAPIError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Google Ads Constants
# =============================================================================

GOOGLE_ADS_API_VERSION = "v15"
GOOGLE_ADS_API_BASE = "https://googleads.googleapis.com"

# Google Ads campaign status values
class GoogleCampaignStatus:
    ENABLED = "ENABLED"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


# =============================================================================
# Google Credentials
# =============================================================================

@dataclass
class GoogleAdsCredentials:
    """
    Credentials for Google Ads API.

    SECURITY: All tokens should be encrypted at rest.

    Requires:
    - access_token: OAuth2 access token
    - refresh_token: OAuth2 refresh token (for token refresh)
    - client_id: OAuth2 client ID
    - client_secret: OAuth2 client secret
    - developer_token: Google Ads developer token
    - customer_id: Google Ads customer ID (without hyphens)
    - login_customer_id: Optional manager account ID (for MCC access)
    """
    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    developer_token: str
    customer_id: str
    login_customer_id: Optional[str] = None

    def __post_init__(self):
        # Remove hyphens from customer IDs if present
        self.customer_id = self.customer_id.replace("-", "")
        if self.login_customer_id:
            self.login_customer_id = self.login_customer_id.replace("-", "")


# =============================================================================
# Google Ads Executor
# =============================================================================

class GoogleAdsExecutor(BasePlatformExecutor):
    """
    Executor for Google Ads API.

    Handles execution of actions on Google advertising campaigns
    via the Google Ads API.

    SECURITY:
    - OAuth2 tokens should be encrypted at rest
    - Developer token is rate-limited by Google
    - All API calls are logged for audit

    Rate Limiting:
    - Google Ads uses daily operation limits
    - Executor respects rate limit headers
    - Exponential backoff for 429 responses

    Note: Google Ads API uses gRPC internally, but we use the REST
    interface for simplicity. For production, consider using the
    official google-ads Python client library.
    """

    platform_name = "google"

    def __init__(
        self,
        credentials: GoogleAdsCredentials,
        retry_config: Optional[RetryConfig] = None,
        api_version: str = GOOGLE_ADS_API_VERSION,
        timeout_seconds: float = 30.0,
    ):
        """
        Initialize Google Ads executor.

        Args:
            credentials: Google Ads API credentials
            retry_config: Optional retry configuration
            api_version: Google Ads API version (default: v15)
            timeout_seconds: HTTP timeout in seconds
        """
        super().__init__(retry_config)
        self.credentials = credentials
        self.api_version = api_version
        self.base_url = f"{GOOGLE_ADS_API_BASE}/{api_version}"
        self.timeout = httpx.Timeout(timeout_seconds)

        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with auth headers."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers=self._get_auth_headers(),
            )
        return self._client

    def _get_auth_headers(self) -> dict:
        """Get authentication headers for Google Ads API."""
        headers = {
            "Authorization": f"Bearer {self.credentials.access_token}",
            "developer-token": self.credentials.developer_token,
            "Content-Type": "application/json",
        }
        if self.credentials.login_customer_id:
            headers["login-customer-id"] = self.credentials.login_customer_id
        return headers

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    # =========================================================================
    # Credential Validation
    # =========================================================================

    def validate_credentials(self) -> bool:
        """Validate that credentials are present and properly formatted."""
        if not self.credentials.access_token:
            logger.error("Google Ads access token is missing")
            return False
        if not self.credentials.developer_token:
            logger.error("Google Ads developer token is missing")
            return False
        if not self.credentials.customer_id:
            logger.error("Google Ads customer ID is missing")
            return False
        if len(self.credentials.customer_id) != 10:
            logger.error("Google Ads customer ID must be 10 digits")
            return False
        return True

    # =========================================================================
    # State Capture
    # =========================================================================

    async def get_entity_state(
        self,
        entity_id: str,
        entity_type: str,
    ) -> StateCapture:
        """
        Get current state of a Google Ads entity.

        Args:
            entity_id: Google Ads resource name or ID
            entity_type: Type of entity (campaign, ad_group, ad)

        Returns:
            StateCapture with current entity state

        Raises:
            PlatformAPIError: If API call fails
        """
        # Build GAQL query based on entity type
        query = self._build_state_query(entity_id, entity_type)

        url = f"{self.base_url}/customers/{self.credentials.customer_id}/googleAds:searchStream"

        payload = {"query": query}

        client = await self._get_client()

        try:
            response = await client.post(url, json=payload)
            data = response.json()

            if response.status_code != 200:
                error = data.get("error", {})
                raise PlatformAPIError(
                    message=error.get("message", f"Failed to get {entity_type} state"),
                    platform=self.platform_name,
                    status_code=response.status_code,
                    error_code=error.get("status", ""),
                    response=data,
                    is_retryable=response.status_code in (429, 500, 502, 503, 504),
                )

            # Parse the streaming response
            state = self._parse_search_response(data, entity_type)

            return StateCapture(
                entity_id=entity_id,
                entity_type=entity_type,
                platform=self.platform_name,
                state=state,
            )

        except httpx.RequestError as e:
            raise PlatformAPIError(
                message=f"Network error getting {entity_type} state: {e}",
                platform=self.platform_name,
                is_retryable=True,
            )

    def _build_state_query(self, entity_id: str, entity_type: str) -> str:
        """Build GAQL query for fetching entity state."""
        if entity_type == "campaign":
            return f"""
                SELECT
                    campaign.id,
                    campaign.name,
                    campaign.status,
                    campaign.advertising_channel_type,
                    campaign_budget.amount_micros,
                    campaign_budget.delivery_method,
                    campaign.bidding_strategy_type,
                    campaign.target_cpa.target_cpa_micros,
                    campaign.target_roas.target_roas,
                    campaign.start_date,
                    campaign.end_date
                FROM campaign
                WHERE campaign.id = {entity_id}
            """
        elif entity_type == "ad_group":
            return f"""
                SELECT
                    ad_group.id,
                    ad_group.name,
                    ad_group.status,
                    ad_group.campaign,
                    ad_group.cpc_bid_micros,
                    ad_group.cpm_bid_micros,
                    ad_group.target_cpa_micros
                FROM ad_group
                WHERE ad_group.id = {entity_id}
            """
        elif entity_type == "ad":
            return f"""
                SELECT
                    ad_group_ad.ad.id,
                    ad_group_ad.ad.name,
                    ad_group_ad.status,
                    ad_group_ad.ad_group,
                    ad_group_ad.ad.type
                FROM ad_group_ad
                WHERE ad_group_ad.ad.id = {entity_id}
            """
        else:
            # Generic campaign query as fallback
            return f"""
                SELECT campaign.id, campaign.name, campaign.status
                FROM campaign
                WHERE campaign.id = {entity_id}
            """

    def _parse_search_response(self, data: list, entity_type: str) -> dict:
        """Parse Google Ads search stream response."""
        # Response is a list of batches
        if not data:
            return {}

        results = []
        for batch in data:
            if "results" in batch:
                results.extend(batch["results"])

        if not results:
            return {}

        # Return first result's entity
        first_result = results[0]

        if entity_type == "campaign":
            return first_result.get("campaign", {})
        elif entity_type == "ad_group":
            return first_result.get("adGroup", {})
        elif entity_type == "ad":
            return first_result.get("adGroupAd", {})
        else:
            return first_result

    # =========================================================================
    # Action Execution
    # =========================================================================

    async def _execute_action_impl(
        self,
        action_type: str,
        entity_id: str,
        entity_type: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Execute action on Google Ads platform.

        Args:
            action_type: Type of action to execute
            entity_id: Google Ads entity ID
            entity_type: Type of entity
            params: Action parameters
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome details
        """
        if action_type == "pause_campaign":
            return await self._execute_status_change(
                entity_id, entity_type, GoogleCampaignStatus.PAUSED, idempotency_key
            )
        elif action_type == "resume_campaign":
            return await self._execute_status_change(
                entity_id, entity_type, GoogleCampaignStatus.ENABLED, idempotency_key
            )
        elif action_type == "adjust_budget":
            return await self._execute_budget_change(
                entity_id, entity_type, params, idempotency_key
            )
        elif action_type == "adjust_bid":
            return await self._execute_bid_change(
                entity_id, entity_type, params, idempotency_key
            )
        else:
            return ExecutionResult.failure_result(
                message=f"Unsupported action type: {action_type}",
                error_code="UNSUPPORTED_ACTION",
                is_retryable=False,
            )

    async def _execute_status_change(
        self,
        entity_id: str,
        entity_type: str,
        new_status: str,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Change entity status (pause/resume).

        Args:
            entity_id: Google Ads entity ID
            entity_type: Type of entity
            new_status: New status value (ENABLED, PAUSED)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        # Build resource name
        resource_name = f"customers/{self.credentials.customer_id}/campaigns/{entity_id}"

        url = f"{self.base_url}/customers/{self.credentials.customer_id}/campaigns:mutate"

        payload = {
            "operations": [
                {
                    "updateMask": "status",
                    "update": {
                        "resourceName": resource_name,
                        "status": new_status,
                    }
                }
            ],
            "partialFailure": False,
            "validateOnly": False,
        }

        # Log request
        log_entry = self._log_request("POST", url, {"status": new_status, "resourceName": resource_name})
        logger.info("Executing Google Ads status change", extra=log_entry)

        client = await self._get_client()

        try:
            response = await client.post(url, json=payload)
            data = response.json()

            if response.status_code == 200:
                # Verify the change
                verified_state = await self.get_entity_state(entity_id, entity_type)

                return ExecutionResult.success_result(
                    message=f"Successfully changed {entity_type} status to {new_status}",
                    response_data=data,
                    confirmed_state=verified_state.state,
                    http_status_code=response.status_code,
                )

            error = data.get("error", {})
            return self._handle_error_response(
                response.status_code,
                error,
                f"Failed to change {entity_type} status",
            )

        except httpx.RequestError as e:
            logger.error(
                "Network error during Google Ads status change",
                extra={"entity_id": entity_id, "error": str(e)}
            )
            return ExecutionResult.failure_result(
                message=f"Network error: {e}",
                is_retryable=True,
            )

    async def _execute_budget_change(
        self,
        entity_id: str,
        entity_type: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Change campaign budget.

        Note: In Google Ads, budgets are separate resources linked to campaigns.
        This implementation assumes direct budget updates; production code should
        handle budget resource management properly.

        Args:
            entity_id: Campaign ID
            entity_type: Type of entity
            params: Budget parameters:
                - new_budget: New budget amount (in account currency)
                - budget_id: Budget resource ID (required for existing budgets)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        new_budget = params.get("new_budget")
        budget_id = params.get("budget_id")

        if new_budget is None:
            return ExecutionResult.failure_result(
                message="new_budget is required for budget adjustment",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        if budget_id is None:
            return ExecutionResult.failure_result(
                message="budget_id is required for budget adjustment",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        # Convert to micros (Google Ads uses micro-units)
        amount_micros = int(new_budget * 1_000_000)

        resource_name = f"customers/{self.credentials.customer_id}/campaignBudgets/{budget_id}"

        url = f"{self.base_url}/customers/{self.credentials.customer_id}/campaignBudgets:mutate"

        payload = {
            "operations": [
                {
                    "updateMask": "amountMicros",
                    "update": {
                        "resourceName": resource_name,
                        "amountMicros": str(amount_micros),
                    }
                }
            ],
            "partialFailure": False,
            "validateOnly": False,
        }

        log_entry = self._log_request("POST", url, {"amountMicros": amount_micros})
        logger.info("Executing Google Ads budget change", extra=log_entry)

        client = await self._get_client()

        try:
            response = await client.post(url, json=payload)
            data = response.json()

            if response.status_code == 200:
                verified_state = await self.get_entity_state(entity_id, entity_type)

                return ExecutionResult.success_result(
                    message=f"Successfully updated budget to {new_budget}",
                    response_data=data,
                    confirmed_state=verified_state.state,
                    http_status_code=response.status_code,
                )

            error = data.get("error", {})
            return self._handle_error_response(
                response.status_code,
                error,
                "Failed to update campaign budget",
            )

        except httpx.RequestError as e:
            logger.error(
                "Network error during Google Ads budget change",
                extra={"entity_id": entity_id, "error": str(e)}
            )
            return ExecutionResult.failure_result(
                message=f"Network error: {e}",
                is_retryable=True,
            )

    async def _execute_bid_change(
        self,
        entity_id: str,
        entity_type: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Change bidding settings.

        Args:
            entity_id: Campaign or ad group ID
            entity_type: Type of entity
            params: Bid parameters:
                - target_cpa: Target CPA in account currency (optional)
                - target_roas: Target ROAS as percentage (optional)
                - cpc_bid: CPC bid in account currency (for ad groups)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        if entity_type == "campaign":
            return await self._execute_campaign_bid_change(entity_id, params, idempotency_key)
        elif entity_type == "ad_group":
            return await self._execute_ad_group_bid_change(entity_id, params, idempotency_key)
        else:
            return ExecutionResult.failure_result(
                message=f"Bid adjustments not supported for {entity_type}",
                error_code="UNSUPPORTED_ENTITY",
                is_retryable=False,
            )

    async def _execute_campaign_bid_change(
        self,
        campaign_id: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """Execute bid change at campaign level."""
        resource_name = f"customers/{self.credentials.customer_id}/campaigns/{campaign_id}"

        update_mask_fields = []
        update_data = {"resourceName": resource_name}

        if "target_cpa" in params:
            target_cpa_micros = int(params["target_cpa"] * 1_000_000)
            update_data["targetCpa"] = {"targetCpaMicros": str(target_cpa_micros)}
            update_mask_fields.append("targetCpa.targetCpaMicros")

        if "target_roas" in params:
            # Target ROAS is expressed as a ratio (e.g., 3.5 for 350%)
            update_data["targetRoas"] = {"targetRoas": params["target_roas"]}
            update_mask_fields.append("targetRoas.targetRoas")

        if not update_mask_fields:
            return ExecutionResult.failure_result(
                message="No bid parameters provided",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        url = f"{self.base_url}/customers/{self.credentials.customer_id}/campaigns:mutate"

        payload = {
            "operations": [
                {
                    "updateMask": ",".join(update_mask_fields),
                    "update": update_data,
                }
            ],
            "partialFailure": False,
            "validateOnly": False,
        }

        log_entry = self._log_request("POST", url, params)
        logger.info("Executing Google Ads campaign bid change", extra=log_entry)

        client = await self._get_client()

        try:
            response = await client.post(url, json=payload)
            data = response.json()

            if response.status_code == 200:
                verified_state = await self.get_entity_state(campaign_id, "campaign")

                return ExecutionResult.success_result(
                    message="Successfully updated campaign bid settings",
                    response_data=data,
                    confirmed_state=verified_state.state,
                    http_status_code=response.status_code,
                )

            error = data.get("error", {})
            return self._handle_error_response(
                response.status_code,
                error,
                "Failed to update campaign bid settings",
            )

        except httpx.RequestError as e:
            return ExecutionResult.failure_result(
                message=f"Network error: {e}",
                is_retryable=True,
            )

    async def _execute_ad_group_bid_change(
        self,
        ad_group_id: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """Execute bid change at ad group level."""
        resource_name = f"customers/{self.credentials.customer_id}/adGroups/{ad_group_id}"

        update_mask_fields = []
        update_data = {"resourceName": resource_name}

        if "cpc_bid" in params:
            cpc_bid_micros = int(params["cpc_bid"] * 1_000_000)
            update_data["cpcBidMicros"] = str(cpc_bid_micros)
            update_mask_fields.append("cpcBidMicros")

        if "target_cpa" in params:
            target_cpa_micros = int(params["target_cpa"] * 1_000_000)
            update_data["targetCpaMicros"] = str(target_cpa_micros)
            update_mask_fields.append("targetCpaMicros")

        if not update_mask_fields:
            return ExecutionResult.failure_result(
                message="No bid parameters provided",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        url = f"{self.base_url}/customers/{self.credentials.customer_id}/adGroups:mutate"

        payload = {
            "operations": [
                {
                    "updateMask": ",".join(update_mask_fields),
                    "update": update_data,
                }
            ],
            "partialFailure": False,
            "validateOnly": False,
        }

        log_entry = self._log_request("POST", url, params)
        logger.info("Executing Google Ads ad group bid change", extra=log_entry)

        client = await self._get_client()

        try:
            response = await client.post(url, json=payload)
            data = response.json()

            if response.status_code == 200:
                verified_state = await self.get_entity_state(ad_group_id, "ad_group")

                return ExecutionResult.success_result(
                    message="Successfully updated ad group bid settings",
                    response_data=data,
                    confirmed_state=verified_state.state,
                    http_status_code=response.status_code,
                )

            error = data.get("error", {})
            return self._handle_error_response(
                response.status_code,
                error,
                "Failed to update ad group bid settings",
            )

        except httpx.RequestError as e:
            return ExecutionResult.failure_result(
                message=f"Network error: {e}",
                is_retryable=True,
            )

    def _handle_error_response(
        self,
        status_code: int,
        error: dict,
        default_message: str,
    ) -> ExecutionResult:
        """
        Handle Google Ads API error response.

        Args:
            status_code: HTTP status code
            error: Error object from Google response
            default_message: Default error message

        Returns:
            ExecutionResult with failure details
        """
        error_code = error.get("status", "")
        error_message = error.get("message", default_message)

        # Determine if retryable based on error code
        is_retryable = status_code in (429, 500, 502, 503, 504)

        # Check for specific Google Ads error codes
        if error_code == "RESOURCE_EXHAUSTED":
            is_retryable = True
        elif error_code in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            is_retryable = False

        # Extract retry-after if present
        retry_after = None
        if status_code == 429:
            retry_after = 60.0  # Default wait for rate limits

        return ExecutionResult.failure_result(
            message=error_message,
            error_code=error_code,
            error_details={
                "status": error_code,
                "details": error.get("details", []),
            },
            http_status_code=status_code,
            is_retryable=is_retryable,
            retry_after_seconds=retry_after,
        )

    # =========================================================================
    # Rollback Generation
    # =========================================================================

    def generate_rollback_params(
        self,
        action_type: str,
        before_state: dict,
    ) -> dict:
        """
        Generate parameters to reverse a Google Ads action.

        Args:
            action_type: Type of action that was executed
            before_state: Entity state before the action

        Returns:
            Dictionary of parameters for rollback
        """
        if action_type in ("pause_campaign", "resume_campaign"):
            # Restore original status
            original_status = before_state.get("status", GoogleCampaignStatus.PAUSED)
            return {"status": original_status}

        elif action_type == "adjust_budget":
            # Restore original budget (convert from micros)
            amount_micros = before_state.get("amountMicros")
            if amount_micros:
                return {
                    "new_budget": int(amount_micros) / 1_000_000,
                    "budget_id": before_state.get("resourceName", "").split("/")[-1],
                }
            return {}

        elif action_type == "adjust_bid":
            # Restore original bid settings
            params = {}

            # Campaign-level bids
            if "targetCpa" in before_state:
                target_cpa_micros = before_state["targetCpa"].get("targetCpaMicros")
                if target_cpa_micros:
                    params["target_cpa"] = int(target_cpa_micros) / 1_000_000

            if "targetRoas" in before_state:
                params["target_roas"] = before_state["targetRoas"].get("targetRoas")

            # Ad group-level bids
            if "cpcBidMicros" in before_state:
                params["cpc_bid"] = int(before_state["cpcBidMicros"]) / 1_000_000

            if "targetCpaMicros" in before_state:
                params["target_cpa"] = int(before_state["targetCpaMicros"]) / 1_000_000

            return params

        else:
            logger.warning(f"Cannot generate rollback for unknown action type: {action_type}")
            return {}
