"""
Unit tests for Governance modules (Story 5.8).

Tests cover:
- 5.8.1: Approval-gated deployment system
- 5.8.2: Metric version enforcement
- 5.8.3: Rollback orchestrator
- 5.8.4: Pre-deploy validation framework
- 5.8.5: AI guardrails system
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

# Import governance modules
from src.governance.approval_gate import (
    ApprovalGate,
    ApprovalResult,
    ApprovalStatus,
)
from src.governance.metric_versioning import (
    DeprecationWarning,
    MetricResolution,
    MetricStatus,
    MetricVersionResolver,
    WarningLevel,
)
from src.governance.rollback_orchestrator import (
    RollbackOrchestrator,
    RollbackRequest,
    RollbackResult,
    RollbackScope,
    RollbackState,
)
from src.governance.pre_deploy_validator import (
    CheckResult,
    PreDeployValidator,
    ValidationResult,
    ValidationStatus,
)
from src.governance.ai_guardrails import (
    AIGuardrails,
    GuardrailCheck,
    GuardrailRefusal,
    GuardrailViolation,
    RefusalReason,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory with test config files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def approval_config(temp_config_dir):
    """Create test approval configuration."""
    config = {
        "enforcement": {
            "blocking_mode": True,
            "audit_log_required": True,
            "failure_behavior": "BLOCK_DEPLOYMENT",
        },
        "change_approvals": {
            "metric_definition_change": {
                "approval_required": True,
                "approvers": {"primary": "Product Manager"},
                "sla_hours": 48,
                "pre_approval_checklist": [
                    "metric definition document",
                    "comparison: old vs new calculation",
                ],
            },
            "dashboard_default_change": {
                "approval_required": False,
                "change_type": "cosmetic",
            },
            "rls_rule_change": {
                "approval_required": True,
                "approvers": {"primary": "Security Engineer"},
                "sla_hours": 4,
                "pre_approval_checklist": ["RLS test cases pass"],
                "emergency_approval": {
                    "allows": ["CTO", "Security Engineer"],
                    "min_approvers": 2,
                    "requires": ["incident ticket", "post-mortem"],
                },
            },
        },
        "rollback_approval": {
            "bypass_normal_approval": True,
            "trigger_authority": ["Analytics Oncall", "Security Oncall"],
        },
    }

    config_path = temp_config_dir / "change_approvals.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


@pytest.fixture
def change_requests_config(temp_config_dir):
    """Create test change requests."""
    # SLA deadline in the future
    future_deadline = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    # SLA deadline in the past
    past_deadline = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

    config = {
        "change_requests": [
            {
                "id": "CR-001",
                "type": "metric_definition_change",
                "status": "pending_approval",
                "checklist_completed": [
                    "metric definition document",
                    "comparison: old vs new calculation",
                ],
                "checklist_pending": [],
                "approvals": [
                    {"role": "Product Manager", "approved_at": "2026-01-20T10:00:00Z"}
                ],
                "sla_deadline": future_deadline,
            },
            {
                "id": "CR-002",
                "type": "metric_definition_change",
                "status": "pending_approval",
                "checklist_completed": [],
                "checklist_pending": ["metric definition document"],
                "approvals": [],
                "sla_deadline": future_deadline,
            },
            {
                "id": "CR-003",
                "type": "metric_definition_change",
                "status": "pending_approval",
                "checklist_completed": [
                    "metric definition document",
                    "comparison: old vs new calculation",
                ],
                "approvals": [],
                "sla_deadline": past_deadline,
            },
            {
                "id": "CR-004",
                "type": "dashboard_default_change",
                "status": "pending",
            },
            {
                "id": "CR-005",
                "type": "rls_rule_change",
                "status": "pending_approval",
                "emergency": True,
                "checklist_completed": ["RLS test cases pass"],
                "approvals": [
                    {"role": "CTO", "approved_at": "2026-01-25T09:00:00Z"},
                    {"role": "Security Engineer", "approved_at": "2026-01-25T09:05:00Z"},
                ],
                "incident_ticket": "INC-001",
                "post_mortem_required": True,
                "sla_deadline": future_deadline,
            },
        ]
    }

    config_path = temp_config_dir / "change_requests.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


@pytest.fixture
def metrics_config(temp_config_dir):
    """Create test metrics configuration."""
    # Sunset date in the past
    past_sunset = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")
    # Sunset date in the future
    future_sunset = (datetime.now(timezone.utc) + timedelta(days=30)).strftime(
        "%Y-%m-%d"
    )

    config = {
        "deprecation_enforcement": {
            "warn_on_query": True,
            "warn_days_before_sunset": 30,
            "block_on_sunset": True,
            "merchant_visibility": ["dashboard_banner", "email_notification"],
        },
        "metrics": {
            "revenue": {
                "current_version": "v2",
                "v2": {
                    "dbt_model": "fact_orders",
                    "definition": "SUM(revenue)",
                    "status": "active",
                },
                "v1": {
                    "dbt_model": "fact_orders_legacy",
                    "definition": "SUM(revenue) WHERE refund_status != 'returned'",
                    "status": "deprecated",
                    "sunset_date": future_sunset,
                    "migration_guide": "docs/migrate_revenue_v1_to_v2.md",
                },
            },
            "old_metric": {
                "current_version": "v2",
                "v2": {
                    "dbt_model": "new_model",
                    "definition": "NEW",
                    "status": "active",
                },
                "v1": {
                    "dbt_model": "old_model",
                    "definition": "OLD",
                    "status": "sunset",
                    "sunset_date": past_sunset,
                },
            },
        },
        "migration": {
            "auto_migrate": False,
            "require_explicit_approval": True,
        },
    }

    config_path = temp_config_dir / "metrics_versions.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


@pytest.fixture
def rollback_config(temp_config_dir):
    """Create test rollback configuration."""
    config = {
        "rollback_control": {
            "trigger_authority": ["Analytics Oncall", "Security Oncall"],
            "verification_required": ["error rate normalized", "latency stabilized"],
            "post_rollback_review": "required",
        },
        "rollback_strategy": {
            "rollback_actions": [
                {"action": "clear_redis_cache", "target": "all", "order": 1},
                {"action": "notify_slack", "target": "#alerts", "order": 2},
            ],
            "gradual_rollback": {
                "enabled": True,
                "canary_percentage": 10,
                "rollout_interval_minutes": 5,
                "success_criteria": ["no new error alerts"],
            },
            "verification": {
                "checks": [
                    {
                        "name": "error_rate_check",
                        "threshold": 0.01,
                        "comparison": "less_than",
                    }
                ],
                "timeout_seconds": 300,
            },
        },
    }

    config_path = temp_config_dir / "rollback_config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


@pytest.fixture
def validation_config(temp_config_dir):
    """Create test validation configuration."""
    config = {
        "validation_output": {
            "format": "json",
            "required_fields": ["check_name", "status", "measured_value", "threshold"],
        },
        "pre_deploy_validation": {
            "dbt_models": {
                "checks": [
                    {"name": "models_compile", "description": "All models compile"},
                    {
                        "name": "tests_pass",
                        "description": "Tests pass",
                        "threshold": 0.95,
                    },
                ],
                "failure_behavior": "BLOCK_DEPLOYMENT",
            },
            "rls_verification": {
                "checks": [
                    {
                        "name": "cross_tenant_isolation",
                        "description": "Cross-tenant isolation",
                        "blocking": True,
                    }
                ],
                "failure_behavior": "BLOCK_DEPLOYMENT",
            },
        },
        "sign_off": {
            "required_approvers": {
                "default": ["Analytics Tech Lead"],
                "rls_change": ["Analytics Tech Lead", "Security Engineer"],
            },
        },
    }

    config_path = temp_config_dir / "pre_deploy_validation.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


@pytest.fixture
def ai_restrictions_config(temp_config_dir):
    """Create test AI restrictions configuration."""
    config = {
        "ai_restrictions": {
            "prohibited_actions": [
                {
                    "id": "approve_metric_changes",
                    "description": "Approve metric definition changes",
                    "reason": "Requires human accountability",
                    "redirect_to": "Product Manager",
                },
                {
                    "id": "classify_breaking_changes",
                    "description": "Classify breaking vs non-breaking",
                    "reason": "Requires business domain knowledge",
                    "redirect_to": "Analytics Tech Lead",
                },
                {
                    "id": "trigger_rollback",
                    "description": "Autonomously trigger rollbacks",
                    "reason": "Requires incident assessment",
                    "redirect_to": "Analytics Oncall",
                },
            ],
            "required_behaviors": [
                {
                    "id": "log_all_decisions",
                    "description": "Log all decision points",
                    "enforcement": "mandatory",
                },
                {
                    "id": "require_human_approval",
                    "description": "Require human approval for production",
                    "enforcement": "mandatory",
                },
            ],
        }
    }

    config_path = temp_config_dir / "ai_restrictions.yaml"
    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


# ============================================================================
# 5.8.1 - Approval Gate Tests
# ============================================================================


class TestApprovalGate:
    """Tests for the approval-gated deployment system."""

    def test_approved_change_passes(self, approval_config, change_requests_config):
        """Test that a fully approved change request passes validation."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_change_request("CR-001")

        assert result.status == ApprovalStatus.PASS
        assert "All required approvals present" in result.reason
        assert len(result.missing_approvals) == 0

    def test_missing_approval_blocks(self, approval_config, change_requests_config):
        """Test that missing approval blocks deployment."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_change_request("CR-002")

        assert result.status == ApprovalStatus.BLOCK
        assert "checklist incomplete" in result.reason.lower()

    def test_expired_sla_blocks(self, approval_config, change_requests_config):
        """Test that expired SLA blocks deployment."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_change_request("CR-003")

        assert result.status == ApprovalStatus.BLOCK
        assert result.expired is True
        assert "expired" in result.reason.lower()

    def test_cosmetic_change_no_approval_needed(
        self, approval_config, change_requests_config
    ):
        """Test that cosmetic changes don't require approval."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_change_request("CR-004")

        assert result.status == ApprovalStatus.PASS
        assert "not required" in result.reason.lower()

    def test_emergency_approval_passes(self, approval_config, change_requests_config):
        """Test that emergency approval with all requirements passes."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_change_request("CR-005")

        assert result.status == ApprovalStatus.PASS

    def test_rollback_authorized_passes(self, approval_config, change_requests_config):
        """Test that authorized rollback passes."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_rollback(
            {
                "rollback_id": "RB-001",
                "triggered_by": "oncall@company.com",
                "trigger_role": "Analytics Oncall",
                "reason": "Metric mismatch detected",
            }
        )

        assert result.status == ApprovalStatus.PASS

    def test_rollback_unauthorized_blocks(
        self, approval_config, change_requests_config
    ):
        """Test that unauthorized rollback is blocked."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_rollback(
            {
                "rollback_id": "RB-002",
                "triggered_by": "junior@company.com",
                "trigger_role": "Junior Developer",
                "reason": "Something looks wrong",
            }
        )

        assert result.status == ApprovalStatus.BLOCK
        assert "not authorized" in result.reason.lower()

    def test_audit_log_created(self, approval_config, change_requests_config):
        """Test that audit log entries are created."""
        gate = ApprovalGate(approval_config, change_requests_config)
        gate.validate_change_request("CR-001")

        audit_log = gate.get_audit_log()
        assert len(audit_log) > 0
        assert audit_log[-1]["change_request_id"] == "CR-001"

    def test_unknown_change_request_blocks(
        self, approval_config, change_requests_config
    ):
        """Test that unknown change request is blocked."""
        gate = ApprovalGate(approval_config, change_requests_config)
        result = gate.validate_change_request("CR-UNKNOWN")

        assert result.status == ApprovalStatus.BLOCK
        assert "not found" in result.reason.lower()


# ============================================================================
# 5.8.2 - Metric Versioning Tests
# ============================================================================


class TestMetricVersionResolver:
    """Tests for the metric version enforcement system."""

    def test_resolve_active_metric(self, metrics_config):
        """Test resolving an active metric version."""
        resolver = MetricVersionResolver(metrics_config)
        resolution = resolver.resolve_metric("revenue", "v2")

        assert resolution.resolved_version == "v2"
        assert resolution.status == MetricStatus.ACTIVE
        assert resolution.dbt_model == "fact_orders"
        assert len(resolution.warnings) == 0

    def test_resolve_deprecated_metric_warns(self, metrics_config):
        """Test that deprecated metric emits warning."""
        resolver = MetricVersionResolver(metrics_config)
        resolution = resolver.resolve_metric("revenue", "v1")

        assert resolution.resolved_version == "v1"
        assert resolution.status == MetricStatus.DEPRECATED
        assert len(resolution.warnings) == 1
        assert resolution.warnings[0].level in (WarningLevel.WARN, WarningLevel.INFO)

    def test_resolve_sunset_metric_blocks(self, metrics_config):
        """Test that sunset metric raises error."""
        resolver = MetricVersionResolver(metrics_config)

        with pytest.raises(ValueError) as exc_info:
            resolver.resolve_metric("old_metric", "v1")

        assert "sunset" in str(exc_info.value).lower()

    def test_resolve_current_version_default(self, metrics_config):
        """Test that None version resolves to current."""
        resolver = MetricVersionResolver(metrics_config)
        resolution = resolver.resolve_metric("revenue")

        assert resolution.resolved_version == "v2"

    def test_unknown_metric_raises(self, metrics_config):
        """Test that unknown metric raises error."""
        resolver = MetricVersionResolver(metrics_config)

        with pytest.raises(ValueError) as exc_info:
            resolver.resolve_metric("unknown_metric")

        assert "unknown" in str(exc_info.value).lower()

    def test_get_deprecated_metrics(self, metrics_config):
        """Test getting list of deprecated metrics."""
        resolver = MetricVersionResolver(metrics_config)
        deprecated = resolver.get_deprecated_metrics()

        assert len(deprecated) >= 1
        assert any(m["metric_name"] == "revenue" and m["version"] == "v1"
                   for m in deprecated)

    def test_check_sunset_status(self, metrics_config):
        """Test checking sunset status."""
        resolver = MetricVersionResolver(metrics_config)

        assert resolver.check_sunset_status("old_metric", "v1") is True
        assert resolver.check_sunset_status("revenue", "v2") is False

    def test_supports_rollback(self, metrics_config):
        """Test rollback support check."""
        resolver = MetricVersionResolver(metrics_config)

        assert resolver.supports_rollback_to("revenue", "v1") is True
        assert resolver.supports_rollback_to("old_metric", "v1") is False  # sunset


# ============================================================================
# 5.8.3 - Rollback Orchestrator Tests
# ============================================================================


class TestRollbackOrchestrator:
    """Tests for the rollback orchestrator."""

    def test_authorized_rollback_executes(self, rollback_config):
        """Test that authorized rollback executes successfully."""
        orchestrator = RollbackOrchestrator(rollback_config)
        request = RollbackRequest(
            rollback_id="RB-001",
            triggered_by="oncall@company.com",
            trigger_role="Analytics Oncall",
            reason="Metric mismatch",
            scope=RollbackScope.GLOBAL,
        )

        result = orchestrator.initiate_rollback(request)

        assert result.state == RollbackState.COMPLETED
        assert len(result.actions_completed) > 0

    def test_unauthorized_rollback_fails(self, rollback_config):
        """Test that unauthorized rollback fails."""
        orchestrator = RollbackOrchestrator(rollback_config)
        request = RollbackRequest(
            rollback_id="RB-002",
            triggered_by="junior@company.com",
            trigger_role="Junior Developer",
            reason="I think something is wrong",
            scope=RollbackScope.GLOBAL,
        )

        result = orchestrator.initiate_rollback(request)

        assert result.state == RollbackState.FAILED
        assert "not authorized" in result.error.lower()

    def test_validate_authority(self, rollback_config):
        """Test authority validation."""
        orchestrator = RollbackOrchestrator(rollback_config)

        # Authorized
        authorized, _ = orchestrator.validate_authority(
            RollbackRequest(
                rollback_id="RB-001",
                triggered_by="oncall@company.com",
                trigger_role="Security Oncall",
                reason="Security incident",
                scope=RollbackScope.GLOBAL,
            )
        )
        assert authorized is True

        # Unauthorized
        authorized, reason = orchestrator.validate_authority(
            RollbackRequest(
                rollback_id="RB-002",
                triggered_by="random@company.com",
                trigger_role="Random Person",
                reason="Just because",
                scope=RollbackScope.GLOBAL,
            )
        )
        assert authorized is False
        assert "not authorized" in reason.lower()

    def test_rollback_result_serialization(self, rollback_config):
        """Test that rollback result can be serialized."""
        orchestrator = RollbackOrchestrator(rollback_config)
        request = RollbackRequest(
            rollback_id="RB-003",
            triggered_by="oncall@company.com",
            trigger_role="Analytics Oncall",
            reason="Test",
            scope=RollbackScope.TENANT_SUBSET,
            target_tenants=["tenant-1", "tenant-2"],
        )

        result = orchestrator.initiate_rollback(request)
        result_dict = result.to_dict()

        assert "rollback_id" in result_dict
        assert "state" in result_dict
        assert result_dict["rollback_id"] == "RB-003"

    def test_get_rollback_history(self, rollback_config):
        """Test getting rollback history."""
        orchestrator = RollbackOrchestrator(rollback_config)
        request = RollbackRequest(
            rollback_id="RB-004",
            triggered_by="oncall@company.com",
            trigger_role="Analytics Oncall",
            reason="Test",
            scope=RollbackScope.GLOBAL,
        )

        orchestrator.initiate_rollback(request)
        history = orchestrator.get_rollback_history()

        assert len(history) >= 1
        assert history[-1]["rollback_id"] == "RB-004"


# ============================================================================
# 5.8.4 - Pre-Deploy Validator Tests
# ============================================================================


class TestPreDeployValidator:
    """Tests for the pre-deployment validation framework."""

    def test_validation_runs_all_checks(self, validation_config):
        """Test that validation runs all configured checks."""
        validator = PreDeployValidator(validation_config)
        result = validator.run_validation()

        assert result.validation_id is not None
        assert len(result.checks) > 0

    def test_validation_result_json_output(self, validation_config):
        """Test that validation result produces valid JSON."""
        validator = PreDeployValidator(validation_config)
        result = validator.run_validation()

        json_output = result.to_json()
        assert '"validation_id"' in json_output
        assert '"overall_status"' in json_output
        assert '"can_deploy"' in json_output

    def test_validation_result_has_required_fields(self, validation_config):
        """Test that each check result has required fields."""
        validator = PreDeployValidator(validation_config)
        result = validator.run_validation()

        for check in result.checks:
            check_dict = check.to_dict()
            assert "check_name" in check_dict
            assert "status" in check_dict
            assert "measured_value" in check_dict
            assert "threshold" in check_dict
            assert "blocking" in check_dict

    def test_blocking_failure_blocks_deploy(self, validation_config):
        """Test that blocking failures prevent deployment."""
        # Create a handler that fails
        def failing_handler(config):
            return CheckResult(
                check_name="models_compile",
                status=ValidationStatus.BLOCK,
                measured_value=False,
                threshold=True,
                blocking=True,
                error_message="Compilation failed",
            )

        validator = PreDeployValidator(validation_config)
        validator.check_handlers["models_compile"] = failing_handler

        result = validator.run_validation()

        assert result.can_deploy is False
        assert result.overall_status == ValidationStatus.BLOCK
        assert len(result.blocking_failures) > 0

    def test_warning_allows_deploy_with_approval(self, validation_config):
        """Test that warnings allow deployment with approval."""
        validator = PreDeployValidator(validation_config)
        result = validator.run_validation()

        # Default stub handlers pass, so deployment should be allowed
        assert result.overall_status in (ValidationStatus.PASS, ValidationStatus.WARN)

    def test_sign_off_checklist(self, validation_config):
        """Test getting sign-off checklist."""
        validator = PreDeployValidator(validation_config)

        default_signoff = validator.get_sign_off_checklist()
        assert "Analytics Tech Lead" in default_signoff["required_approvers"]

        rls_signoff = validator.get_sign_off_checklist("rls_change")
        assert "Security Engineer" in rls_signoff["required_approvers"]

    def test_validation_categories_filter(self, validation_config):
        """Test filtering validation by categories."""
        validator = PreDeployValidator(validation_config)

        # Run only dbt_models checks
        result = validator.run_validation(categories=["dbt_models"])

        # Should only have checks from dbt_models category
        check_names = [c.check_name for c in result.checks]
        assert "models_compile" in check_names or "tests_pass" in check_names


# ============================================================================
# 5.8.5 - AI Guardrails Tests
# ============================================================================


class TestAIGuardrails:
    """Tests for the AI guardrails system."""

    def test_prohibited_action_refused(self, ai_restrictions_config):
        """Test that prohibited actions are refused."""
        guardrails = AIGuardrails(ai_restrictions_config)
        check = guardrails.check_action("approve_metric_changes")

        assert check.allowed is False
        assert check.refusal is not None
        assert "Product Manager" in check.refusal.redirect_to

    def test_allowed_action_passes(self, ai_restrictions_config):
        """Test that non-prohibited actions pass."""
        guardrails = AIGuardrails(ai_restrictions_config)
        check = guardrails.check_action("read_metric_definition")

        assert check.allowed is True
        assert check.refusal is None

    def test_refusal_format_response(self, ai_restrictions_config):
        """Test refusal response formatting."""
        guardrails = AIGuardrails(ai_restrictions_config)
        check = guardrails.check_action("trigger_rollback")

        assert check.refusal is not None
        response = check.refusal.format_response()

        assert "REFUSED" in response
        assert "Reason:" in response
        assert "Please contact:" in response

    def test_explicit_refusal(self, ai_restrictions_config):
        """Test explicit action refusal."""
        guardrails = AIGuardrails(ai_restrictions_config)
        refusal = guardrails.refuse_action(
            action_description="Auto-approve deployment",
            reason="Deployments require human sign-off",
            reason_category=RefusalReason.ACCOUNTABILITY_REQUIRED,
            redirect_to="Tech Lead",
        )

        assert refusal.action_attempted == "Auto-approve deployment"
        assert refusal.redirect_to == "Tech Lead"

    def test_require_human_approval(self, ai_restrictions_config):
        """Test requiring human approval."""
        guardrails = AIGuardrails(ai_restrictions_config)
        refusal = guardrails.require_human_approval(
            action_description="Deploy to production",
            approver_role="Analytics Tech Lead",
        )

        assert "approval" in refusal.reason.lower()
        assert refusal.redirect_to == "Analytics Tech Lead"

    def test_business_decision_refused(self, ai_restrictions_config):
        """Test that business decisions are refused."""
        guardrails = AIGuardrails(ai_restrictions_config)
        refusal = guardrails.check_business_decision(
            "Determine if metric change is breaking"
        )

        assert refusal.reason_category == RefusalReason.BUSINESS_DECISION
        assert "human judgment" in refusal.reason.lower()

    def test_audit_log_created(self, ai_restrictions_config):
        """Test that audit log entries are created."""
        guardrails = AIGuardrails(ai_restrictions_config)
        guardrails.check_action("approve_metric_changes")
        guardrails.check_action("read_data")

        audit_log = guardrails.get_audit_log()
        assert len(audit_log) == 2

    def test_enforce_behavior(self, ai_restrictions_config):
        """Test behavior enforcement checking."""
        guardrails = AIGuardrails(ai_restrictions_config)

        assert guardrails.enforce_behavior("log_all_decisions") is True
        assert guardrails.enforce_behavior("nonexistent_behavior") is False

    def test_refusal_callback(self, ai_restrictions_config):
        """Test that refusal callback is called."""
        refusals_received = []

        def on_refusal(refusal):
            refusals_received.append(refusal)

        guardrails = AIGuardrails(ai_restrictions_config, on_refusal=on_refusal)
        guardrails.check_action("classify_breaking_changes")

        assert len(refusals_received) == 1
        assert refusals_received[0].action_attempted == "Classify breaking vs non-breaking"

    def test_guardrail_check_serialization(self, ai_restrictions_config):
        """Test that guardrail check can be serialized."""
        guardrails = AIGuardrails(ai_restrictions_config)
        check = guardrails.check_action("trigger_rollback")

        check_dict = check.to_dict()
        assert "allowed" in check_dict
        assert "action_id" in check_dict
        assert "refusal" in check_dict


# ============================================================================
# Integration Tests
# ============================================================================


class TestGovernanceIntegration:
    """Integration tests across governance modules."""

    def test_approval_before_deploy_workflow(
        self,
        approval_config,
        change_requests_config,
        validation_config,
    ):
        """Test complete approval -> validation workflow."""
        # Step 1: Check approval
        gate = ApprovalGate(approval_config, change_requests_config)
        approval_result = gate.validate_change_request("CR-001")

        assert approval_result.status == ApprovalStatus.PASS

        # Step 2: Run validation
        validator = PreDeployValidator(validation_config)
        validation_result = validator.run_validation()

        # Step 3: Both must pass for deployment
        can_deploy = (
            approval_result.status == ApprovalStatus.PASS
            and validation_result.can_deploy
        )
        assert can_deploy is True

    def test_ai_cannot_bypass_approval(
        self,
        ai_restrictions_config,
        approval_config,
        change_requests_config,
    ):
        """Test that AI cannot bypass approval process."""
        guardrails = AIGuardrails(ai_restrictions_config)

        # AI tries to approve
        check = guardrails.check_action("approve_metric_changes")
        assert check.allowed is False

        # Human must approve through proper channel
        gate = ApprovalGate(approval_config, change_requests_config)
        # CR-002 is not approved
        result = gate.validate_change_request("CR-002")
        assert result.status == ApprovalStatus.BLOCK

    def test_rollback_requires_authority_not_ai(
        self,
        ai_restrictions_config,
        rollback_config,
    ):
        """Test that AI cannot trigger rollback, but authorized humans can."""
        guardrails = AIGuardrails(ai_restrictions_config)

        # AI cannot trigger
        check = guardrails.check_action("trigger_rollback")
        assert check.allowed is False

        # But authorized human can
        orchestrator = RollbackOrchestrator(rollback_config)
        request = RollbackRequest(
            rollback_id="RB-INT-001",
            triggered_by="oncall@company.com",
            trigger_role="Analytics Oncall",
            reason="Emergency rollback",
            scope=RollbackScope.GLOBAL,
        )

        result = orchestrator.initiate_rollback(request)
        assert result.state == RollbackState.COMPLETED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
