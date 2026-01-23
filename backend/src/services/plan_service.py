"""
Plan Service for admin plan management.

Handles:
- Creating and updating plans
- Managing plan features
- Validating Shopify plan sync
- Plan lifecycle operations

SECURITY: Admin operations require admin role verification.
"""

import logging
from typing import Optional, List
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from src.repositories.plans_repo import (
    PlansRepository,
    PlanRepositoryError,
    PlanNotFoundError,
    PlanAlreadyExistsError
)
from src.models.plan import Plan, PlanFeature
from src.integrations.shopify.billing_client import (
    ShopifyBillingClient,
    ShopifyAPIError,
    get_billing_client
)

logger = logging.getLogger(__name__)


@dataclass
class PlanInfo:
    """Plan information with features."""
    id: str
    name: str
    display_name: str
    description: Optional[str]
    price_monthly_cents: Optional[int]
    price_yearly_cents: Optional[int]
    shopify_plan_id: Optional[str]
    is_active: bool
    features: List[dict] = field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


@dataclass
class ShopifyPlanValidationResult:
    """Result of validating Shopify plan configuration."""
    is_valid: bool
    shopify_plan_id: Optional[str]
    plan_name: Optional[str]
    price_amount: Optional[float]
    currency_code: Optional[str]
    error: Optional[str] = None


class PlanServiceError(Exception):
    """Base exception for plan service errors."""
    pass


class PlanNotFoundServiceError(PlanServiceError):
    """Plan not found."""
    pass


class PlanValidationError(PlanServiceError):
    """Plan validation failed."""
    pass


class ShopifyValidationError(PlanServiceError):
    """Shopify plan validation failed."""
    pass


class PlanService:
    """
    Service for admin plan management operations.

    All methods require admin authorization (verified at route level).
    Plans are global entities - not tenant-scoped.
    """

    def __init__(self, db_session: Session):
        """
        Initialize plan service.

        Args:
            db_session: Database session
        """
        self.db = db_session
        self.repo = PlansRepository(db_session)

    def get_plan(self, plan_id: str) -> PlanInfo:
        """
        Get a plan with its features.

        Args:
            plan_id: Plan identifier

        Returns:
            PlanInfo with full plan details

        Raises:
            PlanNotFoundServiceError: If plan doesn't exist
        """
        plan = self.repo.get_by_id(plan_id)
        if not plan:
            raise PlanNotFoundServiceError(f"Plan not found: {plan_id}")

        features = self.repo.get_features(plan_id)

        return PlanInfo(
            id=plan.id,
            name=plan.name,
            display_name=plan.display_name,
            description=plan.description,
            price_monthly_cents=plan.price_monthly_cents,
            price_yearly_cents=plan.price_yearly_cents,
            shopify_plan_id=plan.shopify_plan_id,
            is_active=plan.is_active,
            features=[
                {
                    "feature_key": f.feature_key,
                    "is_enabled": f.is_enabled,
                    "limit_value": f.limit_value,
                    "limits": f.limits
                }
                for f in features
            ],
            created_at=plan.created_at,
            updated_at=plan.updated_at
        )

    def list_plans(
        self,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[PlanInfo], int]:
        """
        List all plans with pagination.

        Args:
            include_inactive: Whether to include inactive plans
            limit: Maximum number of plans to return
            offset: Number of plans to skip

        Returns:
            Tuple of (list of PlanInfo, total count)
        """
        plans = self.repo.get_all(
            include_inactive=include_inactive,
            limit=limit,
            offset=offset,
            include_features=True
        )
        total = self.repo.count(include_inactive=include_inactive)

        plan_infos = []
        for plan in plans:
            plan_infos.append(PlanInfo(
                id=plan.id,
                name=plan.name,
                display_name=plan.display_name,
                description=plan.description,
                price_monthly_cents=plan.price_monthly_cents,
                price_yearly_cents=plan.price_yearly_cents,
                shopify_plan_id=plan.shopify_plan_id,
                is_active=plan.is_active,
                features=[
                    {
                        "feature_key": f.feature_key,
                        "is_enabled": f.is_enabled,
                        "limit_value": f.limit_value,
                        "limits": f.limits
                    }
                    for f in plan.features
                ],
                created_at=plan.created_at,
                updated_at=plan.updated_at
            ))

        return plan_infos, total

    def create_plan(
        self,
        name: str,
        display_name: str,
        description: Optional[str] = None,
        price_monthly_cents: Optional[int] = None,
        price_yearly_cents: Optional[int] = None,
        shopify_plan_id: Optional[str] = None,
        is_active: bool = True,
        features: Optional[List[dict]] = None
    ) -> PlanInfo:
        """
        Create a new plan.

        Args:
            name: Unique plan name (e.g., 'growth')
            display_name: Human-readable name (e.g., 'Growth')
            description: Plan description
            price_monthly_cents: Monthly price in cents
            price_yearly_cents: Yearly price in cents
            shopify_plan_id: Shopify Billing API plan ID
            is_active: Whether plan is available for subscriptions
            features: Optional list of features to add

        Returns:
            Created PlanInfo

        Raises:
            PlanValidationError: If validation fails
            PlanServiceError: If creation fails
        """
        # Validate input
        self._validate_plan_data(
            name=name,
            display_name=display_name,
            price_monthly_cents=price_monthly_cents,
            price_yearly_cents=price_yearly_cents
        )

        try:
            plan = self.repo.create(
                name=name,
                display_name=display_name,
                description=description,
                price_monthly_cents=price_monthly_cents,
                price_yearly_cents=price_yearly_cents,
                shopify_plan_id=shopify_plan_id,
                is_active=is_active
            )

            # Add features if provided
            created_features = []
            if features:
                for feature_data in features:
                    feature = self.repo.add_feature(
                        plan_id=plan.id,
                        feature_key=feature_data["feature_key"],
                        is_enabled=feature_data.get("is_enabled", True),
                        limit_value=feature_data.get("limit_value"),
                        limits=feature_data.get("limits")
                    )
                    created_features.append({
                        "feature_key": feature.feature_key,
                        "is_enabled": feature.is_enabled,
                        "limit_value": feature.limit_value,
                        "limits": feature.limits
                    })

            self.db.commit()

            logger.info("Plan created via service", extra={
                "plan_id": plan.id,
                "name": name,
                "feature_count": len(created_features)
            })

            return PlanInfo(
                id=plan.id,
                name=plan.name,
                display_name=plan.display_name,
                description=plan.description,
                price_monthly_cents=plan.price_monthly_cents,
                price_yearly_cents=plan.price_yearly_cents,
                shopify_plan_id=plan.shopify_plan_id,
                is_active=plan.is_active,
                features=created_features,
                created_at=plan.created_at,
                updated_at=plan.updated_at
            )

        except PlanAlreadyExistsError as e:
            self.db.rollback()
            raise PlanValidationError(str(e))
        except PlanRepositoryError as e:
            self.db.rollback()
            logger.error("Failed to create plan", extra={"error": str(e)})
            raise PlanServiceError(f"Failed to create plan: {e}")

    def update_plan(
        self,
        plan_id: str,
        name: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        price_monthly_cents: Optional[int] = None,
        price_yearly_cents: Optional[int] = None,
        shopify_plan_id: Optional[str] = None,
        is_active: Optional[bool] = None,
        features: Optional[List[dict]] = None
    ) -> PlanInfo:
        """
        Update an existing plan.

        Args:
            plan_id: Plan identifier
            name: New plan name (optional)
            display_name: New display name (optional)
            description: New description (optional)
            price_monthly_cents: New monthly price in cents (optional)
            price_yearly_cents: New yearly price in cents (optional)
            shopify_plan_id: New Shopify plan ID (optional)
            is_active: New active status (optional)
            features: New features list (replaces existing if provided)

        Returns:
            Updated PlanInfo

        Raises:
            PlanNotFoundServiceError: If plan doesn't exist
            PlanValidationError: If validation fails
            PlanServiceError: If update fails
        """
        # Validate input if provided
        if any([name, display_name, price_monthly_cents, price_yearly_cents]):
            existing = self.repo.get_by_id(plan_id)
            if not existing:
                raise PlanNotFoundServiceError(f"Plan not found: {plan_id}")

            self._validate_plan_data(
                name=name or existing.name,
                display_name=display_name or existing.display_name,
                price_monthly_cents=price_monthly_cents if price_monthly_cents is not None else existing.price_monthly_cents,
                price_yearly_cents=price_yearly_cents if price_yearly_cents is not None else existing.price_yearly_cents
            )

        try:
            plan = self.repo.update(
                plan_id=plan_id,
                name=name,
                display_name=display_name,
                description=description,
                price_monthly_cents=price_monthly_cents,
                price_yearly_cents=price_yearly_cents,
                shopify_plan_id=shopify_plan_id,
                is_active=is_active
            )

            # Update features if provided
            updated_features = []
            if features is not None:
                feature_objs = self.repo.set_features(plan_id, features)
                updated_features = [
                    {
                        "feature_key": f.feature_key,
                        "is_enabled": f.is_enabled,
                        "limit_value": f.limit_value,
                        "limits": f.limits
                    }
                    for f in feature_objs
                ]
            else:
                # Get existing features
                feature_objs = self.repo.get_features(plan_id)
                updated_features = [
                    {
                        "feature_key": f.feature_key,
                        "is_enabled": f.is_enabled,
                        "limit_value": f.limit_value,
                        "limits": f.limits
                    }
                    for f in feature_objs
                ]

            self.db.commit()

            logger.info("Plan updated via service", extra={
                "plan_id": plan_id,
                "updated_fields": {
                    k: v for k, v in {
                        "name": name,
                        "display_name": display_name,
                        "price_monthly_cents": price_monthly_cents,
                        "is_active": is_active
                    }.items() if v is not None
                }
            })

            return PlanInfo(
                id=plan.id,
                name=plan.name,
                display_name=plan.display_name,
                description=plan.description,
                price_monthly_cents=plan.price_monthly_cents,
                price_yearly_cents=plan.price_yearly_cents,
                shopify_plan_id=plan.shopify_plan_id,
                is_active=plan.is_active,
                features=updated_features,
                created_at=plan.created_at,
                updated_at=plan.updated_at
            )

        except PlanNotFoundError:
            self.db.rollback()
            raise PlanNotFoundServiceError(f"Plan not found: {plan_id}")
        except PlanAlreadyExistsError as e:
            self.db.rollback()
            raise PlanValidationError(str(e))
        except PlanRepositoryError as e:
            self.db.rollback()
            logger.error("Failed to update plan", extra={
                "plan_id": plan_id,
                "error": str(e)
            })
            raise PlanServiceError(f"Failed to update plan: {e}")

    def toggle_feature(
        self,
        plan_id: str,
        feature_key: str,
        is_enabled: bool
    ) -> dict:
        """
        Toggle a specific feature on/off for a plan.

        Args:
            plan_id: Plan identifier
            feature_key: Feature key
            is_enabled: New enabled status

        Returns:
            Updated feature dict

        Raises:
            PlanNotFoundServiceError: If plan doesn't exist
            PlanServiceError: If feature doesn't exist
        """
        try:
            feature = self.repo.update_feature(
                plan_id=plan_id,
                feature_key=feature_key,
                is_enabled=is_enabled
            )

            if not feature:
                # Try to create the feature
                feature = self.repo.add_feature(
                    plan_id=plan_id,
                    feature_key=feature_key,
                    is_enabled=is_enabled
                )

            self.db.commit()

            logger.info("Feature toggled", extra={
                "plan_id": plan_id,
                "feature_key": feature_key,
                "is_enabled": is_enabled
            })

            return {
                "feature_key": feature.feature_key,
                "is_enabled": feature.is_enabled,
                "limit_value": feature.limit_value,
                "limits": feature.limits
            }

        except PlanNotFoundError:
            self.db.rollback()
            raise PlanNotFoundServiceError(f"Plan not found: {plan_id}")
        except PlanRepositoryError as e:
            self.db.rollback()
            raise PlanServiceError(f"Failed to toggle feature: {e}")

    def delete_plan(self, plan_id: str) -> bool:
        """
        Delete a plan (soft delete recommended - use update with is_active=False).

        Args:
            plan_id: Plan identifier

        Returns:
            True if deleted

        Raises:
            PlanNotFoundServiceError: If plan doesn't exist
        """
        result = self.repo.delete(plan_id)
        if not result:
            raise PlanNotFoundServiceError(f"Plan not found: {plan_id}")

        self.db.commit()

        logger.info("Plan deleted via service", extra={"plan_id": plan_id})

        return True

    async def validate_shopify_plan(
        self,
        shop_domain: str,
        access_token: str,
        shopify_subscription_id: Optional[str] = None
    ) -> ShopifyPlanValidationResult:
        """
        Validate that a Shopify plan/subscription exists and is accessible.

        This verifies that the Shopify Billing API can be reached and
        any existing subscription can be queried.

        Args:
            shop_domain: Shopify store domain
            access_token: Decrypted Shopify access token
            shopify_subscription_id: Optional subscription ID to validate

        Returns:
            ShopifyPlanValidationResult with validation status
        """
        try:
            async with get_billing_client(shop_domain, access_token) as client:
                if shopify_subscription_id:
                    # Validate specific subscription
                    subscription = await client.get_subscription(shopify_subscription_id)
                    if subscription:
                        return ShopifyPlanValidationResult(
                            is_valid=True,
                            shopify_plan_id=subscription.id,
                            plan_name=subscription.name,
                            price_amount=None,  # Would need to parse from line_items
                            currency_code=None,
                            error=None
                        )
                    else:
                        return ShopifyPlanValidationResult(
                            is_valid=False,
                            shopify_plan_id=shopify_subscription_id,
                            plan_name=None,
                            price_amount=None,
                            currency_code=None,
                            error=f"Subscription not found: {shopify_subscription_id}"
                        )
                else:
                    # Just verify API access by getting active subscriptions
                    subscriptions = await client.get_active_subscriptions()
                    return ShopifyPlanValidationResult(
                        is_valid=True,
                        shopify_plan_id=subscriptions[0].id if subscriptions else None,
                        plan_name=subscriptions[0].name if subscriptions else None,
                        price_amount=None,
                        currency_code=None,
                        error=None
                    )

        except ShopifyAPIError as e:
            logger.error("Shopify plan validation failed", extra={
                "shop_domain": shop_domain,
                "error": str(e)
            })
            return ShopifyPlanValidationResult(
                is_valid=False,
                shopify_plan_id=shopify_subscription_id,
                plan_name=None,
                price_amount=None,
                currency_code=None,
                error=str(e)
            )

    async def sync_plan_to_shopify(
        self,
        plan_id: str,
        shop_domain: str,
        access_token: str
    ) -> ShopifyPlanValidationResult:
        """
        Verify that a plan can be synced to Shopify Billing.

        This validates the plan configuration is compatible with
        Shopify Billing API requirements.

        Args:
            plan_id: Local plan identifier
            shop_domain: Shopify store domain
            access_token: Decrypted Shopify access token

        Returns:
            ShopifyPlanValidationResult with sync status

        Raises:
            PlanNotFoundServiceError: If plan doesn't exist
        """
        plan = self.repo.get_by_id(plan_id)
        if not plan:
            raise PlanNotFoundServiceError(f"Plan not found: {plan_id}")

        # Validate plan has required pricing
        if plan.price_monthly_cents is None and plan.price_yearly_cents is None:
            # Free plan - no Shopify sync needed
            return ShopifyPlanValidationResult(
                is_valid=True,
                shopify_plan_id=None,
                plan_name=plan.display_name,
                price_amount=0,
                currency_code="USD",
                error=None
            )

        # Validate Shopify API access
        validation = await self.validate_shopify_plan(
            shop_domain=shop_domain,
            access_token=access_token,
            shopify_subscription_id=plan.shopify_plan_id
        )

        if not validation.is_valid:
            logger.warning("Plan sync validation failed", extra={
                "plan_id": plan_id,
                "error": validation.error
            })

        return validation

    def _validate_plan_data(
        self,
        name: str,
        display_name: str,
        price_monthly_cents: Optional[int],
        price_yearly_cents: Optional[int]
    ) -> None:
        """
        Validate plan data before create/update.

        Args:
            name: Plan name
            display_name: Display name
            price_monthly_cents: Monthly price
            price_yearly_cents: Yearly price

        Raises:
            PlanValidationError: If validation fails
        """
        errors = []

        if not name or len(name.strip()) == 0:
            errors.append("Plan name is required")
        elif len(name) > 100:
            errors.append("Plan name must be 100 characters or less")
        elif not name.replace("_", "").replace("-", "").isalnum():
            errors.append("Plan name must contain only alphanumeric characters, underscores, or hyphens")

        if not display_name or len(display_name.strip()) == 0:
            errors.append("Display name is required")
        elif len(display_name) > 255:
            errors.append("Display name must be 255 characters or less")

        if price_monthly_cents is not None:
            if price_monthly_cents < 0:
                errors.append("Monthly price cannot be negative")
            if price_monthly_cents > 99999999:  # $999,999.99 max
                errors.append("Monthly price exceeds maximum allowed")

        if price_yearly_cents is not None:
            if price_yearly_cents < 0:
                errors.append("Yearly price cannot be negative")
            if price_yearly_cents > 99999999:
                errors.append("Yearly price exceeds maximum allowed")

        if errors:
            raise PlanValidationError("; ".join(errors))
