"""
Unit tests for per-dataset guardrail overrides in explore_guardrails.py.

Tests cover:
- DatasetGuardrailOverrides dataclass
- _get_effective_guardrails returns global defaults when no override
- _get_effective_guardrails applies per-dataset overrides
- Per-dataset overrides can only be stricter (min of override vs global)
- validate_query uses effective guardrails for date range, group-by, metrics, filters
- Existing guardrail behavior unchanged when no overrides present

Story 5.2.6 — Performance Guardrails (Superset Layer)
"""

import sys
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

# Add docker/superset to path for import (tests run from backend/)
_SUPERSET_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "docker", "superset",
)
if _SUPERSET_DIR not in sys.path:
    sys.path.insert(0, os.path.abspath(_SUPERSET_DIR))


# ---------------------------------------------------------------------------
# DatasetGuardrailOverrides
# ---------------------------------------------------------------------------

class TestDatasetGuardrailOverrides:
    """Test the overrides dataclass."""

    def test_defaults_are_none(self):
        from explore_guardrails import DatasetGuardrailOverrides
        o = DatasetGuardrailOverrides()
        assert o.max_date_range_days is None
        assert o.query_timeout_seconds is None
        assert o.row_limit is None
        assert o.cache_ttl_minutes is None

    def test_frozen(self):
        from explore_guardrails import DatasetGuardrailOverrides
        o = DatasetGuardrailOverrides(max_date_range_days=30)
        with pytest.raises(AttributeError):
            o.max_date_range_days = 60


# ---------------------------------------------------------------------------
# _get_effective_guardrails
# ---------------------------------------------------------------------------

class TestGetEffectiveGuardrails:
    """Test effective guardrail resolution."""

    def test_no_override_returns_global(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PERFORMANCE_GUARDRAILS,
        )
        validator = ExplorePermissionValidator(ExplorePersona.MERCHANT)
        # 'dim_customers' has no guardrail_overrides (disabled dataset)
        effective = validator._get_effective_guardrails("dim_customers")
        assert effective.max_date_range_days == PERFORMANCE_GUARDRAILS.max_date_range_days

    def test_unknown_dataset_returns_global(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PERFORMANCE_GUARDRAILS,
        )
        validator = ExplorePermissionValidator(ExplorePersona.MERCHANT)
        effective = validator._get_effective_guardrails("nonexistent_dataset")
        assert effective == PERFORMANCE_GUARDRAILS

    def test_override_applies_stricter_limit(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PERFORMANCE_GUARDRAILS,
            DATASET_EXPLORE_CONFIGS,
            DatasetExploreConfig,
            DatasetGuardrailOverrides,
        )
        # fact_orders has overrides set to 90/20/50000/30 which matches global
        validator = ExplorePermissionValidator(ExplorePersona.MERCHANT)
        effective = validator._get_effective_guardrails("fact_orders")
        # Should be min(override, global)
        assert effective.max_date_range_days <= PERFORMANCE_GUARDRAILS.max_date_range_days
        assert effective.query_timeout_seconds <= PERFORMANCE_GUARDRAILS.query_timeout_seconds
        assert effective.row_limit <= PERFORMANCE_GUARDRAILS.row_limit

    def test_override_cannot_exceed_global(self):
        """Per-dataset overrides that are LESS strict get clamped to global."""
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PerformanceGuardrails,
            DatasetGuardrailOverrides,
            DATASET_EXPLORE_CONFIGS,
            DatasetExploreConfig,
        )
        # Create a custom validator with very strict global guardrails
        strict_global = PerformanceGuardrails(
            max_date_range_days=30,
            query_timeout_seconds=10,
            row_limit=10000,
        )
        validator = ExplorePermissionValidator(
            ExplorePersona.MERCHANT,
            guardrails=strict_global,
        )
        # fact_orders override says 90 days, but global is 30 → effective = 30
        effective = validator._get_effective_guardrails("fact_orders")
        assert effective.max_date_range_days == 30
        assert effective.query_timeout_seconds == 10
        assert effective.row_limit == 10000


# ---------------------------------------------------------------------------
# validate_query with per-dataset guardrails
# ---------------------------------------------------------------------------

class TestValidateQueryWithOverrides:
    """Test that validate_query uses effective per-dataset guardrails."""

    def test_date_range_uses_effective_limit(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PerformanceGuardrails,
        )
        # Set global to 30 days
        strict = PerformanceGuardrails(max_date_range_days=30)
        validator = ExplorePermissionValidator(
            ExplorePersona.MERCHANT,
            guardrails=strict,
        )
        now = datetime.now(timezone.utc)
        result = validator.validate_query("fact_orders", {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)"],
            "start_date": now - timedelta(days=31),
            "end_date": now,
        })
        assert result.is_valid is False
        assert result.error_code == "DATE_RANGE_EXCEEDED"

    def test_within_effective_limit_passes(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
        )
        validator = ExplorePermissionValidator(ExplorePersona.MERCHANT)
        now = datetime.now(timezone.utc)
        result = validator.validate_query("fact_orders", {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)"],
            "start_date": now - timedelta(days=30),
            "end_date": now,
        })
        assert result.is_valid is True

    def test_too_many_group_by_rejected(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
        )
        validator = ExplorePermissionValidator(ExplorePersona.MERCHANT)
        result = validator.validate_query("fact_orders", {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)"],
            "group_by": ["order_date", "channel", "campaign_id"],  # 3 > max 2
        })
        assert result.is_valid is False
        assert result.error_code == "TOO_MANY_GROUP_BY"

    def test_too_many_filters_rejected(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PerformanceGuardrails,
        )
        strict = PerformanceGuardrails(max_filters=2)
        validator = ExplorePermissionValidator(
            ExplorePersona.MERCHANT,
            guardrails=strict,
        )
        result = validator.validate_query("fact_orders", {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)"],
            "filters": [{"col": "a"}, {"col": "b"}, {"col": "c"}],  # 3 > 2
        })
        assert result.is_valid is False
        assert result.error_code == "TOO_MANY_FILTERS"

    def test_too_many_metrics_rejected(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PerformanceGuardrails,
        )
        strict = PerformanceGuardrails(max_metrics_per_query=1)
        validator = ExplorePermissionValidator(
            ExplorePersona.MERCHANT,
            guardrails=strict,
        )
        result = validator.validate_query("fact_orders", {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)", "COUNT(order_id)"],  # 2 > 1
        })
        assert result.is_valid is False
        assert result.error_code == "TOO_MANY_METRICS"


# ---------------------------------------------------------------------------
# Backward compatibility — existing behavior unchanged
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Ensure existing behavior is preserved for datasets without overrides."""

    def test_marketing_spend_no_overrides(self):
        """fact_marketing_spend has no guardrail_overrides set."""
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
            PERFORMANCE_GUARDRAILS,
            DATASET_EXPLORE_CONFIGS,
        )
        config = DATASET_EXPLORE_CONFIGS.get("fact_marketing_spend")
        assert config is not None
        assert config.guardrail_overrides is None

        validator = ExplorePermissionValidator(ExplorePersona.MERCHANT)
        effective = validator._get_effective_guardrails("fact_marketing_spend")
        assert effective == PERFORMANCE_GUARDRAILS

    def test_disabled_dataset_still_rejected(self):
        from explore_guardrails import (
            ExplorePermissionValidator,
            ExplorePersona,
        )
        validator = ExplorePermissionValidator(ExplorePersona.MERCHANT)
        result = validator.validate_dataset("dim_customers")
        assert result.is_valid is False
        assert result.error_code == "DATASET_DISABLED"
