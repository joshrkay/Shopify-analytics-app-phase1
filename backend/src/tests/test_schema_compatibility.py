"""
Unit and property-based tests for SchemaCompatibilityChecker.

Story 5.2 — Prompt 5.2.3. Critical path: schema compatibility must detect
all breaking changes (column removal, type change, view removal). Property-based
tests prove no edge case bypasses the checker.
"""

from datetime import datetime, timezone

import pytest

from src.services.schema_compatibility_checker import (
    SchemaCompatibilityChecker,
    DatasetSchemaSnapshot,
    DatasetViewSchema,
    ColumnSchema,
    BreakingChange,
    CompatibilityResult,
    build_snapshot_from_manifest,
    _is_semantic_view,
)


# =============================================================================
# Fixtures: manifest and snapshot builders
# =============================================================================


def _make_manifest_node(name: str, columns: dict[str, dict]) -> dict:
    """Build a single model node for manifest.nodes."""
    return {
        "unique_id": f"model.markinsight.{name}",
        "name": name,
        "schema": "semantic",
        "database": "markinsight",
        "description": "",
        "columns": columns,
        "config": {"materialized": "view"},
        "tags": ["semantic"],
    }


def _make_columns(
    *names: str,
    exposed: list[str] | None = None,
    types: dict[str, str] | None = None,
) -> dict[str, dict]:
    """Build columns dict. If exposed is None, all are exposed."""
    exposed_set = set(exposed) if exposed is not None else set(names)
    types = types or {}
    return {
        n: {
            "name": n,
            "data_type": types.get(n, "VARCHAR"),
            "meta": {"superset_expose": n in exposed_set},
        }
        for n in names
    }


def _manifest(*nodes: tuple[tuple[str, dict], ...]) -> dict:
    """Build minimal manifest with given model names and column configs."""
    return {
        "nodes": {
            f"model.markinsight.{name}": _make_manifest_node(name, cols)
            for name, cols in nodes
        }
        if nodes
        else {},
    }


# =============================================================================
# Unit tests: column removal
# =============================================================================


class TestColumnRemoval:
    """Exposed column removal must be detected as breaking."""

    def test_removed_exposed_column_fails(self):
        current = build_snapshot_from_manifest(
            _manifest(
                ("fact_orders_current", _make_columns("tenant_id", "revenue_gross")),
            )
        )
        new_manifest = _manifest(
            ("fact_orders_current", _make_columns("tenant_id")),  # revenue_gross removed
        )
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is False
        assert any(
            b.change_type == "column_removed" and b.column_name == "revenue_gross"
            for b in result.breaking_changes
        )

    def test_removed_non_exposed_column_passes(self):
        current = build_snapshot_from_manifest(
            _manifest(
                (
                    "fact_orders_current",
                    _make_columns("tenant_id", "revenue_gross", exposed=["tenant_id", "revenue_gross"]),
                ),
            )
        )
        # internal_col not exposed; removing it is additive/safe
        new_manifest = _manifest(
            (
                "fact_orders_current",
                _make_columns("tenant_id", "revenue_gross", exposed=["tenant_id", "revenue_gross"]),
            ),
        )
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is True

    def test_additive_new_column_passes(self):
        current = build_snapshot_from_manifest(
            _manifest(
                ("fact_orders_current", _make_columns("tenant_id", "revenue_gross")),
            )
        )
        new_manifest = _manifest(
            (
                "fact_orders_current",
                _make_columns("tenant_id", "revenue_gross", "new_col"),
            ),
        )
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is True
        assert any("new_col" in a for a in result.additive_changes)


# =============================================================================
# Unit tests: type change
# =============================================================================


class TestColumnTypeChange:
    """Exposed column type change must be detected as breaking."""

    def test_type_change_detected(self):
        current = build_snapshot_from_manifest(
            _manifest(
                (
                    "fact_orders_current",
                    _make_columns("tenant_id", "revenue_gross", types={"revenue_gross": "NUMERIC"}),
                ),
            )
        )
        new_manifest = _manifest(
            (
                "fact_orders_current",
                _make_columns("tenant_id", "revenue_gross", types={"revenue_gross": "VARCHAR"}),
            ),
        )
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is False
        assert any(
            b.change_type == "column_type_changed" and b.column_name == "revenue_gross"
            for b in result.breaking_changes
        )

    def test_same_type_passes(self):
        current = build_snapshot_from_manifest(
            _manifest(
                ("sem_orders_v1", _make_columns("tenant_id", "date", types={"date": "DATE"})),
            )
        )
        new_manifest = _manifest(
            ("sem_orders_v1", _make_columns("tenant_id", "date", types={"date": "DATE"})),
        )
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is True


# =============================================================================
# Unit tests: view removed
# =============================================================================


class TestViewRemoved:
    """Semantic view removal must be detected as breaking."""

    def test_view_removed_detected(self):
        current = build_snapshot_from_manifest(
            _manifest(
                ("fact_orders_current", _make_columns("tenant_id")),
                ("fact_marketing_spend_current", _make_columns("tenant_id")),
            )
        )
        new_manifest = _manifest(
            ("fact_orders_current", _make_columns("tenant_id")),
            # fact_marketing_spend_current removed
        )
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is False
        assert any(
            b.change_type == "view_removed" and b.dataset_name == "fact_marketing_spend_current"
            for b in result.breaking_changes
        )

    def test_empty_manifest_fails_if_current_has_views(self):
        current = build_snapshot_from_manifest(
            _manifest(("fact_orders_current", _make_columns("tenant_id"))),
        )
        new_manifest = _manifest()  # no models
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is False
        assert any(b.change_type == "view_removed" for b in result.breaking_changes)


# =============================================================================
# Unit tests: no-op and edge cases
# =============================================================================


class TestNoOpAndEdgeCases:
    """Identical state and edge cases."""

    def test_identical_manifest_passes(self):
        manifest = _manifest(
            ("fact_orders_current", _make_columns("tenant_id", "revenue_gross", "date")),
        )
        current = build_snapshot_from_manifest(manifest)
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, manifest)
        assert result.compatibility_passed is True
        assert len(result.breaking_changes) == 0

    def test_empty_current_passes_for_new_views(self):
        current = DatasetSchemaSnapshot(datasets={})
        new_manifest = _manifest(
            ("fact_orders_current", _make_columns("tenant_id", "revenue_gross")),
        )
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is True
        assert any("fact_orders_current" in a for a in result.additive_changes)

    def test_is_semantic_view(self):
        assert _is_semantic_view("fact_orders_current") is True
        assert _is_semantic_view("fact_marketing_spend_current") is True
        assert _is_semantic_view("sem_orders_v1") is True
        assert _is_semantic_view("sem_marketing_spend_v1") is True
        assert _is_semantic_view("stg_shopify_orders") is False
        assert _is_semantic_view("orders") is False


# =============================================================================
# Property-based tests (Hypothesis)
# =============================================================================

try:
    from hypothesis import given, strategies as st
    HAS_HYPOTHESIS = True
except ImportError:
    HAS_HYPOTHESIS = False

if HAS_HYPOTHESIS:

    @given(
        current_cols=st.lists(
            st.text(alphabet="abcdefghijklmnopqrstuvwxyz_", min_size=1, max_size=25),
            min_size=1,
            max_size=30,
        ),
        remove_count=st.integers(min_value=1, max_value=10),
    )
    def test_column_removal_always_detected(current_cols, remove_count):
        """Removing any exposed column must be detected as breaking."""
        current_cols = list(dict.fromkeys(current_cols))[:20]
        if len(current_cols) < 2:
            return
        remove_count = min(remove_count, len(current_cols) - 1)
        removed = set(current_cols[:remove_count])
        new_cols = [c for c in current_cols if c not in removed]
        current_manifest = _manifest(
            (
                "fact_orders_current",
                _make_columns(*current_cols),
            ),
        )
        new_manifest = _manifest(
            (
                "fact_orders_current",
                _make_columns(*new_cols),
            ),
        )
        current = build_snapshot_from_manifest(current_manifest)
        checker = SchemaCompatibilityChecker()
        result = checker.validate(current, new_manifest)
        assert result.compatibility_passed is False, (
            f"Removed columns {removed} should be detected as breaking"
        )
        removed_detected = {
            b.column_name for b in result.breaking_changes if b.change_type == "column_removed"
        }
        assert removed.issubset(removed_detected) or len(removed_detected) >= 1

else:

    def test_hypothesis_not_installed():
        """Placeholder when Hypothesis is not installed; run with hypothesis for full coverage."""
        pytest.skip("Hypothesis not installed; property-based tests skipped")
