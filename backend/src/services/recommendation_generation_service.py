"""
AI Recommendation Generation Service.

Generates tactical recommendations from AI insights using configurable
rules and deterministic templates. All outputs are deterministic.

SECURITY:
- Tenant isolation via tenant_id in all queries
- No raw data access - only processes existing insights
- No PII access
- No external API calls

NO AUTO-EXECUTION:
- All recommendations are advisory only
- No data modifications
- No calls to ad platform APIs

Story 8.3 - AI Recommendations (No Actions)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.ai_insight import AIInsight, InsightType, InsightSeverity
from src.models.ai_recommendation import (
    AIRecommendation,
    RecommendationType,
    RecommendationPriority,
    EstimatedImpact,
    RiskLevel,
    AffectedEntityType,
)
from src.services.recommendation_rules import (
    get_applicable_recommendations,
    calculate_priority,
    calculate_risk_level,
    calculate_estimated_impact,
    calculate_recommendation_confidence,
)
from src.services.recommendation_templates import (
    render_recommendation_text,
    render_rationale,
    validate_recommendation_language,
)


logger = logging.getLogger(__name__)


@dataclass
class DetectedRecommendation:
    """Intermediate representation of a detected recommendation."""

    recommendation_type: RecommendationType
    source_insight_id: str
    source_insight_type: InsightType
    source_severity: InsightSeverity
    direction: str  # "increase", "decrease", or "default"
    priority: RecommendationPriority
    estimated_impact: EstimatedImpact
    risk_level: RiskLevel
    confidence_score: float
    affected_entity: str | None = None
    affected_entity_type: str | None = None
    currency: str | None = None
    change_magnitude: float | None = None


class RecommendationGenerationService:
    """
    Service for generating AI recommendations from insights.

    SECURITY: All operations are tenant-scoped. tenant_id from JWT only.
    NO AUTO-EXECUTION: All recommendations are advisory only.
    """

    def __init__(
        self,
        db_session: Session,
        tenant_id: str,
    ):
        if not tenant_id:
            raise ValueError("tenant_id is required")

        self.db = db_session
        self.tenant_id = tenant_id

    def generate_recommendations(
        self,
        job_id: str,
        insight_ids: list[str] | None = None,
        max_insights: int = 100,
    ) -> tuple[list[AIRecommendation], int]:
        """
        Generate recommendations from insights.

        Args:
            job_id: ID of the RecommendationJob triggering generation
            insight_ids: Optional specific insight IDs to process
            max_insights: Maximum number of insights to process (default 100)

        Returns:
            Tuple of (list of generated AIRecommendation objects, insights processed count)
        """
        # Fetch insights to process
        if insight_ids:
            insights = self._fetch_specific_insights(insight_ids)
        else:
            insights = self._fetch_unprocessed_insights(max_insights)

        if not insights:
            logger.info(
                "No insights to process for recommendations",
                extra={"tenant_id": self.tenant_id, "job_id": job_id},
            )
            return [], 0

        all_detected: list[DetectedRecommendation] = []
        insights_processed = 0

        for insight in insights:
            detected = self._generate_for_insight(insight)
            all_detected.extend(detected)
            insights_processed += 1

        # Persist recommendations
        persisted = []
        for detected in all_detected:
            recommendation = self._persist_recommendation(detected, job_id)
            if recommendation:
                persisted.append(recommendation)

        logger.info(
            "Recommendations generated",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job_id,
                "insights_processed": insights_processed,
                "detected": len(all_detected),
                "persisted": len(persisted),
            },
        )

        return persisted, insights_processed

    def _fetch_unprocessed_insights(self, limit: int) -> list[AIInsight]:
        """
        Fetch recent insights that haven't had recommendations generated yet.

        Returns insights from the last 7 days that don't have recommendations.
        """
        from sqlalchemy import text

        # Get recent insights without recommendations
        # Using a NOT EXISTS subquery for efficiency
        query = text("""
            SELECT i.id
            FROM ai_insights i
            WHERE i.tenant_id = :tenant_id
              AND i.is_dismissed = 0
              AND i.generated_at > NOW() - INTERVAL '7 days'
              AND NOT EXISTS (
                  SELECT 1 FROM ai_recommendations r
                  WHERE r.related_insight_id = i.id
                    AND r.tenant_id = :tenant_id
              )
            ORDER BY i.generated_at DESC
            LIMIT :limit
        """)

        result = self.db.execute(
            query,
            {"tenant_id": self.tenant_id, "limit": limit}
        )

        insight_ids = [row[0] for row in result.fetchall()]

        if not insight_ids:
            return []

        return (
            self.db.query(AIInsight)
            .filter(
                AIInsight.id.in_(insight_ids),
                AIInsight.tenant_id == self.tenant_id,
            )
            .all()
        )

    def _fetch_specific_insights(self, insight_ids: list[str]) -> list[AIInsight]:
        """Fetch specific insights by ID."""
        return (
            self.db.query(AIInsight)
            .filter(
                AIInsight.id.in_(insight_ids),
                AIInsight.tenant_id == self.tenant_id,
            )
            .all()
        )

    def _generate_for_insight(self, insight: AIInsight) -> list[DetectedRecommendation]:
        """
        Generate recommendations for a single insight.

        Args:
            insight: AIInsight to generate recommendations for

        Returns:
            List of DetectedRecommendation objects (max 3 per insight)
        """
        recommendations: list[DetectedRecommendation] = []

        # Determine direction from insight metrics
        direction = self._get_insight_direction(insight)

        # Get applicable recommendation types
        applicable_types = get_applicable_recommendations(
            insight.insight_type,
            direction,
        )

        if not applicable_types:
            logger.debug(
                "No applicable recommendations for insight",
                extra={
                    "tenant_id": self.tenant_id,
                    "insight_id": insight.id,
                    "insight_type": insight.insight_type.value,
                    "direction": direction,
                },
            )
            return []

        # Get change magnitude from insight metrics
        change_magnitude = self._get_change_magnitude(insight)

        # Generate a recommendation for each applicable type
        for rec_type in applicable_types:
            priority = calculate_priority(insight.severity, rec_type)
            risk_level = calculate_risk_level(
                rec_type,
                insight.severity,
                change_magnitude,
            )
            estimated_impact = calculate_estimated_impact(
                insight.severity,
                rec_type,
                change_magnitude,
            )
            confidence = calculate_recommendation_confidence(
                insight.confidence_score,
                rec_type,
                insight.severity,
            )

            # Determine affected entity
            affected_entity, affected_entity_type = self._get_affected_entity(insight)

            detected = DetectedRecommendation(
                recommendation_type=rec_type,
                source_insight_id=insight.id,
                source_insight_type=insight.insight_type,
                source_severity=insight.severity,
                direction=direction,
                priority=priority,
                estimated_impact=estimated_impact,
                risk_level=risk_level,
                confidence_score=confidence,
                affected_entity=affected_entity,
                affected_entity_type=affected_entity_type,
                currency=insight.currency,
                change_magnitude=change_magnitude,
            )

            recommendations.append(detected)

        return recommendations

    def _get_insight_direction(self, insight: AIInsight) -> str:
        """Determine direction (increase/decrease) from insight metrics."""
        metrics = insight.supporting_metrics or []

        if not metrics:
            return "default"

        # Check primary metric's delta_pct
        primary_metric = metrics[0]
        delta_pct = primary_metric.get("delta_pct", 0)

        if delta_pct > 0:
            return "increase"
        elif delta_pct < 0:
            return "decrease"
        else:
            return "default"

    def _get_change_magnitude(self, insight: AIInsight) -> float | None:
        """Get the magnitude of change from insight metrics."""
        metrics = insight.supporting_metrics or []

        if not metrics:
            return None

        primary_metric = metrics[0]
        return primary_metric.get("delta_pct")

    def _get_affected_entity(
        self,
        insight: AIInsight,
    ) -> tuple[str | None, str | None]:
        """Determine the affected entity from insight context."""
        if insight.campaign_id:
            return insight.campaign_id, AffectedEntityType.CAMPAIGN.value
        elif insight.platform:
            return insight.platform, AffectedEntityType.PLATFORM.value
        else:
            return None, AffectedEntityType.ACCOUNT.value

    def _generate_content_hash(self, detected: DetectedRecommendation) -> str:
        """Generate deterministic hash for deduplication."""
        parts = [
            self.tenant_id,
            detected.recommendation_type.value,
            detected.source_insight_id,
            detected.direction,
            detected.affected_entity or "",
        ]

        content = "|".join(parts)
        return hashlib.sha256(content.encode()).hexdigest()

    def _persist_recommendation(
        self,
        detected: DetectedRecommendation,
        job_id: str,
    ) -> AIRecommendation | None:
        """Persist recommendation to database, handling deduplication."""
        content_hash = self._generate_content_hash(detected)

        # Render recommendation text and rationale
        recommendation_text = render_recommendation_text(detected)
        rationale = render_rationale(detected)

        # Validate language rules
        is_valid, error = validate_recommendation_language(recommendation_text)
        if not is_valid:
            logger.error(
                "Recommendation text validation failed",
                extra={
                    "tenant_id": self.tenant_id,
                    "recommendation_type": detected.recommendation_type.value,
                    "error": error,
                },
            )
            # Still persist but log the error - template should be fixed
            # In production, this should trigger an alert

        # Map string entity type to enum
        affected_entity_type_enum = None
        if detected.affected_entity_type:
            try:
                affected_entity_type_enum = AffectedEntityType(detected.affected_entity_type)
            except ValueError:
                pass

        recommendation = AIRecommendation(
            tenant_id=self.tenant_id,
            related_insight_id=detected.source_insight_id,
            recommendation_type=detected.recommendation_type,
            priority=detected.priority,
            recommendation_text=recommendation_text,
            rationale=rationale,
            estimated_impact=detected.estimated_impact,
            risk_level=detected.risk_level,
            confidence_score=detected.confidence_score,
            affected_entity=detected.affected_entity,
            affected_entity_type=affected_entity_type_enum,
            currency=detected.currency,
            generated_at=datetime.now(timezone.utc),
            job_id=job_id,
            content_hash=content_hash,
            is_accepted=0,
            is_dismissed=0,
        )

        try:
            self.db.add(recommendation)
            self.db.flush()
            return recommendation
        except IntegrityError:
            # Duplicate constraint violation - recommendation already exists
            self.db.rollback()
            logger.debug(
                "Recommendation deduplicated",
                extra={
                    "tenant_id": self.tenant_id,
                    "content_hash": content_hash,
                    "insight_id": detected.source_insight_id,
                },
            )
            return None

    def generate_for_single_insight(
        self,
        insight_id: str,
        job_id: str | None = None,
    ) -> list[AIRecommendation]:
        """
        Generate recommendations for a single insight.

        Convenience method for generating recommendations for one insight.

        Args:
            insight_id: ID of the insight to process
            job_id: Optional job ID (will generate one if not provided)

        Returns:
            List of generated AIRecommendation objects
        """
        import uuid

        if not job_id:
            job_id = str(uuid.uuid4())

        recommendations, _ = self.generate_recommendations(
            job_id=job_id,
            insight_ids=[insight_id],
        )

        return recommendations
