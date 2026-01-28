"""
Action Proposal Generation Service.

Converts AI recommendations into actionable proposals that require approval.
All proposals are deterministic based on recommendation inputs.

SECURITY:
- Tenant isolation via tenant_id in all queries
- No raw data access - only processes existing recommendations
- No external API calls

NO AUTO-EXECUTION:
- All proposals require explicit approval
- No actions are taken without human sign-off

Story 8.4 - Action Proposals (Approval Required)
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.ai_recommendation import (
    AIRecommendation,
    RecommendationType,
    RiskLevel,
    AffectedEntityType,
)
from src.models.action_proposal import (
    ActionProposal,
    ActionType,
    ActionStatus,
    TargetPlatform,
    TargetEntityType,
    get_default_expiration,
)
from src.models.action_approval_audit import ActionApprovalAudit, AuditAction
from src.services.action_proposal_validation import (
    ActionProposalValidationService,
    calculate_risk_level_for_change,
)
from src.services.action_proposal_templates import (
    get_risk_disclaimer,
    render_expected_effect,
)


logger = logging.getLogger(__name__)


# Mapping from RecommendationType to ActionType
RECOMMENDATION_TO_ACTION_TYPE: dict[RecommendationType, ActionType | None] = {
    RecommendationType.REDUCE_SPEND: ActionType.REDUCE_BUDGET,
    RecommendationType.INCREASE_SPEND: ActionType.INCREASE_BUDGET,
    RecommendationType.PAUSE_CAMPAIGN: ActionType.PAUSE_CAMPAIGN,
    RecommendationType.SCALE_CAMPAIGN: ActionType.INCREASE_BUDGET,
    RecommendationType.ADJUST_BIDDING: ActionType.MODIFY_BIDDING,
    RecommendationType.OPTIMIZE_TARGETING: ActionType.ADJUST_TARGETING,
    # These don't have direct action mappings
    RecommendationType.REALLOCATE_BUDGET: None,
    RecommendationType.REVIEW_CREATIVE: None,
}


# Default change percentages by action type
DEFAULT_CHANGE_PERCENTAGES: dict[ActionType, float] = {
    ActionType.REDUCE_BUDGET: -15,  # 15% reduction
    ActionType.INCREASE_BUDGET: 15,  # 15% increase
}


@dataclass
class DetectedProposal:
    """Intermediate representation of a detected action proposal."""
    action_type: ActionType
    source_recommendation_id: str
    source_recommendation_type: RecommendationType
    target_platform: TargetPlatform
    target_entity_type: TargetEntityType
    target_entity_id: str
    target_entity_name: str | None
    proposed_change: dict[str, Any]
    current_value: dict[str, Any] | None
    risk_level: RiskLevel
    confidence_score: float
    currency: str | None


class ActionProposalGenerationService:
    """
    Service for generating action proposals from recommendations.

    SECURITY: All operations are tenant-scoped. tenant_id from JWT only.
    NO AUTO-EXECUTION: All proposals require approval before any action.
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
        self.validator = ActionProposalValidationService()

    def generate_proposals(
        self,
        job_id: str,
        recommendation_ids: list[str] | None = None,
        max_recommendations: int = 50,
    ) -> tuple[list[ActionProposal], int]:
        """
        Generate action proposals from recommendations.

        Args:
            job_id: ID of the ActionProposalJob triggering generation
            recommendation_ids: Optional specific recommendation IDs to process
            max_recommendations: Maximum number of recommendations to process

        Returns:
            Tuple of (list of generated ActionProposal objects, recommendations processed count)
        """
        # Fetch recommendations to process
        if recommendation_ids:
            recommendations = self._fetch_specific_recommendations(recommendation_ids)
        else:
            recommendations = self._fetch_unprocessed_recommendations(max_recommendations)

        if not recommendations:
            logger.info(
                "No recommendations to process for proposals",
                extra={"tenant_id": self.tenant_id, "job_id": job_id},
            )
            return [], 0

        all_detected: list[DetectedProposal] = []
        recommendations_processed = 0

        for recommendation in recommendations:
            detected = self._generate_for_recommendation(recommendation)
            if detected:
                all_detected.append(detected)
            recommendations_processed += 1

        # Persist proposals
        persisted = []
        for detected in all_detected:
            proposal = self._persist_proposal(detected, job_id)
            if proposal:
                persisted.append(proposal)

        logger.info(
            "Action proposals generated",
            extra={
                "tenant_id": self.tenant_id,
                "job_id": job_id,
                "recommendations_processed": recommendations_processed,
                "detected": len(all_detected),
                "persisted": len(persisted),
            },
        )

        return persisted, recommendations_processed

    def _fetch_unprocessed_recommendations(
        self,
        limit: int,
    ) -> list[AIRecommendation]:
        """
        Fetch recent recommendations that haven't had proposals generated yet.

        Returns accepted recommendations from the last 30 days without proposals.
        """
        from sqlalchemy import text

        query = text("""
            SELECT r.id
            FROM ai_recommendations r
            WHERE r.tenant_id = :tenant_id
              AND r.is_accepted = 1
              AND r.is_dismissed = 0
              AND r.generated_at > NOW() - INTERVAL '30 days'
              AND NOT EXISTS (
                  SELECT 1 FROM action_proposals p
                  WHERE p.source_recommendation_id = r.id
                    AND p.tenant_id = :tenant_id
              )
            ORDER BY r.generated_at DESC
            LIMIT :limit
        """)

        result = self.db.execute(
            query,
            {"tenant_id": self.tenant_id, "limit": limit}
        )

        recommendation_ids = [row[0] for row in result.fetchall()]

        if not recommendation_ids:
            return []

        return (
            self.db.query(AIRecommendation)
            .filter(
                AIRecommendation.id.in_(recommendation_ids),
                AIRecommendation.tenant_id == self.tenant_id,
            )
            .all()
        )

    def _fetch_specific_recommendations(
        self,
        recommendation_ids: list[str],
    ) -> list[AIRecommendation]:
        """Fetch specific recommendations by ID."""
        return (
            self.db.query(AIRecommendation)
            .filter(
                AIRecommendation.id.in_(recommendation_ids),
                AIRecommendation.tenant_id == self.tenant_id,
            )
            .all()
        )

    def _generate_for_recommendation(
        self,
        recommendation: AIRecommendation,
    ) -> DetectedProposal | None:
        """
        Generate a proposal for a single recommendation.

        Args:
            recommendation: AIRecommendation to generate proposal for

        Returns:
            DetectedProposal or None if recommendation cannot be converted
        """
        # Map recommendation type to action type
        action_type = RECOMMENDATION_TO_ACTION_TYPE.get(recommendation.recommendation_type)

        if action_type is None:
            logger.debug(
                "Recommendation type cannot be converted to action",
                extra={
                    "tenant_id": self.tenant_id,
                    "recommendation_id": recommendation.id,
                    "recommendation_type": recommendation.recommendation_type.value,
                },
            )
            return None

        # Determine target platform (default to Meta if not specified)
        target_platform = self._determine_platform(recommendation)

        # Determine target entity
        target_entity_type, target_entity_id = self._determine_target_entity(
            recommendation,
            action_type,
        )

        if not target_entity_id:
            logger.debug(
                "Cannot determine target entity for recommendation",
                extra={
                    "tenant_id": self.tenant_id,
                    "recommendation_id": recommendation.id,
                },
            )
            return None

        # Build proposed change
        proposed_change = self._build_proposed_change(action_type, recommendation)

        # Validate the proposal
        validation_result = self.validator.validate_proposal(
            action_type=action_type,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            proposed_change=proposed_change,
        )

        if not validation_result.is_valid:
            logger.debug(
                "Proposal validation failed",
                extra={
                    "tenant_id": self.tenant_id,
                    "recommendation_id": recommendation.id,
                    "error": validation_result.error_message,
                },
            )
            return None

        # Calculate risk level for the proposed change
        risk_level = calculate_risk_level_for_change(
            action_type=action_type,
            proposed_change=proposed_change,
        )

        return DetectedProposal(
            action_type=action_type,
            source_recommendation_id=recommendation.id,
            source_recommendation_type=recommendation.recommendation_type,
            target_platform=target_platform,
            target_entity_type=target_entity_type,
            target_entity_id=target_entity_id,
            target_entity_name=recommendation.affected_entity,
            proposed_change=proposed_change,
            current_value=None,  # Would be fetched from platform API
            risk_level=risk_level,
            confidence_score=recommendation.confidence_score,
            currency=recommendation.currency,
        )

    def _determine_platform(
        self,
        recommendation: AIRecommendation,
    ) -> TargetPlatform:
        """Determine the target platform from recommendation context."""
        affected_entity = recommendation.affected_entity or ""
        affected_entity_lower = affected_entity.lower()

        if "meta" in affected_entity_lower or "facebook" in affected_entity_lower:
            return TargetPlatform.META
        elif "google" in affected_entity_lower:
            return TargetPlatform.GOOGLE
        elif "tiktok" in affected_entity_lower:
            return TargetPlatform.TIKTOK

        # Default to Meta
        return TargetPlatform.META

    def _determine_target_entity(
        self,
        recommendation: AIRecommendation,
        action_type: ActionType,
    ) -> tuple[TargetEntityType, str | None]:
        """Determine the target entity type and ID from recommendation."""
        affected_type = recommendation.affected_entity_type

        if affected_type == AffectedEntityType.CAMPAIGN:
            return TargetEntityType.CAMPAIGN, recommendation.affected_entity

        if affected_type == AffectedEntityType.PLATFORM:
            # Platform-level recommendations can't be converted to actions
            # without more specific targeting
            return TargetEntityType.CAMPAIGN, None

        if affected_type == AffectedEntityType.ACCOUNT:
            # Account-level recommendations can't be converted to actions
            return TargetEntityType.CAMPAIGN, None

        # Default to campaign if we have an affected entity
        if recommendation.affected_entity:
            return TargetEntityType.CAMPAIGN, recommendation.affected_entity

        return TargetEntityType.CAMPAIGN, None

    def _build_proposed_change(
        self,
        action_type: ActionType,
        recommendation: AIRecommendation,
    ) -> dict[str, Any]:
        """Build the proposed change object for an action type."""
        if action_type in (ActionType.REDUCE_BUDGET, ActionType.INCREASE_BUDGET):
            default_pct = DEFAULT_CHANGE_PERCENTAGES.get(action_type, 10)
            return {
                "type": "percentage",
                "value": default_pct,
                "description": f"{default_pct:+.0f}% budget change",
            }

        if action_type == ActionType.PAUSE_CAMPAIGN:
            return {
                "type": "status",
                "value": "paused",
                "description": "Pause campaign",
            }

        if action_type == ActionType.RESUME_CAMPAIGN:
            return {
                "type": "status",
                "value": "active",
                "description": "Resume campaign",
            }

        if action_type == ActionType.ADJUST_TARGETING:
            return {
                "type": "targeting",
                "value": "review_recommended",
                "description": "Review and adjust targeting settings",
            }

        if action_type == ActionType.MODIFY_BIDDING:
            return {
                "type": "bidding",
                "value": "optimize_recommended",
                "description": "Review and optimize bidding strategy",
            }

        return {
            "type": "custom",
            "value": "review",
            "description": "Review and take action",
        }

    def _generate_content_hash(self, detected: DetectedProposal) -> str:
        """Generate deterministic hash for deduplication."""
        parts = [
            self.tenant_id,
            detected.action_type.value,
            detected.source_recommendation_id,
            detected.target_platform.value,
            detected.target_entity_id or "",
            str(detected.proposed_change.get("type", "")),
            str(detected.proposed_change.get("value", "")),
        ]

        content = "|".join(parts)
        return hashlib.sha256(content.encode()).hexdigest()

    def _persist_proposal(
        self,
        detected: DetectedProposal,
        job_id: str,
    ) -> ActionProposal | None:
        """Persist proposal to database, handling deduplication."""
        content_hash = self._generate_content_hash(detected)

        # Generate risk disclaimer
        risk_disclaimer = get_risk_disclaimer(
            detected.action_type,
            detected.risk_level,
        )

        # Generate expected effect
        expected_effect = render_expected_effect(
            action_type=detected.action_type,
            entity_name=detected.target_entity_name or detected.target_entity_id,
            current_value=detected.current_value,
            proposed_change=detected.proposed_change,
            currency=detected.currency or "USD",
        )

        proposal = ActionProposal(
            tenant_id=self.tenant_id,
            source_recommendation_id=detected.source_recommendation_id,
            action_type=detected.action_type,
            status=ActionStatus.PROPOSED,
            target_platform=detected.target_platform,
            target_entity_type=detected.target_entity_type,
            target_entity_id=detected.target_entity_id,
            target_entity_name=detected.target_entity_name,
            proposed_change=detected.proposed_change,
            current_value=detected.current_value,
            expected_effect=expected_effect,
            risk_disclaimer=risk_disclaimer,
            risk_level=detected.risk_level,
            confidence_score=detected.confidence_score,
            expires_at=get_default_expiration(),
            content_hash=content_hash,
            generated_at=datetime.now(timezone.utc),
            job_id=job_id,
            proposal_metadata={},
        )

        try:
            self.db.add(proposal)
            self.db.flush()

            # Create audit entry for proposal creation
            audit_entry = ActionApprovalAudit.create_entry(
                tenant_id=self.tenant_id,
                action_proposal_id=proposal.id,
                action=AuditAction.CREATED,
                new_status=ActionStatus.PROPOSED,
                previous_status=None,
            )
            self.db.add(audit_entry)
            self.db.flush()

            return proposal
        except IntegrityError:
            self.db.rollback()
            logger.debug(
                "Proposal deduplicated",
                extra={
                    "tenant_id": self.tenant_id,
                    "content_hash": content_hash,
                    "recommendation_id": detected.source_recommendation_id,
                },
            )
            return None

    def generate_for_single_recommendation(
        self,
        recommendation_id: str,
        job_id: str | None = None,
    ) -> ActionProposal | None:
        """
        Generate a proposal for a single recommendation.

        Args:
            recommendation_id: ID of the recommendation to process
            job_id: Optional job ID (will generate one if not provided)

        Returns:
            Generated ActionProposal or None
        """
        import uuid

        if not job_id:
            job_id = str(uuid.uuid4())

        proposals, _ = self.generate_proposals(
            job_id=job_id,
            recommendation_ids=[recommendation_id],
        )

        return proposals[0] if proposals else None
