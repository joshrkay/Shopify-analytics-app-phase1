"""
Unit tests for data quality guard middleware and Superset quality hook.

Tests cover:
- FAIL state: blocks dashboards, APIs, and AI insights
- WARN state: allows dashboards with warning, blocks AI insights
- PASS state: allows everything
- Dependency injection guard (DataQualityGuard)
- Superset quality hook (SupersetQualityHook)
- Result dataclass correctness
"""

import pytest
from unittest.mock import Mock, MagicMock, patch

from src.api.dq.service import DataQualityVerdict
from src.models.dq_models import DataQualityState
from src.middleware.data_quality_guard import (
    DataQualityCheckResult,
    DataQualityGuard,
    check_data_quality,
)
from src.middleware.superset_quality_hook import (
    QueryQualityResult,
    SupersetQualityHook,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _make_verdict(state, failure_count=0, warning_count=0, passed_count=0):
    """Build a DataQualityVerdict for testing."""
    failing_checks = [f"check_{i}" for i in range(failure_count)]
    total = failure_count + warning_count + passed_count
    return DataQualityVerdict(
        state=state,
        total_checks=total,
        passed_count=passed_count,
        warning_count=warning_count,
        failure_count=failure_count,
        failing_checks=failing_checks,
        message=f"{state.value}: {total} checks",
    )


def _pass_verdict():
    return _make_verdict(DataQualityState.PASS_STATE, passed_count=5)


def _warn_verdict():
    return _make_verdict(DataQualityState.WARN, warning_count=2, passed_count=3)


def _fail_verdict():
    return _make_verdict(
        DataQualityState.FAIL, failure_count=1, warning_count=1, passed_count=3
    )


@pytest.fixture
def mock_request():
    """Create a mock FastAPI request with tenant context."""
    request = Mock()
    request.url.path = "/api/analytics/test"
    request.state = MagicMock()
    request.state.data_quality = None
    del request.state.data_quality
    return request


@pytest.fixture
def mock_tenant_ctx():
    """Mock tenant context."""
    ctx = Mock()
    ctx.tenant_id = "test-tenant-001"
    ctx.billing_tier = "free"
    return ctx


# ---------------------------------------------------------------------------
# Tests: check_data_quality
# ---------------------------------------------------------------------------

class TestCheckDataQuality:
    """Tests for the check_data_quality function."""

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_pass_state(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """PASS verdict returns is_passed=True, all consumers allowed."""
        mock_get_ctx.return_value = mock_tenant_ctx
        verdict = _pass_verdict()

        result = check_data_quality(mock_request, verdict=verdict)

        assert result.state == DataQualityState.PASS_STATE
        assert result.is_passed is True
        assert result.is_failed is False
        assert result.has_warnings is False
        assert result.ai_allowed is True
        assert result.dashboard_allowed is True
        assert result.dashboard_warning is None

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_warn_state(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """WARN verdict: dashboards allowed with warning, AI disabled."""
        mock_get_ctx.return_value = mock_tenant_ctx
        verdict = _warn_verdict()

        result = check_data_quality(mock_request, verdict=verdict)

        assert result.state == DataQualityState.WARN
        assert result.is_passed is False
        assert result.has_warnings is True
        assert result.ai_allowed is False
        assert result.dashboard_allowed is True
        assert result.dashboard_warning is not None

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_fail_state(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """FAIL verdict: all consumers blocked."""
        mock_get_ctx.return_value = mock_tenant_ctx
        verdict = _fail_verdict()

        result = check_data_quality(mock_request, verdict=verdict)

        assert result.state == DataQualityState.FAIL
        assert result.is_passed is False
        assert result.is_failed is True
        assert result.ai_allowed is False
        assert result.dashboard_allowed is False
        assert len(result.failing_checks) == 1

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_attaches_to_request_state(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """Result is attached to request.state.data_quality."""
        mock_get_ctx.return_value = mock_tenant_ctx
        verdict = _pass_verdict()

        result = check_data_quality(mock_request, verdict=verdict)

        assert mock_request.state.data_quality == result

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_no_inputs_returns_pass(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """No check results provided defaults to PASS."""
        mock_get_ctx.return_value = mock_tenant_ctx

        result = check_data_quality(mock_request)

        assert result.state == DataQualityState.PASS_STATE
        assert result.is_passed is True

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_to_dict(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """to_dict returns expected structure."""
        mock_get_ctx.return_value = mock_tenant_ctx
        verdict = _fail_verdict()

        result = check_data_quality(mock_request, verdict=verdict)
        d = result.to_dict()

        assert d["state"] == "fail"
        assert d["is_failed"] is True
        assert d["ai_allowed"] is False
        assert d["dashboard_allowed"] is False
        assert "failing_checks" in d


# ---------------------------------------------------------------------------
# Tests: DataQualityGuard (DI)
# ---------------------------------------------------------------------------

class TestDataQualityGuard:
    """Tests for the DataQualityGuard dependency-injection class."""

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_require_pass_allows_pass(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """require_pass does not raise on PASS state."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        verdict = _pass_verdict()

        result = guard.require_pass(mock_request, verdict=verdict)

        assert result.is_passed is True

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_require_pass_allows_warn(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """require_pass allows WARN state (with warning attached)."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        verdict = _warn_verdict()

        result = guard.require_pass(mock_request, verdict=verdict)

        assert result.has_warnings is True
        assert result.dashboard_allowed is True

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_require_pass_blocks_fail(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """require_pass raises 503 on FAIL state."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        verdict = _fail_verdict()

        with pytest.raises(Exception) as exc_info:
            guard.require_pass(mock_request, verdict=verdict)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["error_code"] == "DATA_QUALITY_FAILED"

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_require_ai_allowed_blocks_warn(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """require_ai_allowed raises 503 on WARN state (AI disabled)."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        verdict = _warn_verdict()

        with pytest.raises(Exception) as exc_info:
            guard.require_ai_allowed(mock_request, verdict=verdict)

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail["error_code"] == "AI_QUALITY_BLOCKED"

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_require_ai_allowed_blocks_fail(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """require_ai_allowed raises 503 on FAIL state."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        verdict = _fail_verdict()

        with pytest.raises(Exception) as exc_info:
            guard.require_ai_allowed(mock_request, verdict=verdict)

        assert exc_info.value.status_code == 503

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_require_ai_allowed_allows_pass(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """require_ai_allowed allows PASS state."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        verdict = _pass_verdict()

        result = guard.require_ai_allowed(mock_request, verdict=verdict)

        assert result.ai_allowed is True

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_check_nonblocking(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """check() does not raise even on FAIL."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        verdict = _fail_verdict()

        result = guard.check(mock_request, verdict=verdict)

        assert result.is_failed is True  # no exception raised


# ---------------------------------------------------------------------------
# Tests: SupersetQualityHook
# ---------------------------------------------------------------------------

class TestSupersetQualityHook:
    """Tests for the SupersetQualityHook."""

    def test_pass_allows_query(self):
        """PASS state allows Superset queries."""
        verdict = _pass_verdict()

        result = SupersetQualityHook.check_quality(
            tenant_id="t-001",
            verdict=verdict,
        )

        assert result.is_allowed is True
        assert result.warning_message is None
        assert result.blocked_reason is None
        assert result.quality_state == "pass"

    def test_warn_allows_with_warning(self):
        """WARN state allows queries with warning message."""
        verdict = _warn_verdict()

        result = SupersetQualityHook.check_quality(
            tenant_id="t-001",
            verdict=verdict,
        )

        assert result.is_allowed is True
        assert result.warning_message is not None
        assert result.blocked_reason is None
        assert result.quality_state == "warn"

    def test_fail_blocks_query(self):
        """FAIL state blocks Superset queries."""
        verdict = _fail_verdict()

        result = SupersetQualityHook.check_quality(
            tenant_id="t-001",
            verdict=verdict,
        )

        assert result.is_allowed is False
        assert result.blocked_reason is not None
        assert result.quality_state == "fail"
        assert len(result.failing_checks) == 1

    def test_instance_method(self):
        """Instance method works the same as static convenience."""
        hook = SupersetQualityHook()
        verdict = _fail_verdict()

        result = hook.check_query_quality(
            tenant_id="t-001",
            verdict=verdict,
        )

        assert result.is_allowed is False

    def test_to_dict(self):
        """to_dict returns expected structure."""
        verdict = _warn_verdict()

        result = SupersetQualityHook.check_quality(
            tenant_id="t-001",
            verdict=verdict,
        )
        d = result.to_dict()

        assert d["is_allowed"] is True
        assert d["quality_state"] == "warn"
        assert d["warning_message"] is not None

    def test_no_verdict_defaults_pass(self):
        """No inputs aggregates to PASS."""
        result = SupersetQualityHook.check_quality(
            tenant_id="t-001",
        )

        assert result.is_allowed is True
        assert result.quality_state == "pass"


# ---------------------------------------------------------------------------
# Tests: Consumer protection rules
# ---------------------------------------------------------------------------

class TestConsumerProtectionRules:
    """Tests verifying the FAIL/WARN/PASS consumer protection matrix."""

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_fail_blocks_dashboard(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """FAIL: dashboard_allowed=False."""
        mock_get_ctx.return_value = mock_tenant_ctx
        result = check_data_quality(mock_request, verdict=_fail_verdict())
        assert result.dashboard_allowed is False

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_fail_disables_ai(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """FAIL: ai_allowed=False."""
        mock_get_ctx.return_value = mock_tenant_ctx
        result = check_data_quality(mock_request, verdict=_fail_verdict())
        assert result.ai_allowed is False

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_fail_returns_503(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """FAIL: analytics APIs return 503."""
        mock_get_ctx.return_value = mock_tenant_ctx
        guard = DataQualityGuard()
        with pytest.raises(Exception) as exc_info:
            guard.require_pass(mock_request, verdict=_fail_verdict())
        assert exc_info.value.status_code == 503

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_warn_allows_dashboard_with_warning(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """WARN: dashboard_allowed=True with warning banner."""
        mock_get_ctx.return_value = mock_tenant_ctx
        result = check_data_quality(mock_request, verdict=_warn_verdict())
        assert result.dashboard_allowed is True
        assert result.dashboard_warning is not None

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_warn_disables_ai(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """WARN: ai_allowed=False."""
        mock_get_ctx.return_value = mock_tenant_ctx
        result = check_data_quality(mock_request, verdict=_warn_verdict())
        assert result.ai_allowed is False

    def test_fail_blocks_superset(self):
        """FAIL: Superset queries blocked."""
        result = SupersetQualityHook.check_quality(
            tenant_id="t-001", verdict=_fail_verdict()
        )
        assert result.is_allowed is False

    def test_warn_allows_superset_with_warning(self):
        """WARN: Superset queries allowed with warning banner."""
        result = SupersetQualityHook.check_quality(
            tenant_id="t-001", verdict=_warn_verdict()
        )
        assert result.is_allowed is True
        assert result.warning_message is not None

    @patch("src.middleware.data_quality_guard.get_tenant_context")
    def test_pass_allows_everything(self, mock_get_ctx, mock_request, mock_tenant_ctx):
        """PASS: all consumers enabled, no warnings."""
        mock_get_ctx.return_value = mock_tenant_ctx
        result = check_data_quality(mock_request, verdict=_pass_verdict())
        assert result.dashboard_allowed is True
        assert result.ai_allowed is True
        assert result.dashboard_warning is None
        assert result.is_passed is True
