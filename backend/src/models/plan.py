"""
Plan and PlanFeature models - Global plan definitions.

Plans are global (not tenant-scoped) and define available subscription tiers.
PlanFeatures link plans to enabled features with optional limits.
"""

from sqlalchemy import Column, String, Integer, Boolean, Text, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import relationship

from src.repositories.base_repo import Base
from src.models.base import TimestampMixin


class Plan(Base, TimestampMixin):
    """
    Global plan definition (Free, Growth, Pro, Enterprise).
    
    Plans are NOT tenant-scoped - they define what's available.
    Each tenant subscribes to a plan via Subscription model.
    """
    
    __tablename__ = "plans"
    
    id = Column(
        String(255),
        primary_key=True,
        comment="Plan identifier (e.g., 'plan_free', 'plan_growth')"
    )
    
    name = Column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique plan name (e.g., 'free', 'growth')"
    )
    
    display_name = Column(
        String(255),
        nullable=False,
        comment="Human-readable plan name (e.g., 'Free', 'Growth')"
    )
    
    description = Column(
        Text,
        nullable=True,
        comment="Plan description"
    )
    
    shopify_plan_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Shopify Billing API plan ID (NULL until configured)"
    )
    
    price_monthly_cents = Column(
        Integer,
        nullable=True,
        comment="Monthly price in cents (NULL for free/enterprise)"
    )
    
    price_yearly_cents = Column(
        Integer,
        nullable=True,
        comment="Yearly price in cents (NULL for free/enterprise)"
    )
    
    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        comment="Whether plan is available for new subscriptions"
    )
    
    # Relationships
    features = relationship(
        "PlanFeature",
        back_populates="plan",
        cascade="all, delete-orphan"
    )
    
    def __repr__(self) -> str:
        return f"<Plan(id={self.id}, name={self.name}, price_monthly_cents={self.price_monthly_cents})>"


class PlanFeature(Base, TimestampMixin):
    """
    Junction table linking plans to enabled features with optional limits.
    
    Features are defined as constants in code (e.g., 'ai_insights', 'custom_reports').
    This table enables/disables features per plan and sets limits.
    """
    
    __tablename__ = "plan_features"
    
    id = Column(
        String(255),
        primary_key=True,
        comment="Primary key (UUID recommended)"
    )
    
    plan_id = Column(
        String(255),
        ForeignKey("plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Foreign key to plans.id"
    )
    
    feature_key = Column(
        String(255),
        nullable=False,
        index=True,
        comment="Feature identifier (e.g., 'ai_insights', 'custom_reports')"
    )
    
    is_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        comment="Whether feature is enabled for this plan"
    )
    
    limit_value = Column(
        Integer,
        nullable=True,
        comment="Usage limit value (NULL means unlimited or not applicable)"
    )
    
    limits = Column(
        JSON,
        nullable=True,
        comment="Optional limits object (e.g., {'ai_insights_per_month': 100})"
    )
    
    # Relationships
    plan = relationship("Plan", back_populates="features")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("plan_id", "feature_key", name="uk_plan_features_plan_feature"),
    )
    
    def __repr__(self) -> str:
        return f"<PlanFeature(plan_id={self.plan_id}, feature_key={self.feature_key}, is_enabled={self.is_enabled})>"
