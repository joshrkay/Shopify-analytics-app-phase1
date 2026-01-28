"""
Unit tests for Action Proposal Validation Service.

Tests cover:
- Scope validation
- Target entity validation
- Change magnitude validation
- Approval/rejection validation

Story 8.4 - Action Proposals (Approval Required)
"""

import pytest

from src.models.action_proposal import (
    ActionType,
    ActionStatus,
    TargetEntityType,
)
from src.models.ai_recommendation import RiskLevel
from src.services.action_proposal_validation import (
    ActionProposalValidationService,
    ValidationResult,
    calculate_risk_level_for_change,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def validation_service():
    """Create a validation service instance."""
    return ActionProposalValidationService()


# =============================================================================
# Scope Validation Tests
# =============================================================================


class TestScopeValidation:
    """Tests for scope validation."""

    def test_campaign_scope_allowed_for_budget_actions(self, validation_service):
        """Campaign scope should be allowed for budget actions."""
        result = validation_service.validate_scope(
            ActionType.REDUCE_BUDGET,
            TargetEntityType.CAMPAIGN,
        )
        assert result.is_valid is True

    def test_ad_set_scope_allowed_for_budget_actions(self, validation_service):
        """Ad set scope (more specific) should be allowed for budget actions."""
        result = validation_service.validate_scope(
            ActionType.REDUCE_BUDGET,
            TargetEntityType.AD_SET,
        )
        assert result.is_valid is True

    def test_ad_scope_allowed_for_budget_actions(self, validation_service):
        """Ad scope (most specific) should be allowed for budget actions."""
        result = validation_service.validate_scope(
            ActionType.REDUCE_BUDGET,
            TargetEntityType.AD,
        )
        assert result.is_valid is True

    def test_campaign_scope_not_allowed_for_targeting_actions(self, validation_service):
        """Campaign scope should not be allowed for targeting actions (max is ad_set)."""
        result = validation_service.validate_scope(
            ActionType.ADJUST_TARGETING,
            TargetEntityType.CAMPAIGN,
        )
        assert result.is_valid is False
        assert "Maximum allowed scope" in result.error_message

    def test_ad_set_scope_allowed_for_targeting_actions(self, validation_service):
        """Ad set scope should be allowed for targeting actions."""
        result = validation_service.validate_scope(
            ActionType.ADJUST_TARGETING,
            TargetEntityType.AD_SET,
        )
        assert result.is_valid is True

    def test_ad_scope_allowed_for_targeting_actions(self, validation_service):
        """Ad scope (more specific) should be allowed for targeting actions."""
        result = validation_service.validate_scope(
            ActionType.ADJUST_TARGETING,
            TargetEntityType.AD,
        )
        assert result.is_valid is True


# =============================================================================
# Target Entity Validation Tests
# =============================================================================


class TestTargetEntityValidation:
    """Tests for target entity validation."""

    def test_valid_campaign_id(self, validation_service):
        """Valid campaign ID should pass validation."""
        result = validation_service.validate_target_entity("campaign_12345")
        assert result.is_valid is True

    def test_empty_entity_id_fails(self, validation_service):
        """Empty entity ID should fail validation."""
        result = validation_service.validate_target_entity("")
        assert result.is_valid is False
        assert "required" in result.error_message.lower()

    def test_account_scope_forbidden(self, validation_service):
        """Entity IDs containing 'account' should be forbidden."""
        result = validation_service.validate_target_entity("account_level_all")
        assert result.is_valid is False
        assert "Bulk or account-level" in result.error_message

    def test_all_campaigns_forbidden(self, validation_service):
        """Entity IDs containing 'all_campaigns' should be forbidden."""
        result = validation_service.validate_target_entity("all_campaigns")
        assert result.is_valid is False
        assert "Bulk or account-level" in result.error_message

    def test_bulk_identifier_forbidden(self, validation_service):
        """Entity IDs containing 'bulk' should be forbidden."""
        result = validation_service.validate_target_entity("bulk_operation_123")
        assert result.is_valid is False
        assert "Bulk or account-level" in result.error_message


# =============================================================================
# Change Magnitude Validation Tests
# =============================================================================


class TestChangeMagnitudeValidation:
    """Tests for change magnitude validation."""

    def test_valid_percentage_reduction(self, validation_service):
        """Valid percentage reduction should pass."""
        result = validation_service.validate_change_magnitude(
            ActionType.REDUCE_BUDGET,
            {"type": "percentage", "value": -30},
        )
        assert result.is_valid is True

    def test_excessive_percentage_reduction_fails(self, validation_service):
        """Reduction exceeding 50% should fail."""
        result = validation_service.validate_change_magnitude(
            ActionType.REDUCE_BUDGET,
            {"type": "percentage", "value": -60},
        )
        assert result.is_valid is False
        assert "Maximum reduction is 50%" in result.error_message

    def test_valid_percentage_increase(self, validation_service):
        """Valid percentage increase should pass."""
        result = validation_service.validate_change_magnitude(
            ActionType.INCREASE_BUDGET,
            {"type": "percentage", "value": 50},
        )
        assert result.is_valid is True

    def test_excessive_percentage_increase_fails(self, validation_service):
        """Increase exceeding 100% should fail."""
        result = validation_service.validate_change_magnitude(
            ActionType.INCREASE_BUDGET,
            {"type": "percentage", "value": 150},
        )
        assert result.is_valid is False
        assert "Maximum increase is 100%" in result.error_message

    def test_status_change_always_valid(self, validation_service):
        """Status changes (pause/resume) should always be valid."""
        result = validation_service.validate_change_magnitude(
            ActionType.PAUSE_CAMPAIGN,
            {"type": "status", "value": "paused"},
        )
        assert result.is_valid is True

    def test_empty_proposed_change_fails(self, validation_service):
        """Empty proposed change should fail."""
        result = validation_service.validate_change_magnitude(
            ActionType.REDUCE_BUDGET,
            {},
        )
        assert result.is_valid is False
        assert "required" in result.error_message.lower()

    def test_none_proposed_change_fails(self, validation_service):
        """None proposed change should fail."""
        result = validation_service.validate_change_magnitude(
            ActionType.REDUCE_BUDGET,
            None,
        )
        assert result.is_valid is False


# =============================================================================
# Approval Validation Tests
# =============================================================================


class TestApprovalValidation:
    """Tests for approval/rejection validation."""

    def test_can_approve_proposed_status(self, validation_service):
        """Should be able to approve PROPOSED status."""
        result = validation_service.validate_approver_can_approve(ActionStatus.PROPOSED)
        assert result.is_valid is True

    def test_cannot_approve_approved_status(self, validation_service):
        """Should not be able to approve already APPROVED status."""
        result = validation_service.validate_approver_can_approve(ActionStatus.APPROVED)
        assert result.is_valid is False
        assert "Only proposals in 'proposed' status" in result.error_message

    def test_cannot_approve_rejected_status(self, validation_service):
        """Should not be able to approve REJECTED status."""
        result = validation_service.validate_approver_can_approve(ActionStatus.REJECTED)
        assert result.is_valid is False

    def test_cannot_approve_expired_status(self, validation_service):
        """Should not be able to approve EXPIRED status."""
        result = validation_service.validate_approver_can_approve(ActionStatus.EXPIRED)
        assert result.is_valid is False

    def test_can_reject_proposed_status(self, validation_service):
        """Should be able to reject PROPOSED status."""
        result = validation_service.validate_approver_can_reject(ActionStatus.PROPOSED)
        assert result.is_valid is True

    def test_cannot_reject_approved_status(self, validation_service):
        """Should not be able to reject APPROVED status."""
        result = validation_service.validate_approver_can_reject(ActionStatus.APPROVED)
        assert result.is_valid is False


# =============================================================================
# Full Proposal Validation Tests
# =============================================================================


class TestFullProposalValidation:
    """Tests for full proposal validation."""

    def test_valid_proposal_passes_all_checks(self, validation_service):
        """A valid proposal should pass all validation checks."""
        result = validation_service.validate_proposal(
            action_type=ActionType.REDUCE_BUDGET,
            target_entity_type=TargetEntityType.CAMPAIGN,
            target_entity_id="campaign_123",
            proposed_change={"type": "percentage", "value": -15},
        )
        assert result.is_valid is True

    def test_invalid_scope_fails_validation(self, validation_service):
        """Invalid scope should fail full validation."""
        result = validation_service.validate_proposal(
            action_type=ActionType.ADJUST_TARGETING,
            target_entity_type=TargetEntityType.CAMPAIGN,  # Invalid - max is ad_set
            target_entity_id="campaign_123",
            proposed_change={"type": "targeting", "value": "adjust"},
        )
        assert result.is_valid is False

    def test_invalid_entity_fails_validation(self, validation_service):
        """Invalid entity should fail full validation."""
        result = validation_service.validate_proposal(
            action_type=ActionType.REDUCE_BUDGET,
            target_entity_type=TargetEntityType.CAMPAIGN,
            target_entity_id="all_campaigns",  # Invalid - bulk operation
            proposed_change={"type": "percentage", "value": -15},
        )
        assert result.is_valid is False

    def test_excessive_magnitude_fails_validation(self, validation_service):
        """Excessive change magnitude should fail full validation."""
        result = validation_service.validate_proposal(
            action_type=ActionType.REDUCE_BUDGET,
            target_entity_type=TargetEntityType.CAMPAIGN,
            target_entity_id="campaign_123",
            proposed_change={"type": "percentage", "value": -80},  # Invalid - max 50%
        )
        assert result.is_valid is False


# =============================================================================
# Risk Level Calculation Tests
# =============================================================================


class TestRiskLevelCalculation:
    """Tests for risk level calculation."""

    def test_small_budget_change_is_low_risk(self):
        """Small budget changes (<=10%) should be low risk."""
        risk = calculate_risk_level_for_change(
            ActionType.REDUCE_BUDGET,
            {"type": "percentage", "value": -5},
        )
        assert risk == RiskLevel.LOW

    def test_medium_budget_change_is_medium_risk(self):
        """Medium budget changes (11-25%) should be medium risk."""
        risk = calculate_risk_level_for_change(
            ActionType.REDUCE_BUDGET,
            {"type": "percentage", "value": -20},
        )
        assert risk == RiskLevel.MEDIUM

    def test_large_budget_change_is_high_risk(self):
        """Large budget changes (>25%) should be high risk."""
        risk = calculate_risk_level_for_change(
            ActionType.REDUCE_BUDGET,
            {"type": "percentage", "value": -40},
        )
        assert risk == RiskLevel.HIGH

    def test_pause_campaign_is_medium_risk(self):
        """Pause campaign should be at least medium risk."""
        risk = calculate_risk_level_for_change(
            ActionType.PAUSE_CAMPAIGN,
            {"type": "status", "value": "paused"},
        )
        assert risk == RiskLevel.MEDIUM

    def test_resume_campaign_is_low_risk(self):
        """Resume campaign should be low risk."""
        risk = calculate_risk_level_for_change(
            ActionType.RESUME_CAMPAIGN,
            {"type": "status", "value": "active"},
        )
        assert risk == RiskLevel.LOW

    def test_targeting_change_is_medium_risk(self):
        """Targeting changes should be medium risk."""
        risk = calculate_risk_level_for_change(
            ActionType.ADJUST_TARGETING,
            {"type": "targeting", "value": "adjust"},
        )
        assert risk == RiskLevel.MEDIUM


# =============================================================================
# ValidationResult Tests
# =============================================================================


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result_creation(self):
        """Should create valid ValidationResult."""
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.error_message is None
        assert result.warning_message is None

    def test_invalid_result_with_error(self):
        """Should create invalid ValidationResult with error."""
        result = ValidationResult(
            is_valid=False,
            error_message="Something went wrong",
        )
        assert result.is_valid is False
        assert result.error_message == "Something went wrong"

    def test_valid_result_with_warning(self):
        """Should create valid ValidationResult with warning."""
        result = ValidationResult(
            is_valid=True,
            warning_message="This is a warning",
        )
        assert result.is_valid is True
        assert result.warning_message == "This is a warning"
