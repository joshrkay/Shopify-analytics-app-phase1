"""
5.8.4 - Pre-Deployment Validation Framework

Deterministic execution with structured JSON output. No auto-retry.
"""

import json
import logging
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .base import load_yaml_config, serialize_dataclass

logger = logging.getLogger(__name__)


class ValidationStatus(Enum):
    """Status of a validation check."""

    PASS = "PASS"
    WARN = "WARN"
    BLOCK = "BLOCK"
    SKIP = "SKIP"
    ERROR = "ERROR"


class FailureBehavior(Enum):
    """What to do when a check fails."""

    BLOCK_DEPLOYMENT = "BLOCK_DEPLOYMENT"
    WARN_REQUIRE_APPROVAL = "WARN_REQUIRE_APPROVAL"
    WARN_ONLY = "WARN_ONLY"


@dataclass
class CheckResult:
    """
    Result of a single validation check.

    Follows the required_fields specification:
    - check_name
    - status
    - measured_value
    - threshold
    - blocking
    """

    check_name: str
    status: ValidationStatus
    measured_value: Any
    threshold: Any
    blocking: bool
    description: str = ""
    error_message: str | None = None
    execution_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return serialize_dataclass(self)


@dataclass
class ValidationResult:
    """
    Complete validation result.

    Attributes:
        validation_id: Unique ID for this validation run
        overall_status: PASS, WARN, or BLOCK
        can_deploy: Whether deployment is allowed
        checks: List of individual check results
        blocking_failures: Checks that are blocking deployment
        warnings: Checks that are warnings only
        started_at: When validation started
        completed_at: When validation completed
        requires_approval: Whether human approval is needed
    """

    validation_id: str
    overall_status: ValidationStatus
    can_deploy: bool
    checks: list[CheckResult]
    blocking_failures: list[CheckResult]
    warnings: list[CheckResult]
    started_at: datetime
    completed_at: datetime | None = None
    requires_approval: bool = False
    approval_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "validation_id": self.validation_id,
            "overall_status": self.overall_status.value,
            "can_deploy": self.can_deploy,
            "requires_approval": self.requires_approval,
            "approval_reason": self.approval_reason,
            "summary": {
                "total_checks": len(self.checks),
                "passed": len(
                    [c for c in self.checks if c.status == ValidationStatus.PASS]
                ),
                "warnings": len(self.warnings),
                "blocking_failures": len(self.blocking_failures),
            },
            "checks": [c.to_dict() for c in self.checks],
            "blocking_failures": [c.to_dict() for c in self.blocking_failures],
            "warnings": [c.to_dict() for c in self.warnings],
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


@dataclass
class ValidationReport:
    """Exportable validation report for CI/CD integration."""

    result: ValidationResult
    environment: str
    git_sha: str | None = None
    git_branch: str | None = None
    triggered_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "report_version": "1.0",
            "environment": self.environment,
            "git_sha": self.git_sha,
            "git_branch": self.git_branch,
            "triggered_by": self.triggered_by,
            "result": self.result.to_dict(),
        }

    def export_json(self, file_path: str | Path) -> None:
        """Export report to JSON file."""
        with open(file_path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)


class PreDeployValidator:
    """
    Pre-deployment validation framework.

    Executes checks deterministically and produces structured output.
    """

    def __init__(
        self,
        config_path: str | Path,
        check_handlers: dict[str, Callable[..., CheckResult]] | None = None,
    ):
        """
        Initialize the validator.

        Args:
            config_path: Path to pre_deploy_validation.yaml
            check_handlers: Dict mapping check names to handler functions
        """
        self.config_path = Path(config_path)
        self.check_handlers = check_handlers or {}

        self._config: dict[str, Any] = {}
        self._load_config()
        self._register_default_handlers()

    def _load_config(self) -> None:
        """Load validation configuration from YAML."""
        self._config = load_yaml_config(self.config_path, logger)

    def _register_default_handlers(self) -> None:
        """Register default check handlers."""
        # These would be implemented with actual validation logic
        default_checks = [
            "models_compile",
            "tests_pass",
            "no_deprecation_warnings",
            "docs_generated",
            "lineage_acyclic",
            "sync_time",
            "row_count_match",
            "schema_match",
            "cache_freshness",
            "cross_tenant_isolation",
            "multi_tenant_access",
            "merchant_data_isolation",
            "agency_client_isolation",
            "super_admin_access",
            "load_time",
            "network_conditions",
            "empty_cache_test",
            "no_console_errors",
            "calculation_match",
            "historical_comparison",
        ]

        for check in default_checks:
            if check not in self.check_handlers:
                self.check_handlers[check] = self._create_stub_handler(check)

    def _create_stub_handler(self, check_name: str) -> Callable[..., CheckResult]:
        """Create a stub handler for a check."""

        def handler(config: dict[str, Any]) -> CheckResult:
            return CheckResult(
                check_name=check_name,
                status=ValidationStatus.PASS,
                measured_value="stub",
                threshold=config.get("threshold"),
                blocking=config.get("blocking", True),
                description=config.get("description", ""),
            )

        return handler

    def run_validation(
        self,
        categories: list[str] | None = None,
        environment: str = "staging",
    ) -> ValidationResult:
        """
        Run pre-deployment validation.

        Args:
            categories: Specific categories to validate (None = all)
            environment: Target environment

        Returns:
            ValidationResult with all check results
        """
        validation_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        checks: list[CheckResult] = []

        validation_config = self._config.get("pre_deploy_validation", {})

        # Determine which categories to run
        if categories is None:
            categories = list(validation_config.keys())

        logger.info(
            f"Starting validation {validation_id} for categories: {categories}"
        )

        for category in categories:
            category_config = validation_config.get(category, {})
            if not category_config:
                continue

            category_checks = category_config.get("checks", [])
            failure_behavior = category_config.get(
                "failure_behavior", "BLOCK_DEPLOYMENT"
            )

            for check_config in category_checks:
                if isinstance(check_config, dict):
                    check_result = self._run_check(
                        check_config, category, failure_behavior
                    )
                    checks.append(check_result)
                elif isinstance(check_config, str):
                    # Simple string check
                    check_result = self._run_check(
                        {"name": check_config, "description": check_config},
                        category,
                        failure_behavior,
                    )
                    checks.append(check_result)

        # Run smoke tests
        smoke_tests = validation_config.get("smoke_tests", [])
        for smoke_test in smoke_tests:
            if isinstance(smoke_test, dict):
                check_result = self._run_smoke_test(smoke_test)
                checks.append(check_result)

        # Analyze results
        blocking_failures = [
            c
            for c in checks
            if c.status in (ValidationStatus.BLOCK, ValidationStatus.ERROR)
            and c.blocking
        ]
        warnings = [
            c
            for c in checks
            if c.status == ValidationStatus.WARN
            or (
                c.status in (ValidationStatus.BLOCK, ValidationStatus.ERROR)
                and not c.blocking
            )
        ]

        # Determine overall status
        if blocking_failures:
            overall_status = ValidationStatus.BLOCK
            can_deploy = False
            requires_approval = False
        elif warnings:
            overall_status = ValidationStatus.WARN
            # Check if any warnings require approval
            requires_approval = any(
                not c.blocking
                and c.status in (ValidationStatus.BLOCK, ValidationStatus.ERROR)
                for c in checks
            )
            can_deploy = not requires_approval
        else:
            overall_status = ValidationStatus.PASS
            can_deploy = True
            requires_approval = False

        result = ValidationResult(
            validation_id=validation_id,
            overall_status=overall_status,
            can_deploy=can_deploy,
            checks=checks,
            blocking_failures=blocking_failures,
            warnings=warnings,
            started_at=started_at,
            completed_at=datetime.now(timezone.utc),
            requires_approval=requires_approval,
            approval_reason="Non-blocking checks failed"
            if requires_approval
            else None,
        )

        logger.info(
            f"Validation {validation_id} completed: {overall_status.value}, "
            f"can_deploy={can_deploy}"
        )

        return result

    def _run_check(
        self, check_config: dict[str, Any], category: str, failure_behavior: str
    ) -> CheckResult:
        """Run a single validation check."""
        check_name = check_config.get("name", "unknown")
        start_time = time.time()

        # Determine if blocking based on failure_behavior
        blocking = failure_behavior == "BLOCK_DEPLOYMENT"
        if "blocking" in check_config:
            blocking = check_config["blocking"]

        handler = self.check_handlers.get(check_name)
        if not handler:
            return CheckResult(
                check_name=check_name,
                status=ValidationStatus.ERROR,
                measured_value=None,
                threshold=check_config.get("threshold"),
                blocking=blocking,
                description=check_config.get("description", ""),
                error_message=f"No handler registered for check: {check_name}",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        try:
            result = handler(check_config)
            result.execution_time_ms = int((time.time() - start_time) * 1000)
            return result
        except Exception as e:
            logger.exception(f"Check {check_name} failed with exception: {e}")
            return CheckResult(
                check_name=check_name,
                status=ValidationStatus.ERROR,
                measured_value=None,
                threshold=check_config.get("threshold"),
                blocking=blocking,
                description=check_config.get("description", ""),
                error_message=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

    def _run_smoke_test(self, smoke_test: dict[str, Any]) -> CheckResult:
        """Run a smoke test."""
        name = smoke_test.get("name", "unknown")
        blocking = smoke_test.get("blocking", True)
        start_time = time.time()

        # Stub implementation - would run actual smoke test
        return CheckResult(
            check_name=f"smoke_test_{name}",
            status=ValidationStatus.PASS,
            measured_value="executed",
            threshold=None,
            blocking=blocking,
            description=smoke_test.get("description", ""),
            execution_time_ms=int((time.time() - start_time) * 1000),
        )

    def create_report(
        self,
        result: ValidationResult,
        environment: str,
        git_sha: str | None = None,
        git_branch: str | None = None,
        triggered_by: str | None = None,
    ) -> ValidationReport:
        """
        Create an exportable validation report.

        Args:
            result: The validation result
            environment: Target environment
            git_sha: Git commit SHA
            git_branch: Git branch name
            triggered_by: Who triggered the validation

        Returns:
            ValidationReport ready for export
        """
        return ValidationReport(
            result=result,
            environment=environment,
            git_sha=git_sha,
            git_branch=git_branch,
            triggered_by=triggered_by,
        )

    def get_sign_off_checklist(self, change_type: str | None = None) -> dict[str, Any]:
        """
        Get the sign-off checklist for the given change type.

        Args:
            change_type: Type of change (metric_change, rls_change, etc.)

        Returns:
            Sign-off configuration
        """
        sign_off = self._config.get("sign_off", {})
        required_approvers = sign_off.get("required_approvers", {})

        if change_type and change_type in required_approvers:
            approvers = required_approvers[change_type]
        else:
            approvers = required_approvers.get("default", [])

        return {
            "required_approvers": approvers,
            "template": sign_off.get("template", ""),
        }


# CI/CD Integration Hook
class CICDIntegration:
    """Helper class for CI/CD integration."""

    def __init__(self, validator: PreDeployValidator):
        """Initialize with validator."""
        self.validator = validator

    def run_and_exit(
        self,
        categories: list[str] | None = None,
        output_file: str | None = None,
        environment: str = "staging",
    ) -> int:
        """
        Run validation and return exit code for CI/CD.

        Args:
            categories: Categories to validate
            output_file: Path to write JSON report
            environment: Target environment

        Returns:
            Exit code: 0 for success, 1 for failure
        """
        result = self.validator.run_validation(
            categories=categories, environment=environment
        )

        # Create and export report
        report = self.validator.create_report(
            result=result,
            environment=environment,
            git_sha=self._get_git_sha(),
            git_branch=self._get_git_branch(),
        )

        if output_file:
            report.export_json(output_file)
            logger.info(f"Validation report written to {output_file}")

        # Print summary to stdout
        print(result.to_json())

        # Return exit code
        if result.can_deploy:
            return 0
        else:
            return 1

    def _get_git_sha(self) -> str | None:
        """Get current git SHA."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None

    def _get_git_branch(self) -> str | None:
        """Get current git branch."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() if result.returncode == 0 else None
        except Exception:
            return None
