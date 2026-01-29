"""
Shopify Admin API executor.

Executes actions on Shopify stores via the GraphQL Admin API.

Supported Actions:
- create_discount: Create a new discount code
- update_discount: Update discount settings
- delete_discount: Remove a discount
- update_product: Update product details (title, price, status)
- update_inventory: Adjust inventory levels

API Reference: https://shopify.dev/docs/api/admin-graphql

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
# Shopify Constants
# =============================================================================

SHOPIFY_API_VERSION = "2024-01"

# Shopify product status values
class ShopifyProductStatus:
    ACTIVE = "ACTIVE"
    DRAFT = "DRAFT"
    ARCHIVED = "ARCHIVED"


# Shopify discount status values
class ShopifyDiscountStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SCHEDULED = "SCHEDULED"


# =============================================================================
# Shopify Credentials
# =============================================================================

@dataclass
class ShopifyCredentials:
    """
    Credentials for Shopify Admin API.

    SECURITY: access_token should be encrypted at rest.
    """
    access_token: str
    shop_domain: str  # e.g., "mystore.myshopify.com"

    def __post_init__(self):
        # Normalize shop domain - remove protocol and trailing slash
        self.shop_domain = (
            self.shop_domain
            .replace("https://", "")
            .replace("http://", "")
            .rstrip("/")
        )


# =============================================================================
# Shopify Executor
# =============================================================================

class ShopifyExecutor(BasePlatformExecutor):
    """
    Executor for Shopify Admin API.

    Handles execution of actions on Shopify stores including
    discounts, products, and inventory via the GraphQL Admin API.

    SECURITY:
    - Access token should have minimal required scopes
    - Token should be encrypted at rest
    - All API calls are logged for audit

    Rate Limiting:
    - Shopify uses a bucket-based rate limit system
    - Executor respects Retry-After headers
    - Exponential backoff for 429 responses
    """

    platform_name = "shopify"

    def __init__(
        self,
        credentials: ShopifyCredentials,
        retry_config: Optional[RetryConfig] = None,
        api_version: str = SHOPIFY_API_VERSION,
        timeout_seconds: float = 30.0,
    ):
        """
        Initialize Shopify executor.

        Args:
            credentials: Shopify API credentials
            retry_config: Optional retry configuration
            api_version: Shopify API version (default: 2024-01)
            timeout_seconds: HTTP timeout in seconds
        """
        super().__init__(retry_config)
        self.credentials = credentials
        self.api_version = api_version
        self.graphql_url = (
            f"https://{credentials.shop_domain}/admin/api/{api_version}/graphql.json"
        )
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
            logger.error("Shopify access token is missing")
            return False
        if not self.credentials.shop_domain:
            logger.error("Shopify shop domain is missing")
            return False
        if not self.credentials.shop_domain.endswith(".myshopify.com"):
            logger.warning(
                "Shopify shop domain may not be in correct format",
                extra={"shop_domain": self.credentials.shop_domain}
            )
        return True

    # =========================================================================
    # GraphQL Execution
    # =========================================================================

    async def _execute_graphql(
        self,
        query: str,
        variables: Optional[dict] = None,
    ) -> dict:
        """
        Execute a GraphQL query against Shopify Admin API.

        Args:
            query: GraphQL query string
            variables: Optional query variables

        Returns:
            Response data dictionary

        Raises:
            PlatformAPIError: If API call fails
        """
        client = await self._get_client()

        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        try:
            response = await client.post(
                self.graphql_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-Shopify-Access-Token": self.credentials.access_token,
                },
            )

            data = response.json()

            # Handle rate limiting
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 2.0))
                raise PlatformAPIError(
                    message="Rate limited by Shopify",
                    platform=self.platform_name,
                    status_code=429,
                    error_code="THROTTLED",
                    response=data,
                    retry_after=retry_after,
                    is_retryable=True,
                )

            # Handle authentication errors
            if response.status_code in (401, 403):
                raise PlatformAPIError(
                    message="Authentication failed with Shopify",
                    platform=self.platform_name,
                    status_code=response.status_code,
                    error_code="AUTH_ERROR",
                    response=data,
                    is_retryable=False,
                )

            # Handle server errors
            if response.status_code >= 500:
                raise PlatformAPIError(
                    message=f"Shopify server error: {response.status_code}",
                    platform=self.platform_name,
                    status_code=response.status_code,
                    error_code="SERVER_ERROR",
                    response=data,
                    is_retryable=True,
                )

            # Check for GraphQL errors
            if "errors" in data:
                errors = data["errors"]
                error_message = errors[0].get("message", "Unknown GraphQL error")
                error_code = errors[0].get("extensions", {}).get("code", "GRAPHQL_ERROR")

                # Check if throttled
                is_throttled = any(
                    e.get("extensions", {}).get("code") == "THROTTLED"
                    for e in errors
                )

                raise PlatformAPIError(
                    message=error_message,
                    platform=self.platform_name,
                    status_code=response.status_code,
                    error_code=error_code,
                    response=data,
                    is_retryable=is_throttled,
                    retry_after=2.0 if is_throttled else None,
                )

            return data.get("data", {})

        except httpx.RequestError as e:
            raise PlatformAPIError(
                message=f"Network error connecting to Shopify: {e}",
                platform=self.platform_name,
                is_retryable=True,
            )

    # =========================================================================
    # State Capture
    # =========================================================================

    async def get_entity_state(
        self,
        entity_id: str,
        entity_type: str,
    ) -> StateCapture:
        """
        Get current state of a Shopify entity.

        Args:
            entity_id: Shopify entity GID (e.g., gid://shopify/Product/123)
            entity_type: Type of entity (product, discount, inventory_item)

        Returns:
            StateCapture with current entity state

        Raises:
            PlatformAPIError: If API call fails
        """
        query = self._get_state_query(entity_type)

        # Ensure GID format
        gid = self._ensure_gid(entity_id, entity_type)

        data = await self._execute_graphql(query, {"id": gid})

        # Extract state based on entity type
        state = self._extract_state(data, entity_type)

        return StateCapture(
            entity_id=entity_id,
            entity_type=entity_type,
            platform=self.platform_name,
            state=state,
        )

    def _ensure_gid(self, entity_id: str, entity_type: str) -> str:
        """Ensure entity ID is in Shopify GID format."""
        if entity_id.startswith("gid://"):
            return entity_id

        # Map entity type to Shopify resource type
        type_map = {
            "product": "Product",
            "variant": "ProductVariant",
            "discount": "DiscountCodeNode",
            "discount_automatic": "DiscountAutomaticNode",
            "inventory_item": "InventoryItem",
            "inventory_level": "InventoryLevel",
        }

        resource_type = type_map.get(entity_type, entity_type.title())
        return f"gid://shopify/{resource_type}/{entity_id}"

    def _get_state_query(self, entity_type: str) -> str:
        """Get GraphQL query for fetching entity state."""
        if entity_type == "product":
            return """
            query getProduct($id: ID!) {
                product(id: $id) {
                    id
                    title
                    handle
                    status
                    productType
                    vendor
                    tags
                    createdAt
                    updatedAt
                    variants(first: 10) {
                        edges {
                            node {
                                id
                                title
                                price
                                compareAtPrice
                                sku
                                inventoryQuantity
                            }
                        }
                    }
                }
            }
            """
        elif entity_type in ("discount", "discount_code"):
            return """
            query getDiscount($id: ID!) {
                codeDiscountNode(id: $id) {
                    id
                    codeDiscount {
                        ... on DiscountCodeBasic {
                            title
                            status
                            startsAt
                            endsAt
                            usageLimit
                            codes(first: 5) {
                                edges {
                                    node {
                                        code
                                    }
                                }
                            }
                            customerGets {
                                value {
                                    ... on DiscountPercentage {
                                        percentage
                                    }
                                    ... on DiscountAmount {
                                        amount {
                                            amount
                                            currencyCode
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            """
        elif entity_type == "inventory_level":
            return """
            query getInventoryLevel($id: ID!) {
                inventoryLevel(id: $id) {
                    id
                    available
                    location {
                        id
                        name
                    }
                    item {
                        id
                        sku
                    }
                }
            }
            """
        else:
            # Generic node query
            return """
            query getNode($id: ID!) {
                node(id: $id) {
                    id
                    ... on Product {
                        title
                        status
                    }
                }
            }
            """

    def _extract_state(self, data: dict, entity_type: str) -> dict:
        """Extract state from GraphQL response."""
        if entity_type == "product":
            return data.get("product", {})
        elif entity_type in ("discount", "discount_code"):
            node = data.get("codeDiscountNode", {})
            return {
                "id": node.get("id"),
                "discount": node.get("codeDiscount", {}),
            }
        elif entity_type == "inventory_level":
            return data.get("inventoryLevel", {})
        else:
            return data.get("node", {})

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
        Execute action on Shopify platform.

        Args:
            action_type: Type of action to execute
            entity_id: Shopify entity ID (GID format)
            entity_type: Type of entity
            params: Action parameters
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome details
        """
        # Route to specific action handler
        if action_type == "update_product":
            return await self._execute_product_update(
                entity_id, params, idempotency_key
            )
        elif action_type == "update_product_status":
            return await self._execute_product_status_change(
                entity_id, params, idempotency_key
            )
        elif action_type == "create_discount":
            return await self._execute_discount_create(
                params, idempotency_key
            )
        elif action_type == "update_discount":
            return await self._execute_discount_update(
                entity_id, params, idempotency_key
            )
        elif action_type == "delete_discount":
            return await self._execute_discount_delete(
                entity_id, idempotency_key
            )
        elif action_type == "update_inventory":
            return await self._execute_inventory_update(
                entity_id, params, idempotency_key
            )
        elif action_type == "update_price":
            return await self._execute_price_update(
                entity_id, params, idempotency_key
            )
        else:
            return ExecutionResult.failure_result(
                message=f"Unsupported action type: {action_type}",
                error_code="UNSUPPORTED_ACTION",
                is_retryable=False,
            )

    async def _execute_product_update(
        self,
        entity_id: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Update product details.

        Args:
            entity_id: Product GID
            params: Update parameters (title, productType, vendor, tags, etc.)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        gid = self._ensure_gid(entity_id, "product")

        mutation = """
        mutation productUpdate($input: ProductInput!) {
            productUpdate(input: $input) {
                product {
                    id
                    title
                    status
                    updatedAt
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        # Build input from params
        product_input = {"id": gid}
        allowed_fields = ["title", "productType", "vendor", "tags", "status"]

        for field in allowed_fields:
            if field in params:
                product_input[field] = params[field]

        # Log request (sanitized)
        log_entry = self._log_request("POST", self.graphql_url, product_input)
        logger.info("Executing Shopify product update", extra=log_entry)

        try:
            data = await self._execute_graphql(mutation, {"input": product_input})

            result = data.get("productUpdate", {})
            user_errors = result.get("userErrors", [])

            if user_errors:
                error_msg = "; ".join(e.get("message", "") for e in user_errors)
                return ExecutionResult.failure_result(
                    message=f"Product update failed: {error_msg}",
                    error_code="USER_ERROR",
                    error_details={"userErrors": user_errors},
                    is_retryable=False,
                )

            product = result.get("product", {})

            # Verify the change
            verified_state = await self.get_entity_state(entity_id, "product")

            return ExecutionResult.success_result(
                message=f"Successfully updated product",
                response_data=product,
                confirmed_state=verified_state.state,
                http_status_code=200,
            )

        except PlatformAPIError:
            raise
        except Exception as e:
            logger.exception("Error during product update")
            return ExecutionResult.failure_result(
                message=f"Unexpected error: {e}",
                is_retryable=False,
            )

    async def _execute_product_status_change(
        self,
        entity_id: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Change product status (active/draft/archived).

        Args:
            entity_id: Product GID
            params: Parameters with 'status' field
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        new_status = params.get("status")
        if not new_status:
            return ExecutionResult.failure_result(
                message="status is required for product status change",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        return await self._execute_product_update(
            entity_id,
            {"status": new_status.upper()},
            idempotency_key,
        )

    async def _execute_discount_create(
        self,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Create a new discount code.

        Args:
            params: Discount parameters:
                - title: Discount title
                - code: Discount code
                - percentage: Discount percentage (0-100)
                - amount: Fixed discount amount (alternative to percentage)
                - starts_at: Start datetime (ISO format)
                - ends_at: End datetime (ISO format, optional)
                - usage_limit: Max uses (optional)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        title = params.get("title")
        code = params.get("code")

        if not title or not code:
            return ExecutionResult.failure_result(
                message="title and code are required for discount creation",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        mutation = """
        mutation discountCodeBasicCreate($basicCodeDiscount: DiscountCodeBasicInput!) {
            discountCodeBasicCreate(basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                    id
                    codeDiscount {
                        ... on DiscountCodeBasic {
                            title
                            status
                            codes(first: 1) {
                                edges {
                                    node {
                                        code
                                    }
                                }
                            }
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        # Build discount input
        discount_input = {
            "title": title,
            "code": code,
            "startsAt": params.get("starts_at", datetime.now(timezone.utc).isoformat()),
            "customerSelection": {
                "all": True
            },
            "combinesWith": {
                "orderDiscounts": False,
                "productDiscounts": False,
                "shippingDiscounts": True,
            },
        }

        # Set discount value
        if "percentage" in params:
            discount_input["customerGets"] = {
                "value": {
                    "percentage": float(params["percentage"]) / 100
                },
                "items": {"all": True}
            }
        elif "amount" in params:
            discount_input["customerGets"] = {
                "value": {
                    "discountAmount": {
                        "amount": str(params["amount"]),
                        "appliesOnEachItem": False
                    }
                },
                "items": {"all": True}
            }
        else:
            return ExecutionResult.failure_result(
                message="Either percentage or amount is required for discount",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        # Optional fields
        if "ends_at" in params:
            discount_input["endsAt"] = params["ends_at"]
        if "usage_limit" in params:
            discount_input["usageLimit"] = params["usage_limit"]

        log_entry = self._log_request("POST", self.graphql_url, {"title": title, "code": code})
        logger.info("Executing Shopify discount create", extra=log_entry)

        try:
            data = await self._execute_graphql(mutation, {"basicCodeDiscount": discount_input})

            result = data.get("discountCodeBasicCreate", {})
            user_errors = result.get("userErrors", [])

            if user_errors:
                error_msg = "; ".join(e.get("message", "") for e in user_errors)
                return ExecutionResult.failure_result(
                    message=f"Discount creation failed: {error_msg}",
                    error_code="USER_ERROR",
                    error_details={"userErrors": user_errors},
                    is_retryable=False,
                )

            discount_node = result.get("codeDiscountNode", {})

            return ExecutionResult.success_result(
                message=f"Successfully created discount code: {code}",
                response_data=discount_node,
                confirmed_state=discount_node,
                http_status_code=200,
            )

        except PlatformAPIError:
            raise
        except Exception as e:
            logger.exception("Error during discount creation")
            return ExecutionResult.failure_result(
                message=f"Unexpected error: {e}",
                is_retryable=False,
            )

    async def _execute_discount_update(
        self,
        entity_id: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Update an existing discount.

        Args:
            entity_id: Discount GID
            params: Update parameters
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        gid = self._ensure_gid(entity_id, "discount")

        mutation = """
        mutation discountCodeBasicUpdate($id: ID!, $basicCodeDiscount: DiscountCodeBasicInput!) {
            discountCodeBasicUpdate(id: $id, basicCodeDiscount: $basicCodeDiscount) {
                codeDiscountNode {
                    id
                    codeDiscount {
                        ... on DiscountCodeBasic {
                            title
                            status
                        }
                    }
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        # Build update input
        discount_input = {}

        if "title" in params:
            discount_input["title"] = params["title"]
        if "ends_at" in params:
            discount_input["endsAt"] = params["ends_at"]
        if "usage_limit" in params:
            discount_input["usageLimit"] = params["usage_limit"]

        if not discount_input:
            return ExecutionResult.failure_result(
                message="No update parameters provided",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        log_entry = self._log_request("POST", self.graphql_url, discount_input)
        logger.info("Executing Shopify discount update", extra=log_entry)

        try:
            data = await self._execute_graphql(mutation, {
                "id": gid,
                "basicCodeDiscount": discount_input
            })

            result = data.get("discountCodeBasicUpdate", {})
            user_errors = result.get("userErrors", [])

            if user_errors:
                error_msg = "; ".join(e.get("message", "") for e in user_errors)
                return ExecutionResult.failure_result(
                    message=f"Discount update failed: {error_msg}",
                    error_code="USER_ERROR",
                    error_details={"userErrors": user_errors},
                    is_retryable=False,
                )

            discount_node = result.get("codeDiscountNode", {})

            # Verify the change
            verified_state = await self.get_entity_state(entity_id, "discount")

            return ExecutionResult.success_result(
                message="Successfully updated discount",
                response_data=discount_node,
                confirmed_state=verified_state.state,
                http_status_code=200,
            )

        except PlatformAPIError:
            raise
        except Exception as e:
            logger.exception("Error during discount update")
            return ExecutionResult.failure_result(
                message=f"Unexpected error: {e}",
                is_retryable=False,
            )

    async def _execute_discount_delete(
        self,
        entity_id: str,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Delete a discount.

        Args:
            entity_id: Discount GID
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        gid = self._ensure_gid(entity_id, "discount")

        mutation = """
        mutation discountCodeDelete($id: ID!) {
            discountCodeDelete(id: $id) {
                deletedCodeDiscountId
                userErrors {
                    field
                    message
                }
            }
        }
        """

        log_entry = self._log_request("POST", self.graphql_url, {"id": gid})
        logger.info("Executing Shopify discount delete", extra=log_entry)

        try:
            data = await self._execute_graphql(mutation, {"id": gid})

            result = data.get("discountCodeDelete", {})
            user_errors = result.get("userErrors", [])

            if user_errors:
                error_msg = "; ".join(e.get("message", "") for e in user_errors)
                return ExecutionResult.failure_result(
                    message=f"Discount deletion failed: {error_msg}",
                    error_code="USER_ERROR",
                    error_details={"userErrors": user_errors},
                    is_retryable=False,
                )

            deleted_id = result.get("deletedCodeDiscountId")

            return ExecutionResult.success_result(
                message=f"Successfully deleted discount",
                response_data={"deletedId": deleted_id},
                http_status_code=200,
            )

        except PlatformAPIError:
            raise
        except Exception as e:
            logger.exception("Error during discount deletion")
            return ExecutionResult.failure_result(
                message=f"Unexpected error: {e}",
                is_retryable=False,
            )

    async def _execute_inventory_update(
        self,
        entity_id: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Update inventory levels.

        Args:
            entity_id: Inventory level or item ID
            params: Parameters:
                - available_delta: Change in available quantity (+/-)
                - location_id: Location GID (required if entity is inventory_item)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        delta = params.get("available_delta")
        if delta is None:
            return ExecutionResult.failure_result(
                message="available_delta is required for inventory update",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        # Determine mutation based on whether we have a location
        location_id = params.get("location_id")

        mutation = """
        mutation inventoryAdjustQuantities($input: InventoryAdjustQuantitiesInput!) {
            inventoryAdjustQuantities(input: $input) {
                inventoryAdjustmentGroup {
                    createdAt
                    reason
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        inventory_item_id = self._ensure_gid(entity_id, "inventory_item")

        input_data = {
            "reason": params.get("reason", "correction"),
            "name": f"AI Action - {idempotency_key[:8]}",
            "changes": [
                {
                    "inventoryItemId": inventory_item_id,
                    "locationId": location_id or params.get("location_id"),
                    "delta": int(delta),
                }
            ],
        }

        log_entry = self._log_request("POST", self.graphql_url, {
            "inventory_item_id": inventory_item_id,
            "delta": delta
        })
        logger.info("Executing Shopify inventory update", extra=log_entry)

        try:
            data = await self._execute_graphql(mutation, {"input": input_data})

            result = data.get("inventoryAdjustQuantities", {})
            user_errors = result.get("userErrors", [])

            if user_errors:
                error_msg = "; ".join(e.get("message", "") for e in user_errors)
                return ExecutionResult.failure_result(
                    message=f"Inventory update failed: {error_msg}",
                    error_code="USER_ERROR",
                    error_details={"userErrors": user_errors},
                    is_retryable=False,
                )

            adjustment_group = result.get("inventoryAdjustmentGroup", {})

            return ExecutionResult.success_result(
                message=f"Successfully adjusted inventory by {delta}",
                response_data=adjustment_group,
                http_status_code=200,
            )

        except PlatformAPIError:
            raise
        except Exception as e:
            logger.exception("Error during inventory update")
            return ExecutionResult.failure_result(
                message=f"Unexpected error: {e}",
                is_retryable=False,
            )

    async def _execute_price_update(
        self,
        entity_id: str,
        params: dict,
        idempotency_key: str,
    ) -> ExecutionResult:
        """
        Update product variant price.

        Args:
            entity_id: Product variant GID
            params: Parameters:
                - price: New price
                - compare_at_price: Compare at price (optional)
            idempotency_key: Key for idempotent execution

        Returns:
            ExecutionResult with outcome
        """
        price = params.get("price")
        if price is None:
            return ExecutionResult.failure_result(
                message="price is required for price update",
                error_code="MISSING_PARAMETER",
                is_retryable=False,
            )

        gid = self._ensure_gid(entity_id, "variant")

        mutation = """
        mutation productVariantUpdate($input: ProductVariantInput!) {
            productVariantUpdate(input: $input) {
                productVariant {
                    id
                    price
                    compareAtPrice
                }
                userErrors {
                    field
                    message
                }
            }
        }
        """

        variant_input = {
            "id": gid,
            "price": str(price),
        }

        if "compare_at_price" in params:
            variant_input["compareAtPrice"] = str(params["compare_at_price"])

        log_entry = self._log_request("POST", self.graphql_url, variant_input)
        logger.info("Executing Shopify price update", extra=log_entry)

        try:
            data = await self._execute_graphql(mutation, {"input": variant_input})

            result = data.get("productVariantUpdate", {})
            user_errors = result.get("userErrors", [])

            if user_errors:
                error_msg = "; ".join(e.get("message", "") for e in user_errors)
                return ExecutionResult.failure_result(
                    message=f"Price update failed: {error_msg}",
                    error_code="USER_ERROR",
                    error_details={"userErrors": user_errors},
                    is_retryable=False,
                )

            variant = result.get("productVariant", {})

            return ExecutionResult.success_result(
                message=f"Successfully updated price to {price}",
                response_data=variant,
                confirmed_state=variant,
                http_status_code=200,
            )

        except PlatformAPIError:
            raise
        except Exception as e:
            logger.exception("Error during price update")
            return ExecutionResult.failure_result(
                message=f"Unexpected error: {e}",
                is_retryable=False,
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
        Generate parameters to reverse a Shopify action.

        Args:
            action_type: Type of action that was executed
            before_state: Entity state before the action

        Returns:
            Dictionary of parameters for rollback
        """
        if action_type == "update_product":
            # Restore original product fields
            params = {}
            for field in ["title", "status", "productType", "vendor", "tags"]:
                if field in before_state:
                    params[field] = before_state[field]
            return params

        elif action_type == "update_product_status":
            # Restore original status
            return {"status": before_state.get("status", ShopifyProductStatus.ACTIVE)}

        elif action_type == "create_discount":
            # Rollback is delete - return the discount ID
            return {"discount_id": before_state.get("id")}

        elif action_type == "update_discount":
            # Restore original discount settings
            discount = before_state.get("discount", {})
            return {
                "title": discount.get("title"),
                "ends_at": discount.get("endsAt"),
                "usage_limit": discount.get("usageLimit"),
            }

        elif action_type == "delete_discount":
            # Cannot easily rollback a delete - would need to recreate
            # Return original state for reference
            logger.warning("Discount deletion cannot be automatically rolled back")
            return {"original_state": before_state, "manual_recreate_required": True}

        elif action_type == "update_inventory":
            # Reverse the delta
            original_available = before_state.get("available", 0)
            return {
                "target_quantity": original_available,
                "reason": "rollback",
            }

        elif action_type == "update_price":
            # Restore original price
            variants = before_state.get("variants", {}).get("edges", [])
            if variants:
                variant = variants[0].get("node", {})
                return {
                    "price": variant.get("price"),
                    "compare_at_price": variant.get("compareAtPrice"),
                }
            return {}

        else:
            logger.warning(f"Cannot generate rollback for unknown action type: {action_type}")
            return {}

    def _get_reverse_action_type(self, action_type: str) -> str:
        """Get the reverse action type for rollback."""
        reverse_map = {
            "update_product": "update_product",
            "update_product_status": "update_product_status",
            "create_discount": "delete_discount",
            "update_discount": "update_discount",
            "delete_discount": "create_discount",  # Note: requires full params
            "update_inventory": "update_inventory",
            "update_price": "update_price",
        }
        return reverse_map.get(action_type, action_type)
