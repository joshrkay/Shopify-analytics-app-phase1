"""
Action Proposal Validation Service.

Validates that action proposals meet scope limits and business rules.
Ensures no action exceeds the maximum allowed scope (single campaign).

KEY RULES:
- Maximum scope is single campaign (no bulk operations)
- No account-level changes
- Action type must match valid target entity type

Story 8.4 - Action Proposals (Approval Required)
"""

from dataclasses import dataclass
from typing import Any

from src.models.action_proposal import (
    ActionType,
    ActionStatus,
    TargetPlatform,
    TargetEntityType,
    MAX_SCOPE_RULES,
)
from src.models.ai_recommendation import RiskLevel


@dataclass
class ValidationResult:
    """Result of a validation check."""
    is_valid: bool
    error_message: str | None = None
    warning_message: str | None = None


class ActionProposalValidationService:
    """
    Service for validating action proposals.

    Ensures proposals meet scope limits and business rules before
    they are created or approved.
    """

    # Forbidden scope values - actions cannot target these
    FORBIDDEN_SCOPES = frozenset([
        "account",
        "all_campaigns",
        "all_ad_sets",
        "bulk",
    ])

    # Maximum allowed change percentages by action type
    MAX_CHANGE_PERCENTAGES = {
        ActionType.REDUCE_BUDGET: -50,  # Max 50% reduction
        ActionType.INCREASE_BUDGET: 100,  # Max 100% increase (double)
    }

    def validate_proposal(
        self,
        action_type: ActionType,
        target_entity_type: TargetEntityType,
        target_entity_id: str,
        proposed_change: dict[str, Any],
    ) -> ValidationResult:
        """
        Validate a complete action proposal.

        Args:
            action_type: Type of action being proposed
            target_entity_type: Type of entity being targeted
            target_entity_id: ID of the target entity
            proposed_change: The proposed change details

        Returns:
            ValidationResult indicating if proposal is valid
        """
        # Validate scope
        scope_result = self.validate_scope(action_type, target_entity_type)
        if not scope_result.is_valid:
            return scope_result

        # Validate target entity
        entity_result = self.validate_target_entity(target_entity_id)
        if not entity_result.is_valid:
            return entity_result

        # Validate change magnitude
        magnitude_result = self.validate_change_magnitude(action_type, proposed_change)
        if not magnitude_result.is_valid:
            return magnitude_result

        return ValidationResult(is_valid=True)

    def validate_scope(
        self,
        action_type: ActionType,
        target_entity_type: TargetEntityType,
    ) -> ValidationResult:
        """
        Validate that the action does not exceed maximum allowed scope.

        Args:
            action_type: Type of action being proposed
            target_entity_type: Type of entity being targeted

        Returns:
            ValidationResult indicating if scope is valid
        """
        max_scope = MAX_SCOPE_RULES.get(action_type)

        if max_scope is None:
            return ValidationResult(
                is_valid=False,
                error_message=f"Unknown action type: {action_type.value}",
            )

        # Get scope hierarchy (lower index = more specific = smaller scope)
        scope_hierarchy = [
            TargetEntityType.AD,
            TargetEntityType.AD_SET,
            TargetEntityType.CAMPAIGN,
        ]

        try:
            target_scope_level = scope_hierarchy.index(target_entity_type)
            max_scope_level = scope_hierarchy.index(max_scope)
        except ValueError:
            return ValidationResult(
                is_valid=False,
                error_message=f"Invalid entity type: {target_entity_type.value}",
            )

        # Target scope level must be <= max scope level
        # (lower level means more specific, which is always allowed)
        if target_scope_level > max_scope_level:
            return ValidationResult(
                is_valid=False,
                error_message=(
                    f"Action '{action_type.value}' cannot target "
                    f"'{target_entity_type.value}'. Maximum allowed scope is "
                    f"'{max_scope.value}'."
                ),
            )

        return ValidationResult(is_valid=True)

    def validate_target_entity(
        self,
        target_entity_id: str,
    ) -> ValidationResult:
        """
        Validate the target entity identifier.

        Args:
            target_entity_id: ID of the target entity

        Returns:
            ValidationResult indicating if entity is valid
        """
        if not target_entity_id:
            return ValidationResult(
                is_valid=False,
                error_message="Target entity ID is required",
            )

        # Check for forbidden scope indicators
        entity_lower = target_entity_id.lower()
        for forbidden in self.FORBIDDEN_SCOPES:
            if forbidden in entity_lower:
                return ValidationResult(
                    is_valid=False,
                    error_message=(
                        f"Bulk or account-level actions are not allowed. "
                        f"Actions must target individual campaigns or ad sets."
                    ),
                )

        return ValidationResult(is_valid=True)

    def validate_change_magnitude(
        self,
        action_type: ActionType,
        proposed_change: dict[str, Any],
    ) -> ValidationResult:
        """
        Validate that the proposed change is within acceptable limits.

        Args:
            action_type: Type of action being proposed
            proposed_change: The proposed change details

        Returns:
            ValidationResult indicating if magnitude is valid
        """
        if not proposed_change:
            return ValidationResult(
                is_valid=False,
                error_message="Proposed change details are required",
            )

        change_type = proposed_change.get("type")
        change_value = proposed_change.get("value")

        if change_type == "percentage" and change_value is not None:
            max_change = self.MAX_CHANGE_PERCENTAGES.get(action_type)

            if max_change is not None:
                if action_type == ActionType.REDUCE_BUDGET:
                    # For reductions, value should be negative
                    # Max reduction is -50%, so value should be >= -50
                    if change_value < max_change:
                        return ValidationResult(
                            is_valid=False,
                            error_message=(
                                f"Budget reduction exceeds maximum allowed. "
                                f"Maximum reduction is {abs(max_change)}%."
                            ),
                        )
                elif action_type == ActionType.INCREASE_BUDGET:
                    # For increases, value should be positive
                    if change_value > max_change:
                        return ValidationResult(
                            is_valid=False,
                            error_message=(
                                f"Budget increase exceeds maximum allowed. "
                                f"Maximum increase is {max_change}%."
                            ),
                        )

        return ValidationResult(is_valid=True)

    def validate_approver_can_approve(
        self,
        proposal_status: ActionStatus,
    ) -> ValidationResult:
        """
        Validate that a proposal can be approved (is in PROPOSED status).

        Args:
            proposal_status: Current status of the proposal

        Returns:
            ValidationResult indicating if approval is valid
        """
        if proposal_status != ActionStatus.PROPOSED:
            return ValidationResult(
                is_valid=False,
                error_message=(
                    f"Cannot approve proposal in status '{proposal_status.value}'. "
                    f"Only proposals in 'proposed' status can be approved."
                ),
            )

        return ValidationResult(is_valid=True)

    def validate_approver_can_reject(
        self,
        proposal_status: ActionStatus,
    ) -> ValidationResult:
        """
        Validate that a proposal can be rejected (is in PROPOSED status).

        Args:
            proposal_status: Current status of the proposal

        Returns:
            ValidationResult indicating if rejection is valid
        """
        if proposal_status != ActionStatus.PROPOSED:
            return ValidationResult(
                is_valid=False,
                error_message=(
                    f"Cannot reject proposal in status '{proposal_status.value}'. "
                    f"Only proposals in 'proposed' status can be rejected."
                ),
            )

        return ValidationResult(is_valid=True)


def calculate_risk_level_for_change(
    action_type: ActionType,
    proposed_change: dict[str, Any],
    current_value: dict[str, Any] | None = None,
) -> RiskLevel:
    """
    Calculate the risk level for a proposed change.

    Risk levels are based on the magnitude of the change and action type.

    Args:
        action_type: Type of action being proposed
        proposed_change: The proposed change details
        current_value: Current state (optional, for context)

    Returns:
        Calculated RiskLevel
    """
    change_type = proposed_change.get("type")
    change_value = proposed_change.get("value", 0)

    # Default to medium risk
    if change_type != "percentage":
        return RiskLevel.MEDIUM

    abs_change = abs(change_value)

    # Risk thresholds for percentage changes
    if action_type in (ActionType.REDUCE_BUDGET, ActionType.INCREASE_BUDGET):
        if abs_change <= 10:
            return RiskLevel.LOW
        elif abs_change <= 25:
            return RiskLevel.MEDIUM
        else:
            return RiskLevel.HIGH

    if action_type == ActionType.PAUSE_CAMPAIGN:
        # Pausing is always at least medium risk
        return RiskLevel.MEDIUM

    if action_type == ActionType.RESUME_CAMPAIGN:
        # Resuming is generally low risk
        return RiskLevel.LOW

    if action_type in (ActionType.ADJUST_TARGETING, ActionType.MODIFY_BIDDING):
        # Targeting and bidding changes are medium to high risk
        return RiskLevel.MEDIUM

    return RiskLevel.MEDIUM
