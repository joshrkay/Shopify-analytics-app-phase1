"""
AI Insight model for storing generated analytics insights.

Stores AI-generated business insights from aggregated dbt mart data.
Each insight represents a detected pattern or anomaly with:
- Natural language summary (template-based, deterministic)
- Supporting metrics with period-over-period changes
- Confidence score and severity level

SECURITY:
- Tenant isolation via TenantScopedMixin (tenant_id from JWT only)
- No raw data access - insights generated from aggregated marts only
- No PII - uses pseudonymized customer_key from marts
- Content hash for deduplication ensures determinism

Story 8.1 - AI Insight Generation (Read-Only Analytics)
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
    JSON,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.db_base import Base
from src.models.base import TimestampMixin, TenantScopedMixin


# Use JSONB for PostgreSQL, JSON for other databases (testing)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class InsightType(str, enum.Enum):
    """Types of insights the system can generate."""
    SPEND_ANOMALY = "spend_anomaly"
    ROAS_CHANGE = "roas_change"
    REVENUE_VS_SPEND_DIVERGENCE = "revenue_vs_spend_divergence"
    CHANNEL_MIX_SHIFT = "channel_mix_shift"
    CAC_ANOMALY = "cac_anomaly"
    AOV_CHANGE = "aov_change"


class InsightSeverity(str, enum.Enum):
    """Severity level of insights for prioritization."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AIInsight(Base, TimestampMixin, TenantScopedMixin):
    """
    Stores AI-generated business insights.

    Each insight represents a detected pattern or anomaly from
    aggregated marketing/revenue metrics. Generated on schedule,
    never in real-time.

    SECURITY: tenant_id from TenantScopedMixin ensures isolation.
    tenant_id is ONLY extracted from JWT, never from client input.
    """

    __tablename__ = "ai_insights"

    id = Column(
        String(255),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Unique insight identifier (UUID)"
    )

    # Insight classification
    insight_type = Column(
        Enum(InsightType),
        nullable=False,
        index=True,
        comment="Type of insight detected"
    )

    severity = Column(
        Enum(InsightSeverity),
        nullable=False,
        default=InsightSeverity.INFO,
        index=True,
        comment="Severity level for prioritization"
    )

    # Natural language summary (template-based for determinism)
    summary = Column(
        Text,
        nullable=False,
        comment="1-2 sentence natural language summary"
    )

    # Explainability: why this insight matters (Story 8.2)
    why_it_matters = Column(
        Text,
        nullable=True,
        comment="Business-friendly explanation of insight importance"
    )

    # Supporting metrics (structured data)
    supporting_metrics = Column(
        JSONType,
        nullable=False,
        default=list,
        comment="Array of {metric, current_value, prior_value, delta, delta_pct, timeframe}"
    )

    # Confidence score (0.0 to 1.0)
    confidence_score = Column(
        Float,
        nullable=False,
        comment="Confidence score 0.0-1.0"
    )

    # Period context
    period_type = Column(
        String(50),
        nullable=False,
        comment="Period analyzed: weekly, monthly, last_7_days, etc."
    )

    period_start = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="Start of analyzed period"
    )

    period_end = Column(
        DateTime(timezone=True),
        nullable=False,
        comment="End of analyzed period"
    )

    comparison_type = Column(
        String(50),
        nullable=False,
        comment="Comparison type: week_over_week, month_over_month, etc."
    )

    # Optional filters (platform/campaign specific insights)
    platform = Column(
        String(50),
        nullable=True,
        index=True,
        comment="Platform if insight is platform-specific (meta_ads, google_ads)"
    )

    campaign_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="Campaign ID if insight is campaign-specific"
    )

    currency = Column(
        String(10),
        nullable=True,
        comment="Currency for monetary metrics"
    )

    # Generation metadata
    generated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        comment="When insight was generated"
    )

    job_id = Column(
        String(255),
        nullable=True,
        index=True,
        comment="ID of the InsightJob that generated this insight"
    )

    # Determinism hash for deduplication
    content_hash = Column(
        String(64),
        nullable=False,
        index=True,
        comment="SHA256 hash of input data for deduplication"
    )

    # Read/dismiss status (for UI)
    is_read = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Whether user has viewed this insight (0=unread, 1=read)"
    )

    is_dismissed = Column(
        Integer,
        default=0,
        nullable=False,
        comment="Whether user dismissed this insight (0=active, 1=dismissed)"
    )

    # Indexes for efficient querying
    __table_args__ = (
        # Tenant + generated_at for listing recent insights
        Index(
            "ix_ai_insights_tenant_generated",
            "tenant_id",
            "generated_at",
            postgresql_ops={"generated_at": "DESC"}
        ),
        # Tenant + type for filtering by insight type
        Index("ix_ai_insights_tenant_type", "tenant_id", "insight_type"),
        # Deduplication: prevent identical insights for same period
        UniqueConstraint(
            "tenant_id",
            "content_hash",
            "period_end",
            name="uq_ai_insights_dedup"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<AIInsight("
            f"id={self.id}, "
            f"tenant_id={self.tenant_id}, "
            f"type={self.insight_type.value if self.insight_type else None}, "
            f"severity={self.severity.value if self.severity else None}"
            f")>"
        )

    @property
    def is_unread(self) -> bool:
        """Check if insight has not been read."""
        return self.is_read == 0

    @property
    def is_active(self) -> bool:
        """Check if insight is active (not dismissed)."""
        return self.is_dismissed == 0

    def mark_read(self) -> None:
        """Mark insight as read."""
        self.is_read = 1

    def mark_dismissed(self) -> None:
        """Mark insight as dismissed."""
        self.is_dismissed = 1
