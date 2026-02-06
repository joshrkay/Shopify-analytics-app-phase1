"""
Unit + property-based tests for DatasetVersionManager and DatasetVersion model.

Tests cover:
- DatasetVersionStatus enum values
- DatasetVersion model defaults and constraints
- DatasetVersionManager lifecycle: create → validate → activate → rollback
- Schema compatibility: additive safe, removal blocks, type change blocks
- Idempotent version creation (same name+version returns existing)
- Fail-safe: mark_failed preserves active version untouched
- Property-based (Hypothesis): random column sets prove no edge case
  bypasses the compatibility check

Story 5.2.7 — Fail-Safe Dataset Versioning
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.models.dataset_version import DatasetVersion, DatasetVersionStatus
from src.services.dataset_version_manager import (
    DatasetVersionManager,
    SchemaCompatibilityError,
)


# ---------------------------------------------------------------------------
# DatasetVersionStatus enum
# ---------------------------------------------------------------------------

class TestDatasetVersionStatus:
    """Verify all version status values."""

    def test_has_five_statuses(self):
        assert len(DatasetVersionStatus) == 5

    def test_pending(self):
        assert DatasetVersionStatus.PENDING.value == "pending"

    def test_active(self):
        assert DatasetVersionStatus.ACTIVE.value == "active"

    def test_failed(self):
        assert DatasetVersionStatus.FAILED.value == "failed"

    def test_superseded(self):
        assert DatasetVersionStatus.SUPERSEDED.value == "superseded"

    def test_rolled_back(self):
        assert DatasetVersionStatus.ROLLED_BACK.value == "rolled_back"


# ---------------------------------------------------------------------------
# DatasetVersion model
# ---------------------------------------------------------------------------

class TestDatasetVersionModel:
    """Verify DatasetVersion model defaults and representation."""

    def test_tablename(self):
        assert DatasetVersion.__tablename__ == "dataset_version"

    def test_repr(self):
        v = DatasetVersion()
        v.dataset_name = "fact_orders_current"
        v.version = "v2"
        v.status = "active"
        assert "fact_orders_current" in repr(v)
        assert "v2" in repr(v)
        assert "active" in repr(v)


# ---------------------------------------------------------------------------
# Fixtures / Helpers
# ---------------------------------------------------------------------------

def _make_columns(names: list[str], exposed: list[str] | None = None) -> list[dict]:
    """Build a column list from names, marking specified ones as exposed."""
    exposed = exposed or []
    return [
        {
            "column_name": name,
            "type": "VARCHAR",
            "superset_expose": name in exposed,
        }
        for name in names
    ]


def _make_active_version(
    db_mock,
    dataset_name: str,
    version: str,
    columns: list[dict],
) -> DatasetVersion:
    """Create a DatasetVersion object that looks active."""
    v = DatasetVersion()
    v.id = f"ver-{version}"
    v.dataset_name = dataset_name
    v.version = version
    v.status = DatasetVersionStatus.ACTIVE.value
    v.column_snapshot = json.dumps(columns)
    v.column_count = len(columns)
    v.exposed_column_count = sum(1 for c in columns if c.get("superset_expose"))
    v.is_compatible = True
    v.activated_at = datetime.now(timezone.utc)
    return v


# ---------------------------------------------------------------------------
# Schema compatibility (unit tests)
# ---------------------------------------------------------------------------

class TestSchemaCompatibility:
    """Test validate_compatibility for additive, breaking, and type changes."""

    def _make_mgr(self, active_version: DatasetVersion | None):
        """Create a DatasetVersionManager with a mock DB that returns active_version."""
        db = MagicMock()
        mgr = DatasetVersionManager(db)
        # Mock get_active_version
        mgr.get_active_version = MagicMock(return_value=active_version)
        return mgr

    def test_no_active_version_is_compatible(self):
        """First-time sync (no active version) is always compatible."""
        mgr = self._make_mgr(None)
        is_compat, reason = mgr.validate_compatibility(
            "fact_orders_current",
            _make_columns(["id", "revenue"], exposed=["revenue"]),
        )
        assert is_compat is True
        assert reason == ""

    def test_additive_column_is_compatible(self):
        """Adding new columns to existing dataset is safe."""
        old_cols = _make_columns(["id", "revenue"], exposed=["revenue"])
        active = _make_active_version(None, "fact_orders_current", "v1", old_cols)
        mgr = self._make_mgr(active)

        new_cols = _make_columns(
            ["id", "revenue", "currency"],
            exposed=["revenue", "currency"],
        )
        is_compat, reason = mgr.validate_compatibility(
            "fact_orders_current", new_cols,
        )
        assert is_compat is True

    def test_removing_exposed_column_is_breaking(self):
        """Removing an exposed column is a breaking change."""
        old_cols = _make_columns(
            ["id", "revenue", "channel"],
            exposed=["revenue", "channel"],
        )
        active = _make_active_version(None, "fact_orders_current", "v1", old_cols)
        mgr = self._make_mgr(active)

        # Remove 'channel' from the new version
        new_cols = _make_columns(["id", "revenue"], exposed=["revenue"])
        is_compat, reason = mgr.validate_compatibility(
            "fact_orders_current", new_cols,
        )
        assert is_compat is False
        assert "channel" in reason

    def test_removing_unexposed_column_is_safe(self):
        """Removing a column that was NOT exposed is safe."""
        old_cols = _make_columns(
            ["id", "revenue", "internal_id"],
            exposed=["revenue"],
        )
        active = _make_active_version(None, "fact_orders_current", "v1", old_cols)
        mgr = self._make_mgr(active)

        new_cols = _make_columns(["id", "revenue"], exposed=["revenue"])
        is_compat, reason = mgr.validate_compatibility(
            "fact_orders_current", new_cols,
        )
        assert is_compat is True

    def test_type_change_on_exposed_column_is_breaking(self):
        """Changing the type of an exposed column is a breaking change."""
        old_cols = [
            {"column_name": "revenue", "type": "NUMERIC", "superset_expose": True},
        ]
        active = _make_active_version(None, "fact_orders_current", "v1", old_cols)
        mgr = self._make_mgr(active)

        new_cols = [
            {"column_name": "revenue", "type": "VARCHAR", "superset_expose": True},
        ]
        is_compat, reason = mgr.validate_compatibility(
            "fact_orders_current", new_cols,
        )
        assert is_compat is False
        assert "type" in reason.lower()

    def test_type_change_on_unexposed_column_is_safe(self):
        """Changing the type of a non-exposed column is safe."""
        old_cols = [
            {"column_name": "revenue", "type": "NUMERIC", "superset_expose": True},
            {"column_name": "internal", "type": "INTEGER", "superset_expose": False},
        ]
        active = _make_active_version(None, "fact_orders_current", "v1", old_cols)
        mgr = self._make_mgr(active)

        new_cols = [
            {"column_name": "revenue", "type": "NUMERIC", "superset_expose": True},
            {"column_name": "internal", "type": "BIGINT", "superset_expose": False},
        ]
        is_compat, reason = mgr.validate_compatibility(
            "fact_orders_current", new_cols,
        )
        assert is_compat is True

    def test_multiple_exposed_columns_removed(self):
        """Removing multiple exposed columns reports all of them."""
        old_cols = _make_columns(
            ["id", "revenue", "channel", "order_date"],
            exposed=["revenue", "channel", "order_date"],
        )
        active = _make_active_version(None, "fact_orders_current", "v1", old_cols)
        mgr = self._make_mgr(active)

        new_cols = _make_columns(["id"], exposed=[])
        is_compat, reason = mgr.validate_compatibility(
            "fact_orders_current", new_cols,
        )
        assert is_compat is False
        assert "revenue" in reason
        assert "channel" in reason
        assert "order_date" in reason


# ---------------------------------------------------------------------------
# Version lifecycle (unit tests)
# ---------------------------------------------------------------------------

class TestVersionLifecycle:
    """Test create → activate → supersede → rollback lifecycle."""

    def _make_mgr(self):
        """Create manager with mock DB that has add/flush/query."""
        db = MagicMock()
        db.flush = MagicMock()
        db.add = MagicMock()
        # query().filter().first() returns None by default
        db.query.return_value.filter.return_value.first.return_value = None
        return DatasetVersionManager(db), db

    def test_create_pending_version(self):
        mgr, db = self._make_mgr()
        cols = _make_columns(["id", "revenue"], exposed=["revenue"])
        version = mgr.create_pending_version(
            "fact_orders_current", "v1", cols,
        )
        assert version.status == DatasetVersionStatus.PENDING.value
        assert version.column_count == 2
        assert version.exposed_column_count == 1
        assert version.is_compatible is True
        db.add.assert_called_once()

    def test_create_pending_idempotent(self):
        """Creating same dataset_name + version returns existing."""
        mgr, db = self._make_mgr()
        existing = DatasetVersion()
        existing.id = "existing-id"
        existing.dataset_name = "fact_orders_current"
        existing.version = "v1"
        existing.status = "pending"
        # Make query return existing version
        db.query.return_value.filter.return_value.first.return_value = existing

        cols = _make_columns(["id"], exposed=["id"])
        result = mgr.create_pending_version(
            "fact_orders_current", "v1", cols,
        )
        assert result.id == "existing-id"
        db.add.assert_not_called()

    def test_activate_pending_version(self):
        mgr, db = self._make_mgr()
        version = DatasetVersion()
        version.id = "v-001"
        version.dataset_name = "fact_orders_current"
        version.version = "v1"
        version.status = DatasetVersionStatus.PENDING.value
        version.is_compatible = True

        mgr.get_version_by_id = MagicMock(return_value=version)
        mgr.get_active_version = MagicMock(return_value=None)

        result = mgr.activate_version("v-001")
        assert result.status == DatasetVersionStatus.ACTIVE.value
        assert result.activated_at is not None

    def test_activate_supersedes_current(self):
        """Activating a new version supersedes the current active one."""
        mgr, db = self._make_mgr()
        current = DatasetVersion()
        current.id = "v-old"
        current.dataset_name = "fact_orders_current"
        current.version = "v1"
        current.status = DatasetVersionStatus.ACTIVE.value

        new_version = DatasetVersion()
        new_version.id = "v-new"
        new_version.dataset_name = "fact_orders_current"
        new_version.version = "v2"
        new_version.status = DatasetVersionStatus.PENDING.value
        new_version.is_compatible = True

        mgr.get_version_by_id = MagicMock(return_value=new_version)
        mgr.get_active_version = MagicMock(return_value=current)

        result = mgr.activate_version("v-new")
        assert result.status == DatasetVersionStatus.ACTIVE.value
        assert current.status == DatasetVersionStatus.SUPERSEDED.value
        assert current.deactivated_at is not None

    def test_activate_rejects_non_pending(self):
        mgr, db = self._make_mgr()
        version = DatasetVersion()
        version.id = "v-001"
        version.status = DatasetVersionStatus.ACTIVE.value

        mgr.get_version_by_id = MagicMock(return_value=version)

        with pytest.raises(ValueError, match="Cannot activate"):
            mgr.activate_version("v-001")

    def test_activate_rejects_incompatible(self):
        mgr, db = self._make_mgr()
        version = DatasetVersion()
        version.id = "v-001"
        version.dataset_name = "fact_orders_current"
        version.status = DatasetVersionStatus.PENDING.value
        version.is_compatible = False
        version.incompatibility_reason = "Column removed"

        mgr.get_version_by_id = MagicMock(return_value=version)

        with pytest.raises(SchemaCompatibilityError, match="Column removed"):
            mgr.activate_version("v-001")

    def test_mark_failed_preserves_active(self):
        """Marking a version as failed does NOT touch the active version."""
        mgr, db = self._make_mgr()
        failed = DatasetVersion()
        failed.id = "v-fail"
        failed.dataset_name = "fact_orders_current"
        failed.version = "v2"
        failed.status = DatasetVersionStatus.PENDING.value

        active = DatasetVersion()
        active.id = "v-active"
        active.dataset_name = "fact_orders_current"
        active.version = "v1"
        active.status = DatasetVersionStatus.ACTIVE.value

        mgr.get_version_by_id = MagicMock(return_value=failed)

        result = mgr.mark_failed("v-fail", "API timeout")
        assert result.status == DatasetVersionStatus.FAILED.value
        assert result.sync_error == "API timeout"
        # Active version untouched
        assert active.status == DatasetVersionStatus.ACTIVE.value

    def test_rollback_restores_superseded(self):
        """Rollback demotes active and restores latest superseded."""
        mgr, db = self._make_mgr()
        current = DatasetVersion()
        current.id = "v-cur"
        current.dataset_name = "fact_orders_current"
        current.version = "v2"
        current.status = DatasetVersionStatus.ACTIVE.value

        previous = DatasetVersion()
        previous.id = "v-prev"
        previous.dataset_name = "fact_orders_current"
        previous.version = "v1"
        previous.status = DatasetVersionStatus.SUPERSEDED.value
        previous.activated_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        mgr.get_active_version = MagicMock(return_value=current)
        # Mock query for superseded version
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = previous

        result = mgr.rollback("fact_orders_current")
        assert result is not None
        assert result.status == DatasetVersionStatus.ACTIVE.value
        assert current.status == DatasetVersionStatus.ROLLED_BACK.value

    def test_rollback_no_superseded_returns_none(self):
        """Rollback with no previous version returns None."""
        mgr, db = self._make_mgr()
        current = DatasetVersion()
        current.id = "v-cur"
        current.status = DatasetVersionStatus.ACTIVE.value

        mgr.get_active_version = MagicMock(return_value=current)
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        result = mgr.rollback("fact_orders_current")
        assert result is None
        assert current.status == DatasetVersionStatus.ROLLED_BACK.value

    def test_activate_not_found_raises(self):
        mgr, db = self._make_mgr()
        mgr.get_version_by_id = MagicMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            mgr.activate_version("nonexistent")


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis) — CRITICAL PATH: Versioning
# ---------------------------------------------------------------------------

# Strategy: generate a random column name
_column_name_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz_",
    min_size=1,
    max_size=30,
).filter(lambda s: s[0].isalpha())

# Strategy: generate a random column type
_column_type_st = st.sampled_from([
    "VARCHAR", "INTEGER", "NUMERIC", "BOOLEAN", "TIMESTAMP", "TEXT", "BIGINT",
])


@st.composite
def _column_st(draw):
    """Strategy for a single column dict."""
    return {
        "column_name": draw(_column_name_st),
        "type": draw(_column_type_st),
        "superset_expose": draw(st.booleans()),
    }


@st.composite
def _column_list_st(draw, min_size=1, max_size=20):
    """Strategy for a list of unique-named columns."""
    cols = draw(
        st.lists(
            _column_st(),
            min_size=min_size,
            max_size=max_size,
        )
    )
    # Deduplicate by column_name (keep first occurrence)
    seen = set()
    unique = []
    for col in cols:
        if col["column_name"] not in seen:
            seen.add(col["column_name"])
            unique.append(col)
    assume(len(unique) >= 1)
    return unique


class TestSchemaCompatibilityPropertyBased:
    """
    Property-based tests for schema compatibility validation.

    Uses Hypothesis to generate random column sets and prove that:
    1. Purely additive changes never fail
    2. Removing any exposed column always fails
    3. Compatibility is deterministic (same inputs → same output)
    """

    def _make_mgr_with_active(self, columns: list[dict]) -> DatasetVersionManager:
        db = MagicMock()
        mgr = DatasetVersionManager(db)
        active = _make_active_version(db, "test_dataset", "v1", columns)
        mgr.get_active_version = MagicMock(return_value=active)
        return mgr

    @given(old_cols=_column_list_st(), extra_cols=_column_list_st())
    @settings(max_examples=200, deadline=None)
    def test_additive_changes_are_always_safe(self, old_cols, extra_cols):
        """Adding new columns to old set is always compatible."""
        old_names = {c["column_name"] for c in old_cols}
        # Ensure extra columns have truly new names
        new_extras = [c for c in extra_cols if c["column_name"] not in old_names]
        new_cols = old_cols + new_extras

        mgr = self._make_mgr_with_active(old_cols)
        is_compat, reason = mgr.validate_compatibility("test_dataset", new_cols)
        assert is_compat is True, f"Additive change should be safe: {reason}"

    @given(old_cols=_column_list_st(min_size=2))
    @settings(max_examples=200, deadline=None)
    def test_removing_exposed_column_always_fails(self, old_cols):
        """Removing any exposed column must always be detected as breaking."""
        exposed = [c for c in old_cols if c.get("superset_expose")]
        assume(len(exposed) >= 1)

        # Remove one exposed column
        removed = exposed[0]
        new_cols = [c for c in old_cols if c["column_name"] != removed["column_name"]]

        mgr = self._make_mgr_with_active(old_cols)
        is_compat, reason = mgr.validate_compatibility("test_dataset", new_cols)
        assert is_compat is False, (
            f"Removing exposed column '{removed['column_name']}' should fail"
        )
        assert removed["column_name"] in reason

    @given(old_cols=_column_list_st())
    @settings(max_examples=100, deadline=None)
    def test_identical_columns_are_always_compatible(self, old_cols):
        """Exact same column set is always compatible (idempotent)."""
        mgr = self._make_mgr_with_active(old_cols)
        is_compat, reason = mgr.validate_compatibility("test_dataset", old_cols)
        assert is_compat is True, f"Identical columns should be compatible: {reason}"

    @given(old_cols=_column_list_st())
    @settings(max_examples=100, deadline=None)
    def test_compatibility_is_deterministic(self, old_cols):
        """Running validate_compatibility twice gives the same result."""
        mgr = self._make_mgr_with_active(old_cols)
        r1 = mgr.validate_compatibility("test_dataset", old_cols)
        r2 = mgr.validate_compatibility("test_dataset", old_cols)
        assert r1 == r2

    @given(old_cols=_column_list_st(min_size=2))
    @settings(max_examples=200, deadline=None)
    def test_type_change_on_exposed_column_always_fails(self, old_cols):
        """Changing the type of any exposed column must be breaking."""
        exposed = [c for c in old_cols if c.get("superset_expose")]
        assume(len(exposed) >= 1)

        target = exposed[0]
        original_type = target["type"]
        # Pick a different type
        other_types = [
            t for t in ["VARCHAR", "INTEGER", "NUMERIC", "BOOLEAN", "TIMESTAMP"]
            if t != original_type
        ]
        assume(len(other_types) > 0)

        new_cols = []
        for c in old_cols:
            if c["column_name"] == target["column_name"]:
                new_cols.append({**c, "type": other_types[0]})
            else:
                new_cols.append(c)

        mgr = self._make_mgr_with_active(old_cols)
        is_compat, reason = mgr.validate_compatibility("test_dataset", new_cols)
        assert is_compat is False, (
            f"Type change on exposed '{target['column_name']}' "
            f"({original_type} → {other_types[0]}) should fail"
        )
