"""
Plans Repository for admin plan management.

Plans are global (not tenant-scoped) - they define available subscription tiers.
Admin operations do not require tenant context.
"""

import uuid
import logging
from typing import Optional, List
from datetime import datetime, timezone

from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import IntegrityError

from src.models.plan import Plan, PlanFeature

logger = logging.getLogger(__name__)


class PlanRepositoryError(Exception):
    """Base exception for plan repository errors."""
    pass


class PlanNotFoundError(PlanRepositoryError):
    """Plan not found."""
    pass


class PlanAlreadyExistsError(PlanRepositoryError):
    """Plan with same name/id already exists."""
    pass


class PlansRepository:
    """
    Repository for Plan and PlanFeature operations.

    Plans are global entities - not tenant-scoped.
    Used by admin service for plan management.
    """

    def __init__(self, db_session: Session):
        """
        Initialize plans repository.

        Args:
            db_session: Database session
        """
        self.db = db_session

    def get_by_id(self, plan_id: str) -> Optional[Plan]:
        """
        Get a plan by ID.

        Args:
            plan_id: Plan identifier

        Returns:
            Plan if found, None otherwise
        """
        return self.db.query(Plan).filter(Plan.id == plan_id).first()

    def get_by_name(self, name: str) -> Optional[Plan]:
        """
        Get a plan by name.

        Args:
            name: Plan name (unique)

        Returns:
            Plan if found, None otherwise
        """
        return self.db.query(Plan).filter(Plan.name == name).first()

    def get_all(
        self,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0,
        include_features: bool = False
    ) -> List[Plan]:
        """
        Get all plans with pagination.

        Args:
            include_inactive: Whether to include inactive plans
            limit: Maximum number of plans to return
            offset: Number of plans to skip
            include_features: Whether to eager load plan features (avoids N+1 queries)

        Returns:
            List of Plan objects
        """
        query = self.db.query(Plan)

        if include_features:
            query = query.options(selectinload(Plan.features))

        if not include_inactive:
            query = query.filter(Plan.is_active == True)

        return query.order_by(Plan.price_monthly_cents.asc().nullsfirst()).offset(offset).limit(limit).all()

    def count(self, include_inactive: bool = False) -> int:
        """
        Count total plans.

        Args:
            include_inactive: Whether to include inactive plans

        Returns:
            Total count of plans
        """
        query = self.db.query(Plan)

        if not include_inactive:
            query = query.filter(Plan.is_active == True)

        return query.count()

    def create(
        self,
        name: str,
        display_name: str,
        description: Optional[str] = None,
        price_monthly_cents: Optional[int] = None,
        price_yearly_cents: Optional[int] = None,
        shopify_plan_id: Optional[str] = None,
        is_active: bool = True,
        plan_id: Optional[str] = None
    ) -> Plan:
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
            plan_id: Optional custom plan ID (auto-generated if not provided)

        Returns:
            Created Plan object

        Raises:
            PlanAlreadyExistsError: If plan with same name exists
        """
        # Generate plan ID if not provided
        if not plan_id:
            plan_id = f"plan_{name.lower().replace(' ', '_')}"

        # Check for existing plan
        existing = self.get_by_name(name)
        if existing:
            raise PlanAlreadyExistsError(f"Plan with name '{name}' already exists")

        existing_by_id = self.get_by_id(plan_id)
        if existing_by_id:
            raise PlanAlreadyExistsError(f"Plan with ID '{plan_id}' already exists")

        plan = Plan(
            id=plan_id,
            name=name,
            display_name=display_name,
            description=description,
            price_monthly_cents=price_monthly_cents,
            price_yearly_cents=price_yearly_cents,
            shopify_plan_id=shopify_plan_id,
            is_active=is_active
        )

        try:
            self.db.add(plan)
            self.db.flush()

            logger.info("Plan created", extra={
                "plan_id": plan_id,
                "name": name,
                "price_monthly_cents": price_monthly_cents
            })

            return plan
        except IntegrityError as e:
            self.db.rollback()
            logger.error("Failed to create plan - integrity error", extra={
                "plan_id": plan_id,
                "name": name,
                "error": str(e)
            })
            raise PlanAlreadyExistsError(f"Plan creation failed: {e}")

    def update(
        self,
        plan_id: str,
        name: Optional[str] = None,
        display_name: Optional[str] = None,
        description: Optional[str] = None,
        price_monthly_cents: Optional[int] = None,
        price_yearly_cents: Optional[int] = None,
        shopify_plan_id: Optional[str] = None,
        is_active: Optional[bool] = None
    ) -> Plan:
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

        Returns:
            Updated Plan object

        Raises:
            PlanNotFoundError: If plan doesn't exist
            PlanAlreadyExistsError: If new name conflicts with existing plan
        """
        plan = self.get_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(f"Plan not found: {plan_id}")

        # Check for name conflict if changing name
        if name and name != plan.name:
            existing = self.get_by_name(name)
            if existing:
                raise PlanAlreadyExistsError(f"Plan with name '{name}' already exists")
            plan.name = name

        # Update fields if provided
        if display_name is not None:
            plan.display_name = display_name
        if description is not None:
            plan.description = description
        if price_monthly_cents is not None:
            plan.price_monthly_cents = price_monthly_cents
        if price_yearly_cents is not None:
            plan.price_yearly_cents = price_yearly_cents
        if shopify_plan_id is not None:
            plan.shopify_plan_id = shopify_plan_id
        if is_active is not None:
            plan.is_active = is_active

        self.db.flush()

        logger.info("Plan updated", extra={
            "plan_id": plan_id,
            "updated_fields": {
                k: v for k, v in {
                    "name": name,
                    "display_name": display_name,
                    "description": description,
                    "price_monthly_cents": price_monthly_cents,
                    "price_yearly_cents": price_yearly_cents,
                    "shopify_plan_id": shopify_plan_id,
                    "is_active": is_active
                }.items() if v is not None
            }
        })

        return plan

    def delete(self, plan_id: str) -> bool:
        """
        Delete a plan.

        Warning: This will cascade delete all plan features.
        Consider using soft delete (is_active=False) instead.

        Args:
            plan_id: Plan identifier

        Returns:
            True if deleted, False if not found
        """
        plan = self.get_by_id(plan_id)
        if not plan:
            return False

        self.db.delete(plan)
        self.db.flush()

        logger.info("Plan deleted", extra={"plan_id": plan_id})

        return True

    # PlanFeature operations

    def get_features(self, plan_id: str) -> List[PlanFeature]:
        """
        Get all features for a plan.

        Args:
            plan_id: Plan identifier

        Returns:
            List of PlanFeature objects
        """
        return self.db.query(PlanFeature).filter(
            PlanFeature.plan_id == plan_id
        ).all()

    def get_feature(self, plan_id: str, feature_key: str) -> Optional[PlanFeature]:
        """
        Get a specific feature for a plan.

        Args:
            plan_id: Plan identifier
            feature_key: Feature key

        Returns:
            PlanFeature if found, None otherwise
        """
        return self.db.query(PlanFeature).filter(
            PlanFeature.plan_id == plan_id,
            PlanFeature.feature_key == feature_key
        ).first()

    def add_feature(
        self,
        plan_id: str,
        feature_key: str,
        is_enabled: bool = True,
        limit_value: Optional[int] = None,
        limits: Optional[dict] = None
    ) -> PlanFeature:
        """
        Add a feature to a plan.

        Args:
            plan_id: Plan identifier
            feature_key: Feature key (e.g., 'ai_insights')
            is_enabled: Whether feature is enabled
            limit_value: Optional usage limit
            limits: Optional JSONB limits object

        Returns:
            Created PlanFeature object

        Raises:
            PlanNotFoundError: If plan doesn't exist
        """
        # Verify plan exists
        plan = self.get_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(f"Plan not found: {plan_id}")

        # Check if feature already exists
        existing = self.get_feature(plan_id, feature_key)
        if existing:
            # Update existing feature
            existing.is_enabled = is_enabled
            existing.limit_value = limit_value
            existing.limits = limits
            self.db.flush()
            return existing

        feature = PlanFeature(
            id=str(uuid.uuid4()),
            plan_id=plan_id,
            feature_key=feature_key,
            is_enabled=is_enabled,
            limit_value=limit_value,
            limits=limits
        )

        self.db.add(feature)
        self.db.flush()

        logger.info("Plan feature added", extra={
            "plan_id": plan_id,
            "feature_key": feature_key,
            "is_enabled": is_enabled
        })

        return feature

    def update_feature(
        self,
        plan_id: str,
        feature_key: str,
        is_enabled: Optional[bool] = None,
        limit_value: Optional[int] = None,
        limits: Optional[dict] = None
    ) -> Optional[PlanFeature]:
        """
        Update a plan feature.

        Args:
            plan_id: Plan identifier
            feature_key: Feature key
            is_enabled: New enabled status (optional)
            limit_value: New limit value (optional)
            limits: New limits object (optional)

        Returns:
            Updated PlanFeature if found, None otherwise
        """
        feature = self.get_feature(plan_id, feature_key)
        if not feature:
            return None

        if is_enabled is not None:
            feature.is_enabled = is_enabled
        if limit_value is not None:
            feature.limit_value = limit_value
        if limits is not None:
            feature.limits = limits

        self.db.flush()

        logger.info("Plan feature updated", extra={
            "plan_id": plan_id,
            "feature_key": feature_key
        })

        return feature

    def remove_feature(self, plan_id: str, feature_key: str) -> bool:
        """
        Remove a feature from a plan.

        Args:
            plan_id: Plan identifier
            feature_key: Feature key

        Returns:
            True if removed, False if not found
        """
        feature = self.get_feature(plan_id, feature_key)
        if not feature:
            return False

        self.db.delete(feature)
        self.db.flush()

        logger.info("Plan feature removed", extra={
            "plan_id": plan_id,
            "feature_key": feature_key
        })

        return True

    def set_features(
        self,
        plan_id: str,
        features: List[dict]
    ) -> List[PlanFeature]:
        """
        Set all features for a plan (replaces existing).

        Args:
            plan_id: Plan identifier
            features: List of feature dicts with keys:
                - feature_key: str (required)
                - is_enabled: bool (default True)
                - limit_value: int (optional)
                - limits: dict (optional)

        Returns:
            List of PlanFeature objects

        Raises:
            PlanNotFoundError: If plan doesn't exist
        """
        # Verify plan exists
        plan = self.get_by_id(plan_id)
        if not plan:
            raise PlanNotFoundError(f"Plan not found: {plan_id}")

        # Delete existing features
        self.db.query(PlanFeature).filter(
            PlanFeature.plan_id == plan_id
        ).delete()

        # Add new features
        created_features = []
        for feature_data in features:
            feature = PlanFeature(
                id=str(uuid.uuid4()),
                plan_id=plan_id,
                feature_key=feature_data["feature_key"],
                is_enabled=feature_data.get("is_enabled", True),
                limit_value=feature_data.get("limit_value"),
                limits=feature_data.get("limits")
            )
            self.db.add(feature)
            created_features.append(feature)

        self.db.flush()

        logger.info("Plan features set", extra={
            "plan_id": plan_id,
            "feature_count": len(created_features)
        })

        return created_features
