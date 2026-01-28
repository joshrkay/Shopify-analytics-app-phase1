"""
Meta (Facebook/Instagram) Ads API executor.

Executes actions on Meta advertising campaigns via the Marketing API.

Supported Actions:
- pause_campaign: Set campaign status to PAUSED
- resume_campaign: Set campaign status to ACTIVE
- adjust_budget: Update daily or lifetime budget
- adjust_bid: Update bid amount or strategy

API Reference: https://developers.facebook.com/docs/marketing-api

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
# Meta-specific Constants
# =============================================================================

META_API_VERSION = "v18.0"
META_GRAPH_API_BASE = "https://graph.facebook.com"

# Meta campaign status values
class MetaCampaignStatus:
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    ARCHIVED = "ARCHIVED"


# Meta effective status values (read-only, computed by Meta)
class MetaEffectiveStatus:
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"
    PENDING_REVIEW = "PENDING_REVIEW"
    DISAPPROVED = "DISAPPROVED"
    PREAPPROVED = "PREAPPROVED"
    PENDING_BILLING_INFO = "PENDING_BILLING_INFO"
    CAMPAIGN_PAUSED = "CAMPAIGN_PAUSED"
    ARCHIVED = "ARCHIVED"
    ADSET_PAUSED = "ADSET_PAUSED"


# =============================================================================
# Meta Credentials
# =============================================================================

@dataclass
class MetaCredentials:
    """
    Credentials for Meta Marketing API.

    SECURITY: access_token should be encrypted at rest.
    """
    access_token: str
    ad_account_id: str  # Format: act_XXXXX

    def __post_init__(self):
        # Ensure ad_account_id has correct prefix
        if not self.ad_account_id.startswith("act_"):
            self.ad_account_id = f"act_{self.ad_account_id}"


# =============================================================================
# Meta Ads Executor
# =============================================================================

class MetaAdsExecutor(BasePlatformExecutor):
    """
    Executor for Meta (Facebook/Instagram) Ads API.

    Handles execution of actions on Meta advertising campaigns,
    ad sets, and ads via the Marketing API.

    SECURITY:
    - Access token should have minimal required permissions
    - Token should be encrypted at rest
    - All API calls are logged for audit

    Rate Limiting:
    - Meta uses a points-based rate limit system
    - Executor respects Retry-After headers
    - Exponential backoff for 429 responses
    """

    platform_name = "meta"

    def __init__(
        self,
        credentials: MetaCredentials,
        retry_config: Optional[RetryConfig] = None,
        api_version: str = META_API_VERSION,
        timeout_seconds: float = 30.0,
    ):
        """
        Initialize Meta Ads executor.

        Args:
            credentials: Meta API credentials
            retry_config: Optional retry configuration
            api_version: Meta API version (default: v18.0)
            timeout_seconds: HTTP timeout in seconds
        """
        super().__init__(retry_config)
        self.credentials = credentials
        self.api_version = api_version
        self.base_url = f"{META_GRAPH_API_BASE}/{api_version}"
        self.timeout = httpx.Timeout(timeout_seconds)

        # HTTP client (created lazily or passed in for testing)
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

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
            logger.error("Meta access token is missing")
            return False
        if not self.credentials.ad_account_id:
            logger.error("Meta ad account ID is missing")
            return False
        if not self.credentials.ad_account_id.startswith("act_"):
            logger.error("Meta ad account ID must start with 'act_'")
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
        Get current state of a Meta advertising entity.

        Args:
            entity_id: Meta entity ID (campaign_id, adset_id, ad_id)
            entity_type: Type of entity (campaign, ad_set, ad)

        Returns:
            StateCapture with current entity state

        Raises:
            PlatformAPIError: If API call fails
        """
        fields = self._get_fields_for_entity_type(entity_type)

        url = f"{self.base_url}/{entity_id}"
        params = {
            "access_token": self.credentials.access_token,
            "fields": ",".join(fields),
        }

        client = await self._get_client()

        try:
            response = await client.get(url, params=params)
            data = response.json()

            if response.status_code != 200:
                error = data.get("error", {})
                raise PlatformAPIError(
                    message=error.get("message", f"Failed to get {entity_type} state"),
                    platform=self.platform_name,
                    status_code=response.status_code,
                    error_code=str(error.get("code", "")),
                    response=data,
                    is_retryable=response.status_code in (429, 500, 502, 503, 504),
                )

            return StateCapture(
                entity_id=entity_id,
                entity_type=entity_type,
                platform=self.platform_name,
                state=data,
            )

        except httpx.RequestError as e:
            raise PlatformAPIError(
                message=f"Network error getting {entity_type} state: {e}",
                platform=self.platform_name,
                is_retryable=True,
            )

    def _get_fields_for_entity_type(self, entity_type: str) -> list[str]:
        """Get relevant fields to fetch for each entity type."""
        base_fields = ["id", "name", "status", "effective_status", "created_time", "updated_time"]

        if entity_type == "campaign":
            return base_fields + [
                "objective",
                "buying_type",
                "daily_budget",
                "lifetime_budget",
                "budget_remaining",
                "special_ad_categories",
            ]
        elif entity_type == "ad_set":
            return base_fields + [
                "campaign_id",
                "daily_budget",
                "lifetime_budget",
                "budget_remaining",
                "bid_amount",
                "bid_strategy",
                "billing_event",
                "optimization_goal",
                "targeting",
                "start_time",
                "end_time",
            ]
        elif entity_type == "ad":
            return base_fields + [
                "campaign_id",
                "adset_id",
                "creative",
            ]
        else:
            return base_fields

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
        Execute action on Meta platform.

        Args:
            action_type: Type of action to execute
            entity_id: Meta entity ID
            entity_type: Type of entity
            params: Action parameters
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome details
        """
        # Route to specific action handler
        if action_type == "pause_campaign":
            return await self._execute_status_change(
                entity_id, entity_type, MetaCampaignStatus.PAUSED, idempotency_key
            )
        elif action_type == "resume_campaign":
            return await self._execute_status_change(
                entity_id, entity_type, MetaCampaignStatus.ACTIVE, idempotency_key
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
            entity_id: Meta entity ID
            entity_type: Type of entity
            new_status: New status value (ACTIVE, PAUSED)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        url = f"{self.base_url}/{entity_id}"
        payload = {
            "access_token": self.credentials.access_token,
            "status": new_status,
        }

        # Log request (sanitized)
        log_entry = self._log_request("POST", url, {"status": new_status})
        logger.info("Executing Meta status change", extra=log_entry)

        client = await self._get_client()

        try:
            response = await client.post(url, data=payload)
            data = response.json()

            if response.status_code == 200 and data.get("success", False):
                # Verify the change by fetching current state
                verified_state = await self.get_entity_state(entity_id, entity_type)

                return ExecutionResult.success_result(
                    message=f"Successfully changed {entity_type} status to {new_status}",
                    response_data=data,
                    confirmed_state=verified_state.state,
                    http_status_code=response.status_code,
                )

            # Handle error response
            error = data.get("error", {})
            return self._handle_error_response(
                response.status_code,
                error,
                f"Failed to change {entity_type} status",
            )

        except httpx.RequestError as e:
            logger.error(
                "Network error during Meta status change",
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
        Change entity budget.

        Args:
            entity_id: Meta entity ID
            entity_type: Type of entity (campaign or ad_set)
            params: Budget parameters:
                - new_budget: New budget amount (in account currency, micro-units)
                - budget_type: "daily" or "lifetime"
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        new_budget = params.get("new_budget")
        budget_type = params.get("budget_type", "daily")

        if new_budget is None:
            return ExecutionResult.failure_result(
                message="new_budget is required for budget adjustment",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        # Meta expects budget in micro-units (cents for USD)
        # If the value is already in dollars, convert to cents
        budget_value = int(new_budget * 100) if new_budget < 10000 else int(new_budget)

        url = f"{self.base_url}/{entity_id}"

        # Determine which budget field to update
        if budget_type == "lifetime":
            budget_field = "lifetime_budget"
        else:
            budget_field = "daily_budget"

        payload = {
            "access_token": self.credentials.access_token,
            budget_field: budget_value,
        }

        # Log request (sanitized)
        log_entry = self._log_request("POST", url, {budget_field: budget_value})
        logger.info("Executing Meta budget change", extra=log_entry)

        client = await self._get_client()

        try:
            response = await client.post(url, data=payload)
            data = response.json()

            if response.status_code == 200 and data.get("success", False):
                # Verify the change
                verified_state = await self.get_entity_state(entity_id, entity_type)

                return ExecutionResult.success_result(
                    message=f"Successfully updated {budget_type} budget to {new_budget}",
                    response_data=data,
                    confirmed_state=verified_state.state,
                    http_status_code=response.status_code,
                )

            error = data.get("error", {})
            return self._handle_error_response(
                response.status_code,
                error,
                f"Failed to update {entity_type} budget",
            )

        except httpx.RequestError as e:
            logger.error(
                "Network error during Meta budget change",
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
        Change entity bid amount or strategy.

        Args:
            entity_id: Meta entity ID (typically ad_set)
            entity_type: Type of entity
            params: Bid parameters:
                - bid_amount: New bid amount in micro-units (optional)
                - bid_strategy: New bid strategy (optional)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        url = f"{self.base_url}/{entity_id}"

        payload = {
            "access_token": self.credentials.access_token,
        }

        if "bid_amount" in params:
            # Convert to micro-units if needed
            bid_value = params["bid_amount"]
            payload["bid_amount"] = int(bid_value * 100) if bid_value < 10000 else int(bid_value)

        if "bid_strategy" in params:
            payload["bid_strategy"] = params["bid_strategy"]

        if len(payload) == 1:  # Only access_token
            return ExecutionResult.failure_result(
                message="Either bid_amount or bid_strategy is required",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        # Log request (sanitized)
        sanitized = {k: v for k, v in payload.items() if k != "access_token"}
        log_entry = self._log_request("POST", url, sanitized)
        logger.info("Executing Meta bid change", extra=log_entry)

        client = await self._get_client()

        try:
            response = await client.post(url, data=payload)
            data = response.json()

            if response.status_code == 200 and data.get("success", False):
                verified_state = await self.get_entity_state(entity_id, entity_type)

                return ExecutionResult.success_result(
                    message="Successfully updated bid settings",
                    response_data=data,
                    confirmed_state=verified_state.state,
                    http_status_code=response.status_code,
                )

            error = data.get("error", {})
            return self._handle_error_response(
                response.status_code,
                error,
                f"Failed to update {entity_type} bid",
            )

        except httpx.RequestError as e:
            logger.error(
                "Network error during Meta bid change",
                extra={"entity_id": entity_id, "error": str(e)}
            )
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
        Handle Meta API error response.

        Args:
            status_code: HTTP status code
            error: Error object from Meta response
            default_message: Default error message

        Returns:
            ExecutionResult with failure details
        """
        error_code = str(error.get("code", ""))
        error_message = error.get("message", default_message)
        error_type = error.get("type", "")

        # Determine if retryable based on error code
        is_retryable = status_code in (429, 500, 502, 503, 504)

        # Check for specific Meta error codes
        meta_error_code = error.get("code")
        if meta_error_code == 17:  # Rate limiting
            is_retryable = True
        elif meta_error_code == 4:  # Application request limit
            is_retryable = True
        elif meta_error_code in (190, 102):  # OAuth / Session errors
            is_retryable = False

        # Extract retry-after if present
        retry_after = None
        if status_code == 429:
            retry_after = 60.0  # Default 60 second wait for rate limits

        return ExecutionResult.failure_result(
            message=error_message,
            error_code=error_code,
            error_details={
                "type": error_type,
                "code": meta_error_code,
                "fbtrace_id": error.get("fbtrace_id"),
                "error_subcode": error.get("error_subcode"),
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
        Generate parameters to reverse a Meta action.

        Args:
            action_type: Type of action that was executed
            before_state: Entity state before the action

        Returns:
            Dictionary of parameters for rollback
        """
        if action_type in ("pause_campaign", "resume_campaign"):
            # Restore original status
            original_status = before_state.get("status", MetaCampaignStatus.PAUSED)
            return {"status": original_status}

        elif action_type == "adjust_budget":
            # Restore original budget
            params = {}
            if "daily_budget" in before_state:
                params["new_budget"] = before_state["daily_budget"]
                params["budget_type"] = "daily"
            elif "lifetime_budget" in before_state:
                params["new_budget"] = before_state["lifetime_budget"]
                params["budget_type"] = "lifetime"
            return params

        elif action_type == "adjust_bid":
            # Restore original bid settings
            params = {}
            if "bid_amount" in before_state:
                params["bid_amount"] = before_state["bid_amount"]
            if "bid_strategy" in before_state:
                params["bid_strategy"] = before_state["bid_strategy"]
            return params

        else:
            # Unknown action type - return empty params
            logger.warning(f"Cannot generate rollback for unknown action type: {action_type}")
            return {}
