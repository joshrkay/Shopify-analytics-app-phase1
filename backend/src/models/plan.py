"""
Plan and PlanFeature models for subscription tiers.

Plans are GLOBAL (not tenant-scoped) - they define the product offerings.
PlanFeatures define which features are available on each plan.
"""

from sqlalchemy import (
    Column, String, Text, Integer, Boolean, Enum,
    ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship

from src.models.base import Base, TimestampMixin, generate_uuid


class Plan(Base, TimestampMixin):
    """
    Defines pricing tiers and their limits.

    Plans are GLOBAL - they define product offerings, not tenant data.
    Each plan maps to a Shopify recurring charge.
    """

    __tablename__ = "plans"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )

    # Plan identification
    slug = Column(
        String(50),
        nullable=False,
        unique=True,
        index=True,
        comment="URL-safe identifier (free, pro, enterprise)"
    )
    name = Column(
        String(100),
        nullable=False,
        comment="Display name (Free, Pro, Enterprise)"
    )
    description = Column(
        Text,
        nullable=True,
        comment="Plan description for pricing page"
    )

    # Pricing (in cents to avoid floating point issues)
    price_cents = Column(
        Integer,
        nullable=False,
        default=0,
        comment="Monthly price in cents (2900 = $29.00)"
    )
    currency = Column(
        String(10),
        default="USD",
        comment="Currency code"
    )
    billing_interval = Column(
        Enum("monthly", "annual", name="billing_interval"),
        default="monthly",
        comment="Billing frequency"
    )

    # Shopify Billing integration
    shopify_plan_name = Column(
        String(100),
        nullable=True,
        comment="Name shown in Shopify billing UI"
    )
    is_test = Column(
        Boolean,
        default=False,
        comment="Use Shopify test charges (for development)"
    )

    # Plan status
    is_active = Column(
        Boolean,
        default=True,
        index=True,
        comment="Whether plan is available for new subscriptions"
    )
    is_public = Column(
        Boolean,
        default=True,
        comment="Show on public pricing page"
    )
    sort_order = Column(
        Integer,
        default=0,
        comment="Display order on pricing page"
    )

    # Trial settings
    trial_days = Column(
        Integer,
        default=0,
        comment="Number of trial days (0 = no trial)"
    )

    # Usage limits (NULL = unlimited)
    api_calls_limit = Column(
        Integer,
        nullable=True,
        comment="Monthly API call limit (NULL = unlimited)"
    )
    data_retention_days = Column(
        Integer,
        default=30,
        comment="Days to retain historical data"
    )

    # Relationships
    features = relationship(
        "PlanFeature",
        back_populates="plan",
        lazy="selectin",
        cascade="all, delete-orphan"
    )
    subscriptions = relationship(
        "Subscription",
        back_populates="plan",
        lazy="dynamic"
    )

    def __repr__(self) -> str:
        return f"<Plan(slug={self.slug}, price_cents={self.price_cents})>"

    @property
    def price_dollars(self) -> float:
        """Get price in dollars."""
        return self.price_cents / 100

    @property
    def has_trial(self) -> bool:
        """Check if plan has a trial period."""
        return self.trial_days > 0

    @property
    def is_free(self) -> bool:
        """Check if this is a free plan."""
        return self.price_cents == 0


class PlanFeature(Base, TimestampMixin):
    """
    Feature entitlements per plan.

    Each row defines a feature's availability and limits for a specific plan.
    Used for feature gating in the billing middleware.
    """

    __tablename__ = "plan_features"

    # Primary key
    id = Column(
        String(36),
        primary_key=True,
        default=generate_uuid
    )

    # Foreign key to plan
    plan_id = Column(
        String(36),
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Feature identification
    feature_key = Column(
        String(100),
        nullable=False,
        index=True,
        comment="Machine-readable feature identifier (e.g., advanced_analytics)"
    )
    feature_name = Column(
        String(200),
        nullable=False,
        comment="Human-readable feature name"
    )

    # Feature configuration
    is_enabled = Column(
        Boolean,
        default=True,
        comment="Whether feature is enabled for this plan"
    )
    limit_value = Column(
        Integer,
        nullable=True,
        comment="Numerical limit for metered features (NULL = unlimited)"
    )
    config_json = Column(
        Text,
        nullable=True,
        comment="Additional feature configuration as JSON"
    )

    # Relationship
    plan = relationship("Plan", back_populates="features")

    # Constraints
    __table_args__ = (
        UniqueConstraint("plan_id", "feature_key", name="uq_plan_feature"),
        Index("ix_plan_features_plan_feature", "plan_id", "feature_key"),
    )

    def __repr__(self) -> str:
        return f"<PlanFeature(plan_id={self.plan_id}, feature_key={self.feature_key}, enabled={self.is_enabled})>"


# Standard feature keys used in the application
class FeatureKey:
    """Standard feature keys for entitlement checking."""
    BASIC_DASHBOARD = "basic_dashboard"
    EXPORT_CSV = "export_csv"
    ADVANCED_ANALYTICS = "advanced_analytics"
    AI_INSIGHTS = "ai_insights"
    API_ACCESS = "api_access"
    PRIORITY_SUPPORT = "priority_support"
    CUSTOM_REPORTS = "custom_reports"
    WEBHOOK_NOTIFICATIONS = "webhook_notifications"
