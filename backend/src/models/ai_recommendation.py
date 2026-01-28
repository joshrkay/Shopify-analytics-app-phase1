"""
AI Recommendation model for storing tactical recommendations.

Stores AI-generated tactical recommendations derived from insights.
Each recommendation represents an actionable suggestion with:
- Natural language text (conditional phrasing, no imperatives)
- Link to source insight
- Estimated impact and risk level (qualitative)
- User feedback tracking

SECURITY:
- Tenant isolation via TenantScopedMixin (tenant_id from JWT only)
- No raw data access - recommendations generated from insights only
- No PII - uses aggregated data
- Content hash for deduplication ensures determinism

NO AUTO-EXECUTION:
- All recommendations are advisory only
- No external API calls
- No data modifications

Story 8.3 - AI Recommendations (No Actions)
"""

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Enum,
    DateTime,
    Text,
    Index,
    UniqueConstraint,
    ForeignKey,
)

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


class RecommendationType(str, enum.Enum):
    """Types of recommendations the system can generate."""
    REDUCE_SPEND = "reduce_spend"
    INCREASE_SPEND = "increase_spend"
    REALLOCATE_BUDGET = "reallocate_budget"
    PAUSE_CAMPAIGN = "pause_campaign"
    SCALE_CAMPAIGN = "scale_campaign"
    OPTIMIZE_TARGETING = "optimize_targeting"
    REVIEW_CREATIVE = "review_creative"
    ADJUST_BIDDING = "adjust_bidding"


class RecommendationPriority(str, enum.Enum):
    """Priority levels for recommendations."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EstimatedImpact(str, enum.Enum):
    """
    Qualitative estimated impact of following the recommendation.

    NOTE: These are qualitative only - no specific numbers or guarantees.
    """
    MINIMAL = "minimal"
    MODERATE = "moderate"
    SIGNIFICANT = "significant"


class RiskLevel(str, enum.Enum):
    """Risk level associated with the recommendation."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AffectedEntityType(str, enum.Enum):
    """Type of entity the recommendation applies to."""
    CAMPAIGN = "campaign"
    PLATFORM = "platform"
    ACCOUNT = "account"


class AIRecommendation(Base, TimestampMixin, TenantScopedMixin):
    """
    Stores AI-generated tactical recommendations.

    Each recommendation is derived from an AI insight and provides
    actionable guidance using conditional language. Recommendations
    are advisory only - no auto-execution.

    LANGUAGE RULES:
    - ALLOWED: "Consider...", "You may want...", "may help...", "could improve..."
    - FORBIDDEN: "You should...", "You must...", "Do this..."

    SECURITY: tenant_id from TenantScopedMixin ensures isolation.
    tenant_id is ONLY extracted from JWT, never from client input.
    """

    __tablename__ = "ai_recommendations"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique recommendation identifier (UUID)"
    )

    # Link to source insight (REQUIRED)
    related_insight_id = Column(
        String(255),
        ForeignKey("ai_insights.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="ID of the insight this recommendation is based on"
    )

    # Recommendation classification
    recommendation_type = Column(
        Enum(RecommendationType),
        nullable=False,
        index=True,
        comment="Type of recommendation"
    )

    priority = Column(
        Enum(RecommendationPriority),
        nullable=False,
        default=RecommendationPriority.MEDIUM,
        index=True,
        comment="Priority level (derived from insight severity)"
    )

    # Natural language recommendation (conditional phrasing only)
    recommendation_text = Column(
        Text,
        nullable=False,
        comment="Recommendation using conditional language (consider, may help)"
    )

    # Explanation of why this recommendation is being made
    rationale = Column(
        Text,
        nullable=True,
        comment="Explanation of why this recommendation is being made"
    )

    # Qualitative impact and risk assessment
    estimated_impact = Column(
        Enum(EstimatedImpact),
        nullable=False,
        default=EstimatedImpact.MODERATE,
        comment="Qualitative impact estimate (no specific numbers)"
    )

    risk_level = Column(
        Enum(RiskLevel),
        nullable=False,
        default=RiskLevel.MEDIUM,
        index=True,
        comment="Risk level associated with this recommendation"
    )

    # Confidence score (0.0 to 1.0)
    confidence_score = Column(
        Float,
        nullable=False,
        comment="Confidence score 0.0-1.0"
    )

    # What entity this recommendation applies to
    affected_entity = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Campaign ID, platform name, or null for account-level"
    )

    affected_entity_type = Column(
        Enum(AffectedEntityType),
        nullable=True,
        comment="Type of entity: campaign, platform, or account"
    )

    # Currency for monetary context
    currency = Column(
        String(10),
        nullable=True,
        comment="Currency for monetary context"
    )

    # User feedback tracking
    is_accepted = Column(
        Integer,
        default=0,
        nullable=False,
        comment="User found this recommendation useful (0=no feedback, 1=accepted)"
    )

    is_dismissed = Column(
        Integer,
        default=0,
        nullable=False,
        comment="User dismissed this recommendation (0=active, 1=dismissed)"
    )

    # Generation metadata
    generated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="When recommendation was generated"
    )

    job_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="ID of the RecommendationJob that generated this"
    )

    # Determinism hash for deduplication
    content_hash = Column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash of input data for deduplication"
    )

    # Indexes for efficient querying
    __table_args__ = (
        # Tenant + generated_at for listing recent recommendations
        Index(
            "ix_ai_recommendations_tenant_generated",
            "tenant_id",
            "generated_at",
            postgresql_ops={"generated_at": "DESC"}
        ),
        # Tenant + type for filtering by recommendation type
        Index("ix_ai_recommendations_tenant_type", "tenant_id", "recommendation_type"),
        # Tenant + insight for getting recommendations for a specific insight
        Index("ix_ai_recommendations_tenant_insight", "tenant_id", "related_insight_id"),
        # Deduplication: prevent identical recommendations for same insight
        UniqueConstraint(
            "tenant_id",
            "content_hash",
            "related_insight_id",
            name="uq_ai_recommendations_dedup"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AIRecommendation("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"type={self.recommendation_type.value if self.recommendation_type else None}, "
            f"priority={self.priority.value if self.priority else None}"
            f")>"
        )

    @property
    def is_active(self) -> bool:
        """Check if recommendation is active (not dismissed)."""
        return self.is_dismissed == 0

    @property
    def has_feedback(self) -> bool:
        """Check if user has provided feedback (accepted or dismissed)."""
        return self.is_accepted == 1 or self.is_dismissed == 1

    def mark_accepted(self) -> None:
        """Mark recommendation as accepted by user."""
        self.is_accepted = 1

    def mark_dismissed(self) -> None:
        """Mark recommendation as dismissed by user."""
        self.is_dismissed = 1
