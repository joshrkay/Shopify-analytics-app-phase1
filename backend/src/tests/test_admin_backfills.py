"""
Tests for Story 3.4 - Admin Backfill Request API.

Tests:
- Idempotency key computation
- Backfill validator (tenant, date range, overlap, idempotency)
- Pydantic schema validation
- Source system enum
- Security: super admin authorization

Run with: pytest src/tests/test_admin_backfills.py -v
"""

import hashlib
import pytest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from src.api.schemas.backfill_request import (
    CreateBackfillRequest,
    SourceSystem,
    BackfillRequestResponse,
    BackfillRequestCreatedResponse,
)
from src.services.backfill_validator import (
    BackfillValidator,
    compute_idempotency_key,
    TenantNotFoundError,
    TenantNotActiveError,
    DateRangeExceededError,
    OverlappingBackfillError,
    TIER_MAX_BACKFILL_DAYS,
    DEFAULT_MAX_BACKFILL_DAYS,
)
from src.models.historical_backfill import (
    HistoricalBackfillRequest,
    HistoricalBackfillStatus,
    ACTIVE_BACKFILL_STATUSES,
)


# =============================================================================
# Idempotency Key Tests
# =============================================================================


class TestIdempotencyKey:
    """Tests for compute_idempotency_key."""

    def test_same_inputs_produce_same_key(self):
        key1 = compute_idempotency_key("t1", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        key2 = compute_idempotency_key("t1", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        assert key1 == key2

    def test_different_tenant_produces_different_key(self):
        key1 = compute_idempotency_key("t1", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        key2 = compute_idempotency_key("t2", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        assert key1 != key2

    def test_different_source_produces_different_key(self):
        key1 = compute_idempotency_key("t1", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        key2 = compute_idempotency_key("t1", "facebook", date(2024, 1, 1), date(2024, 3, 31))
        assert key1 != key2

    def test_different_dates_produce_different_key(self):
        key1 = compute_idempotency_key("t1", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        key2 = compute_idempotency_key("t1", "shopify", date(2024, 1, 2), date(2024, 3, 31))
        assert key1 != key2

    def test_key_is_sha256_hex(self):
        key = compute_idempotency_key("t1", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        assert len(key) == 64  # SHA-256 hex digest length
        int(key, 16)  # Should parse as hex

    def test_key_matches_expected_hash(self):
        canonical = "t1|shopify|2024-01-01|2024-03-31"
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        actual = compute_idempotency_key("t1", "shopify", date(2024, 1, 1), date(2024, 3, 31))
        assert actual == expected


# =============================================================================
# Source System Enum Tests
# =============================================================================


class TestSourceSystemEnum:
    """Tests for SourceSystem enum."""

    def test_all_expected_sources_exist(self):
        expected = {
            "shopify", "facebook", "google", "tiktok",
            "pinterest", "snapchat", "amazon", "klaviyo",
            "recharge", "ga4",
        }
        actual = {s.value for s in SourceSystem}
        assert actual == expected

    def test_values_are_lowercase(self):
        for source in SourceSystem:
            assert source.value == source.value.lower()


# =============================================================================
# Schema Validation Tests
# =============================================================================


class TestCreateBackfillRequestSchema:
    """Tests for Pydantic schema validation."""

    def test_valid_request_accepted(self):
        req = CreateBackfillRequest(
            tenant_id="tenant_123",
            source_system=SourceSystem.SHOPIFY,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            reason="Data gap after connector migration on 2024-01-15",
        )
        assert req.tenant_id == "tenant_123"
        assert req.source_system == SourceSystem.SHOPIFY
        assert req.start_date == date(2024, 1, 1)
        assert req.end_date == date(2024, 3, 31)

    def test_start_after_end_rejected(self):
        with pytest.raises(ValueError, match="start_date.*must be before"):
            CreateBackfillRequest(
                tenant_id="tenant_123",
                source_system=SourceSystem.SHOPIFY,
                start_date=date(2024, 3, 31),
                end_date=date(2024, 1, 1),
                reason="This should fail because dates are reversed",
            )

    def test_future_end_date_rejected(self):
        future = date.today() + timedelta(days=30)
        with pytest.raises(ValueError, match="end_date cannot be in the future"):
            CreateBackfillRequest(
                tenant_id="tenant_123",
                source_system=SourceSystem.SHOPIFY,
                start_date=date(2024, 1, 1),
                end_date=future,
                reason="This should fail because end date is in the future",
            )

    def test_reason_too_short_rejected(self):
        with pytest.raises(ValueError):
            CreateBackfillRequest(
                tenant_id="tenant_123",
                source_system=SourceSystem.SHOPIFY,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 3, 31),
                reason="Short",  # min_length=10
            )

    def test_empty_tenant_id_rejected(self):
        with pytest.raises(ValueError):
            CreateBackfillRequest(
                tenant_id="",
                source_system=SourceSystem.SHOPIFY,
                start_date=date(2024, 1, 1),
                end_date=date(2024, 3, 31),
                reason="Valid reason for backfill request",
            )

    def test_invalid_source_system_rejected(self):
        with pytest.raises(ValueError):
            CreateBackfillRequest(
                tenant_id="tenant_123",
                source_system="invalid_source",
                start_date=date(2024, 1, 1),
                end_date=date(2024, 3, 31),
                reason="Valid reason for backfill request",
            )

    def test_same_start_and_end_date_accepted(self):
        """Single-day backfill is valid."""
        req = CreateBackfillRequest(
            tenant_id="tenant_123",
            source_system=SourceSystem.SHOPIFY,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 1),
            reason="Single day reprocess after bug fix",
        )
        assert req.start_date == req.end_date


# =============================================================================
# Backfill Validator - Tenant Tests
# =============================================================================


def _mock_tenant(tenant_id="tenant_123", status="active", billing_tier="free"):
    """Create a mock tenant object."""
    from src.models.tenant import TenantStatus
    tenant = MagicMock()
    tenant.id = tenant_id
    tenant.status = TenantStatus(status)
    tenant.billing_tier = billing_tier
    return tenant


class TestBackfillValidatorTenant:
    """Tests for tenant validation."""

    def test_valid_active_tenant_passes(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = (
            _mock_tenant()
        )

        validator = BackfillValidator(mock_db)
        tenant = validator.validate_tenant("tenant_123")
        assert tenant.id == "tenant_123"

    def test_nonexistent_tenant_raises_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        validator = BackfillValidator(mock_db)
        with pytest.raises(TenantNotFoundError, match="not found"):
            validator.validate_tenant("nonexistent")

    def test_suspended_tenant_raises_not_active(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = (
            _mock_tenant(status="suspended")
        )

        validator = BackfillValidator(mock_db)
        with pytest.raises(TenantNotActiveError, match="not active"):
            validator.validate_tenant("tenant_123")

    def test_deactivated_tenant_raises_not_active(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = (
            _mock_tenant(status="deactivated")
        )

        validator = BackfillValidator(mock_db)
        with pytest.raises(TenantNotActiveError, match="not active"):
            validator.validate_tenant("tenant_123")


# =============================================================================
# Backfill Validator - Date Range Tests
# =============================================================================


class TestBackfillValidatorDateRange:
    """Tests for date range validation against billing tier limits."""

    def test_free_tier_90_day_limit_passes(self):
        validator = BackfillValidator(MagicMock())
        days = validator.validate_date_range(
            date(2024, 1, 1), date(2024, 3, 30), "free"  # 90 days
        )
        assert days == 90

    def test_free_tier_91_day_limit_fails(self):
        validator = BackfillValidator(MagicMock())
        with pytest.raises(DateRangeExceededError, match="91 days.*90 days.*free"):
            validator.validate_date_range(
                date(2024, 1, 1), date(2024, 3, 31), "free"  # 91 days
            )

    def test_growth_tier_90_day_limit_passes(self):
        validator = BackfillValidator(MagicMock())
        days = validator.validate_date_range(
            date(2024, 1, 1), date(2024, 3, 30), "growth"
        )
        assert days == 90

    def test_growth_tier_91_day_limit_fails(self):
        validator = BackfillValidator(MagicMock())
        with pytest.raises(DateRangeExceededError, match="growth"):
            validator.validate_date_range(
                date(2024, 1, 1), date(2024, 3, 31), "growth"
            )

    def test_enterprise_tier_365_days_passes(self):
        validator = BackfillValidator(MagicMock())
        # 365 days: Jan 1 to Dec 30 (non-leap year logic)
        days = validator.validate_date_range(
            date(2023, 1, 1), date(2023, 12, 31), "enterprise"  # 365 days exactly
        )
        assert days == 365

    def test_enterprise_tier_366_day_fails(self):
        validator = BackfillValidator(MagicMock())
        with pytest.raises(DateRangeExceededError, match="enterprise"):
            # 366 days in 2024 (leap year)
            validator.validate_date_range(
                date(2024, 1, 1), date(2024, 12, 31), "enterprise"
            )

    def test_unknown_tier_uses_default_90_days(self):
        validator = BackfillValidator(MagicMock())
        with pytest.raises(DateRangeExceededError, match="91 days.*90 days"):
            validator.validate_date_range(
                date(2024, 1, 1), date(2024, 3, 31), "unknown_tier"
            )

    def test_single_day_backfill_passes(self):
        validator = BackfillValidator(MagicMock())
        days = validator.validate_date_range(
            date(2024, 1, 1), date(2024, 1, 1), "free"
        )
        assert days == 1

    def test_tier_constants_are_correct(self):
        assert TIER_MAX_BACKFILL_DAYS["free"] == 90
        assert TIER_MAX_BACKFILL_DAYS["growth"] == 90
        assert TIER_MAX_BACKFILL_DAYS["enterprise"] == 365
        assert DEFAULT_MAX_BACKFILL_DAYS == 90


# =============================================================================
# Backfill Validator - Overlap Tests
# =============================================================================


class TestBackfillValidatorOverlap:
    """Tests for overlapping backfill detection."""

    def test_no_active_backfills_passes(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        validator = BackfillValidator(mock_db)
        # Should not raise
        validator.check_overlapping_backfills(
            "tenant_123", "shopify", date(2024, 1, 1), date(2024, 3, 31)
        )

    def test_overlapping_active_backfill_raises(self):
        existing = MagicMock()
        existing.id = "existing_backfill_id"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        validator = BackfillValidator(mock_db)
        with pytest.raises(OverlappingBackfillError, match="existing_backfill_id"):
            validator.check_overlapping_backfills(
                "tenant_123", "shopify", date(2024, 1, 1), date(2024, 3, 31)
            )


# =============================================================================
# Backfill Validator - Full Pipeline Tests
# =============================================================================


class TestBackfillValidatorPipeline:
    """Tests for the full validate_and_prepare pipeline."""

    def test_first_request_returns_none_and_true(self):
        mock_db = MagicMock()
        # find_idempotent_match returns None (no existing)
        # validate_tenant returns active tenant
        # check_overlapping returns None

        mock_tenant = _mock_tenant(billing_tier="free")

        # Setup chain: idempotent check returns None, tenant check returns tenant, overlap returns None
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            None,           # find_idempotent_match
            mock_tenant,    # validate_tenant
            None,           # check_overlapping_backfills
        ]

        validator = BackfillValidator(mock_db)
        existing, is_new = validator.validate_and_prepare(
            "tenant_123", "shopify", date(2024, 1, 1), date(2024, 3, 30)
        )
        assert existing is None
        assert is_new is True

    def test_idempotent_match_returns_existing_and_false(self):
        existing_request = MagicMock()
        existing_request.id = "existing_id"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = (
            existing_request
        )

        validator = BackfillValidator(mock_db)
        result, is_new = validator.validate_and_prepare(
            "tenant_123", "shopify", date(2024, 1, 1), date(2024, 3, 31)
        )
        assert result is existing_request
        assert is_new is False


# =============================================================================
# Model Tests
# =============================================================================


class TestHistoricalBackfillModel:
    """Tests for the HistoricalBackfillRequest model."""

    def test_status_enum_values(self):
        expected = {"pending", "approved", "running", "completed", "failed", "cancelled", "rejected"}
        actual = {s.value for s in HistoricalBackfillStatus}
        assert actual == expected

    def test_active_statuses_are_correct(self):
        active_values = {s.value for s in ACTIVE_BACKFILL_STATUSES}
        assert active_values == {"pending", "approved", "running"}

    def test_model_defaults(self):
        record = HistoricalBackfillRequest(
            tenant_id="tenant_123",
            source_system="shopify",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            reason="Test backfill",
            requested_by="admin_user",
            idempotency_key="test_key",
        )
        assert record.tenant_id == "tenant_123"
        assert record.source_system == "shopify"
        assert record.started_at is None
        assert record.completed_at is None
        assert record.error_message is None

    def test_model_repr(self):
        record = HistoricalBackfillRequest(
            id="test_id",
            tenant_id="tenant_123",
            source_system="shopify",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            status=HistoricalBackfillStatus.PENDING,
            reason="Test",
            requested_by="admin",
            idempotency_key="key",
        )
        repr_str = repr(record)
        assert "test_id" in repr_str
        assert "tenant_123" in repr_str
        assert "shopify" in repr_str


# =============================================================================
# Response Schema Tests
# =============================================================================


class TestBackfillResponseSchemas:
    """Tests for response Pydantic models."""

    def test_backfill_request_response(self):
        resp = BackfillRequestResponse(
            id="bf_123",
            tenant_id="tenant_123",
            source_system="shopify",
            start_date="2024-01-01",
            end_date="2024-03-31",
            status="pending",
            reason="Test reason for backfill",
            requested_by="admin_user",
            idempotency_key="abc123",
        )
        assert resp.id == "bf_123"
        assert resp.status == "pending"

    def test_backfill_created_response(self):
        inner = BackfillRequestResponse(
            id="bf_123",
            tenant_id="tenant_123",
            source_system="shopify",
            start_date="2024-01-01",
            end_date="2024-03-31",
            status="pending",
            reason="Test reason for backfill",
            requested_by="admin_user",
            idempotency_key="abc123",
        )
        resp = BackfillRequestCreatedResponse(
            backfill_request=inner,
            created=True,
            message="Backfill request created successfully",
        )
        assert resp.created is True
        assert resp.backfill_request.id == "bf_123"


# =============================================================================
# Security Tests
# =============================================================================


class TestSecurityConstraints:
    """Tests for security properties of the backfill system."""

    def test_validator_requires_active_tenant(self):
        """Backfills should be rejected for suspended tenants."""
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = (
            _mock_tenant(status="suspended")
        )
        validator = BackfillValidator(mock_db)
        with pytest.raises(TenantNotActiveError):
            validator.validate_tenant("tenant_123")

    def test_tier_limits_enforced(self):
        """Free tier should not allow > 90 days."""
        validator = BackfillValidator(MagicMock())
        with pytest.raises(DateRangeExceededError):
            validator.validate_date_range(
                date(2024, 1, 1), date(2024, 12, 31), "free"
            )

    def test_no_secrets_in_model(self):
        """Model should not expose sensitive fields."""
        record = HistoricalBackfillRequest(
            tenant_id="t", source_system="shopify",
            start_date=date(2024, 1, 1), end_date=date(2024, 1, 1),
            reason="test", requested_by="admin", idempotency_key="key",
        )
        assert not hasattr(record, "access_token")
        assert not hasattr(record, "api_key")
        assert not hasattr(record, "secret")

    def test_active_statuses_exclude_terminal_states(self):
        """Terminal states should not block new backfills."""
        terminal = {
            HistoricalBackfillStatus.COMPLETED,
            HistoricalBackfillStatus.FAILED,
            HistoricalBackfillStatus.CANCELLED,
            HistoricalBackfillStatus.REJECTED,
        }
        active_set = set(ACTIVE_BACKFILL_STATUSES)
        assert active_set.isdisjoint(terminal)


# =============================================================================
# Backfill Planner Tests
# =============================================================================


from src.services.backfill_planner import (
    BackfillPlanner,
    MODEL_REGISTRY,
    SOURCE_TO_STAGING,
    SOURCE_INGESTION_TABLES,
    ModelLayer,
    _DEPENDENTS,
)


class TestBackfillPlannerDependencyGraph:
    """Tests for the dependency graph resolution."""

    def test_shopify_resolves_full_downstream(self):
        planner = BackfillPlanner()
        affected = planner._resolve_downstream(["stg_shopify_orders"])
        # Must include the seed
        assert "stg_shopify_orders" in affected
        # Must include direct canonical dependents
        assert "orders" in affected
        assert "fact_orders_v1" in affected
        # Must include transitive dependents
        assert "fct_revenue" in affected
        assert "sem_orders_v1" in affected
        assert "fact_orders_current" in affected
        assert "last_click" in affected
        assert "fct_roas" in affected
        assert "mart_revenue_metrics" in affected

    def test_facebook_resolves_ads_downstream(self):
        planner = BackfillPlanner()
        affected = planner._resolve_downstream(["stg_facebook_ads_performance"])
        assert "marketing_spend" in affected
        assert "campaign_performance" in affected
        assert "sem_marketing_spend_v1" in affected
        assert "dim_ad_accounts" in affected
        assert "dim_campaigns" in affected
        # Should NOT include shopify-only models
        assert "stg_shopify_orders" not in affected

    def test_unknown_model_ignored(self):
        planner = BackfillPlanner()
        affected = planner._resolve_downstream(["nonexistent_model"])
        assert len(affected) == 0

    def test_empty_seeds_returns_empty(self):
        planner = BackfillPlanner()
        affected = planner._resolve_downstream([])
        assert len(affected) == 0

    def test_tiktok_only_affects_marketing_spend(self):
        """TikTok should affect marketing_spend but NOT campaign_performance."""
        planner = BackfillPlanner()
        affected = planner._resolve_downstream(["stg_tiktok_ads_performance"])
        assert "marketing_spend" in affected
        assert "fact_marketing_spend_v1" in affected
        # campaign_performance only depends on facebook + google
        assert "campaign_performance" not in affected


class TestBackfillPlannerPlan:
    """Tests for the full plan() method."""

    def test_shopify_plan_has_all_fields(self):
        planner = BackfillPlanner()
        plan = planner.plan(
            tenant_id="tenant_123",
            source_system="shopify",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        assert plan.tenant_id == "tenant_123"
        assert plan.source_system == "shopify"
        assert plan.start_date == date(2024, 1, 1)
        assert plan.end_date == date(2024, 1, 31)
        assert len(plan.ingestion_tables) > 0
        assert len(plan.affected_models) > 0
        assert len(plan.execution_steps) > 0
        assert plan.cost_estimate.date_range_days == 31
        assert plan.cost_estimate.estimated_raw_rows > 0
        assert plan.is_partial is True  # Shopify doesn't affect all models
        assert "dbt run" in plan.dbt_run_command
        assert "tenant_123" in plan.dbt_run_command

    def test_execution_steps_are_ordered_by_layer(self):
        planner = BackfillPlanner()
        plan = planner.plan(
            tenant_id="t1",
            source_system="shopify",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 7),
        )
        layer_orders = []
        for step in plan.execution_steps:
            layer = ModelLayer(step.layer)
            layer_orders.append(layer.order)
        # Must be monotonically non-decreasing
        assert layer_orders == sorted(layer_orders)

    def test_ingestion_tables_for_shopify(self):
        planner = BackfillPlanner()
        plan = planner.plan("t1", "shopify", date(2024, 1, 1), date(2024, 1, 7))
        assert "_airbyte_raw_shopify_orders" in plan.ingestion_tables
        assert "_airbyte_raw_shopify_customers" in plan.ingestion_tables

    def test_ingestion_tables_for_facebook(self):
        planner = BackfillPlanner()
        plan = planner.plan("t1", "facebook", date(2024, 1, 1), date(2024, 1, 7))
        assert "_airbyte_raw_meta_ads" in plan.ingestion_tables

    def test_unknown_source_returns_empty_plan(self):
        planner = BackfillPlanner()
        plan = planner.plan("t1", "nonexistent", date(2024, 1, 1), date(2024, 1, 7))
        assert plan.affected_models == []
        assert plan.ingestion_tables == []
        assert plan.execution_steps == []


class TestBackfillPlannerCostEstimate:
    """Tests for cost estimation."""

    def test_longer_range_costs_more(self):
        planner = BackfillPlanner()
        plan_7d = planner.plan("t1", "shopify", date(2024, 1, 1), date(2024, 1, 7))
        plan_30d = planner.plan("t1", "shopify", date(2024, 1, 1), date(2024, 1, 30))
        assert plan_30d.cost_estimate.estimated_raw_rows > plan_7d.cost_estimate.estimated_raw_rows
        assert plan_30d.cost_estimate.estimated_seconds > plan_7d.cost_estimate.estimated_seconds

    def test_single_day_cost(self):
        planner = BackfillPlanner()
        plan = planner.plan("t1", "shopify", date(2024, 1, 1), date(2024, 1, 1))
        assert plan.cost_estimate.date_range_days == 1
        assert plan.cost_estimate.estimated_raw_rows == 500  # shopify rows_per_day

    def test_cost_estimate_fields_positive(self):
        planner = BackfillPlanner()
        plan = planner.plan("t1", "facebook", date(2024, 1, 1), date(2024, 1, 31))
        assert plan.cost_estimate.estimated_raw_rows > 0
        assert plan.cost_estimate.estimated_total_rows >= plan.cost_estimate.estimated_raw_rows
        assert plan.cost_estimate.estimated_seconds >= 0


class TestBackfillPlannerRegistry:
    """Tests for the model registry and source mappings."""

    def test_all_source_systems_have_staging_mapping(self):
        """Every source in SourceSystem enum should have a staging mapping."""
        from src.api.schemas.backfill_request import SourceSystem
        for source in SourceSystem:
            assert source.value in SOURCE_TO_STAGING, (
                f"Missing SOURCE_TO_STAGING entry for {source.value}"
            )

    def test_all_source_systems_have_ingestion_mapping(self):
        from src.api.schemas.backfill_request import SourceSystem
        for source in SourceSystem:
            assert source.value in SOURCE_INGESTION_TABLES, (
                f"Missing SOURCE_INGESTION_TABLES entry for {source.value}"
            )

    def test_all_staging_models_exist_in_registry(self):
        """Every model referenced in SOURCE_TO_STAGING must be in MODEL_REGISTRY."""
        for source, models in SOURCE_TO_STAGING.items():
            for model_name in models:
                assert model_name in MODEL_REGISTRY, (
                    f"Staging model '{model_name}' for source '{source}' "
                    f"not found in MODEL_REGISTRY"
                )

    def test_all_depends_on_exist_in_registry(self):
        """Every dependency reference must point to an existing model."""
        for name, model in MODEL_REGISTRY.items():
            for dep in model.depends_on:
                assert dep in MODEL_REGISTRY, (
                    f"Model '{name}' depends on '{dep}' which is not in MODEL_REGISTRY"
                )

    def test_dependents_index_is_consistent(self):
        """The reverse index must be consistent with depends_on."""
        for name, model in MODEL_REGISTRY.items():
            for dep in model.depends_on:
                assert name in _DEPENDENTS.get(dep, set()), (
                    f"'{name}' depends on '{dep}' but is not in _DEPENDENTS['{dep}']"
                )

    def test_staging_models_have_no_internal_deps(self):
        """Staging models (except aggregations) should have no depends_on."""
        # stg_email_campaigns depends on stg_klaviyo_events — that's the exception
        exceptions = {"stg_email_campaigns", "dim_ad_accounts", "dim_campaigns"}
        for name, model in MODEL_REGISTRY.items():
            if model.layer == ModelLayer.STAGING and name not in exceptions:
                assert model.depends_on == (), (
                    f"Staging model '{name}' has unexpected deps: {model.depends_on}"
                )


# =============================================================================
# Backfill Executor Tests - Story 3.4.3
# =============================================================================


from src.services.backfill_executor import (
    BackfillExecutor,
    calculate_backoff,
    compute_chunks,
    CHUNK_SIZE_DAYS,
    BASE_RETRY_DELAY_SECONDS,
    MAX_RETRY_DELAY_SECONDS,
)
from src.models.backfill_job import (
    BackfillJob,
    BackfillJobStatus,
)


class TestComputeChunks:
    """Tests for date range chunking."""

    def test_single_day(self):
        chunks = compute_chunks(date(2024, 1, 1), date(2024, 1, 1))
        assert chunks == [(date(2024, 1, 1), date(2024, 1, 1))]

    def test_exact_chunk_size(self):
        """7-day range produces exactly one chunk."""
        chunks = compute_chunks(date(2024, 1, 1), date(2024, 1, 7))
        assert len(chunks) == 1
        assert chunks[0] == (date(2024, 1, 1), date(2024, 1, 7))

    def test_two_chunks(self):
        """8-day range produces two chunks: 7 + 1."""
        chunks = compute_chunks(date(2024, 1, 1), date(2024, 1, 8))
        assert len(chunks) == 2
        assert chunks[0] == (date(2024, 1, 1), date(2024, 1, 7))
        assert chunks[1] == (date(2024, 1, 8), date(2024, 1, 8))

    def test_14_days_produces_two_chunks(self):
        chunks = compute_chunks(date(2024, 1, 1), date(2024, 1, 14))
        assert len(chunks) == 2
        assert chunks[0] == (date(2024, 1, 1), date(2024, 1, 7))
        assert chunks[1] == (date(2024, 1, 8), date(2024, 1, 14))

    def test_90_days_produces_13_chunks(self):
        """90 days = 12 full weeks + 6 days = 13 chunks."""
        chunks = compute_chunks(date(2024, 1, 1), date(2024, 3, 30))
        assert len(chunks) == 13
        # First chunk
        assert chunks[0] == (date(2024, 1, 1), date(2024, 1, 7))
        # Last chunk
        assert chunks[-1][1] == date(2024, 3, 30)

    def test_chunks_are_contiguous(self):
        """No gaps or overlaps between chunks."""
        chunks = compute_chunks(date(2024, 1, 1), date(2024, 2, 15))
        for i in range(len(chunks) - 1):
            gap = (chunks[i + 1][0] - chunks[i][1]).days
            assert gap == 1, f"Gap between chunk {i} and {i+1}: {gap} days"

    def test_chunk_size_is_configurable(self):
        """All chunks except possibly the last are CHUNK_SIZE_DAYS long."""
        chunks = compute_chunks(date(2024, 1, 1), date(2024, 3, 30))
        for i, (start, end) in enumerate(chunks[:-1]):
            size = (end - start).days + 1
            assert size == CHUNK_SIZE_DAYS, (
                f"Chunk {i} is {size} days, expected {CHUNK_SIZE_DAYS}"
            )


class TestCalculateBackoff:
    """Tests for exponential backoff calculation."""

    def test_attempt_0_near_base_delay(self):
        delay = calculate_backoff(0)
        # base ± 25% jitter
        assert BASE_RETRY_DELAY_SECONDS * 0.5 <= delay <= BASE_RETRY_DELAY_SECONDS * 1.5

    def test_attempt_increases_delay(self):
        """Higher attempt = longer delay on average."""
        delays_0 = [calculate_backoff(0) for _ in range(50)]
        delays_3 = [calculate_backoff(3) for _ in range(50)]
        avg_0 = sum(delays_0) / len(delays_0)
        avg_3 = sum(delays_3) / len(delays_3)
        assert avg_3 > avg_0

    def test_delay_capped_at_max(self):
        delay = calculate_backoff(20)  # Very high attempt
        assert delay <= MAX_RETRY_DELAY_SECONDS

    def test_delay_always_positive(self):
        for attempt in range(10):
            assert calculate_backoff(attempt) >= 1.0


class TestBackfillJobModel:
    """Tests for BackfillJob model properties and lifecycle methods."""

    def _make_job(self, **kwargs):
        defaults = dict(
            id="job_1",
            backfill_request_id="req_1",
            tenant_id="tenant_1",
            source_system="shopify",
            chunk_start_date=date(2024, 1, 1),
            chunk_end_date=date(2024, 1, 7),
            chunk_index=0,
            status=BackfillJobStatus.QUEUED,
            attempt=0,
            max_retries=3,
        )
        defaults.update(kwargs)
        job = BackfillJob(**defaults)
        return job

    def test_is_active_for_queued(self):
        job = self._make_job(status=BackfillJobStatus.QUEUED)
        assert job.is_active is True

    def test_is_active_for_running(self):
        job = self._make_job(status=BackfillJobStatus.RUNNING)
        assert job.is_active is True

    def test_is_active_false_for_success(self):
        job = self._make_job(status=BackfillJobStatus.SUCCESS)
        assert job.is_active is False

    def test_is_terminal_for_success(self):
        job = self._make_job(status=BackfillJobStatus.SUCCESS)
        assert job.is_terminal is True

    def test_is_terminal_for_failed(self):
        job = self._make_job(status=BackfillJobStatus.FAILED)
        assert job.is_terminal is True

    def test_is_terminal_false_for_queued(self):
        job = self._make_job(status=BackfillJobStatus.QUEUED)
        assert job.is_terminal is False

    def test_can_retry_when_failed_with_attempts_left(self):
        job = self._make_job(
            status=BackfillJobStatus.FAILED, attempt=1, max_retries=3
        )
        assert job.can_retry is True

    def test_can_retry_false_when_max_reached(self):
        job = self._make_job(
            status=BackfillJobStatus.FAILED, attempt=3, max_retries=3
        )
        assert job.can_retry is False

    def test_can_retry_false_when_not_failed(self):
        job = self._make_job(status=BackfillJobStatus.SUCCESS, attempt=0)
        assert job.can_retry is False

    def test_mark_running_sets_status_and_increments_attempt(self):
        job = self._make_job()
        job.mark_running()
        assert job.status == BackfillJobStatus.RUNNING
        assert job.attempt == 1
        assert job.started_at is not None

    def test_mark_success(self):
        job = self._make_job(status=BackfillJobStatus.RUNNING)
        job.mark_success(rows_affected=100, duration=5.5)
        assert job.status == BackfillJobStatus.SUCCESS
        assert job.rows_affected == 100
        assert job.duration_seconds == 5.5
        assert job.completed_at is not None

    def test_mark_failed(self):
        job = self._make_job(status=BackfillJobStatus.RUNNING)
        job.mark_failed("Something broke")
        assert job.status == BackfillJobStatus.FAILED
        assert job.error_message == "Something broke"
        assert job.completed_at is not None

    def test_mark_failed_truncates_error(self):
        job = self._make_job(status=BackfillJobStatus.RUNNING)
        long_error = "x" * 2000
        job.mark_failed(long_error)
        assert len(job.error_message) == 1000

    def test_mark_cancelled(self):
        job = self._make_job()
        job.mark_cancelled()
        assert job.status == BackfillJobStatus.CANCELLED
        assert job.completed_at is not None

    def test_mark_paused(self):
        job = self._make_job()
        job.mark_paused()
        assert job.status == BackfillJobStatus.PAUSED

    def test_schedule_retry_resets_to_queued(self):
        job = self._make_job(status=BackfillJobStatus.FAILED)
        job.schedule_retry(120.0)
        assert job.status == BackfillJobStatus.QUEUED
        assert job.next_retry_at is not None
        assert job.completed_at is None
        assert job.started_at is None

    def test_status_enum_values(self):
        expected = {"queued", "running", "success", "failed", "cancelled", "paused"}
        actual = {s.value for s in BackfillJobStatus}
        assert actual == expected

    def test_repr(self):
        job = self._make_job(id="job_abc", chunk_index=2)
        r = repr(job)
        assert "job_abc" in r
        assert "2" in r


class TestBackfillExecutorCreateJobs:
    """Tests for BackfillExecutor.create_jobs_for_request."""

    def test_creates_correct_number_of_chunks(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        request = MagicMock()
        request.id = "req_1"
        request.tenant_id = "t1"
        request.source_system = "shopify"
        request.start_date = date(2024, 1, 1)
        request.end_date = date(2024, 1, 14)  # 14 days = 2 chunks

        jobs = executor.create_jobs_for_request(request)
        assert len(jobs) == 2
        assert jobs[0].chunk_index == 0
        assert jobs[1].chunk_index == 1

    @patch("src.services.audit_logger.emit_backfill_started")
    def test_transitions_request_to_running(self, mock_emit):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        request = MagicMock()
        request.id = "req_1"
        request.tenant_id = "t1"
        request.source_system = "shopify"
        request.start_date = date(2024, 1, 1)
        request.end_date = date(2024, 1, 7)

        executor.create_jobs_for_request(request)
        assert request.status == HistoricalBackfillStatus.RUNNING
        assert request.started_at is not None
        mock_db.commit.assert_called_once()

    def test_single_day_creates_one_chunk(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        request = MagicMock()
        request.id = "req_1"
        request.tenant_id = "t1"
        request.source_system = "shopify"
        request.start_date = date(2024, 1, 1)
        request.end_date = date(2024, 1, 1)

        jobs = executor.create_jobs_for_request(request)
        assert len(jobs) == 1
        assert jobs[0].chunk_start_date == date(2024, 1, 1)
        assert jobs[0].chunk_end_date == date(2024, 1, 1)

    def test_90_day_range_creates_13_chunks(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        request = MagicMock()
        request.id = "req_1"
        request.tenant_id = "t1"
        request.source_system = "shopify"
        request.start_date = date(2024, 1, 1)
        request.end_date = date(2024, 3, 30)

        jobs = executor.create_jobs_for_request(request)
        assert len(jobs) == 13


class TestBackfillExecutorRetry:
    """Tests for retry logic in the executor."""

    def test_maybe_schedule_retry_when_can_retry(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        job = BackfillJob(
            id="job_1",
            backfill_request_id="req_1",
            tenant_id="t1",
            source_system="shopify",
            chunk_start_date=date(2024, 1, 1),
            chunk_end_date=date(2024, 1, 7),
            chunk_index=0,
            status=BackfillJobStatus.FAILED,
            attempt=1,
            max_retries=3,
        )

        executor._maybe_schedule_retry(job)
        assert job.status == BackfillJobStatus.QUEUED
        assert job.next_retry_at is not None

    def test_no_retry_when_max_reached(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        job = BackfillJob(
            id="job_1",
            backfill_request_id="req_1",
            tenant_id="t1",
            source_system="shopify",
            chunk_start_date=date(2024, 1, 1),
            chunk_end_date=date(2024, 1, 7),
            chunk_index=0,
            status=BackfillJobStatus.FAILED,
            attempt=3,
            max_retries=3,
        )

        executor._maybe_schedule_retry(job)
        # Should remain FAILED
        assert job.status == BackfillJobStatus.FAILED


class TestBackfillExecutorParentStatus:
    """Tests for parent request status roll-up."""

    def _setup_executor_with_jobs(self, job_statuses, can_retry_flags=None):
        """Helper to set up executor with mock jobs."""
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        jobs = []
        for i, status in enumerate(job_statuses):
            job = MagicMock()
            job.status = status
            if can_retry_flags:
                job.can_retry = can_retry_flags[i]
            else:
                job.can_retry = False
            jobs.append(job)

        request = MagicMock()
        request.id = "req_1"

        mock_db.query.return_value.filter.return_value.all.return_value = jobs
        mock_db.query.return_value.filter.return_value.first.return_value = request

        return executor, request

    def test_all_success_completes_parent(self):
        executor, request = self._setup_executor_with_jobs(
            [BackfillJobStatus.SUCCESS, BackfillJobStatus.SUCCESS]
        )
        executor._update_parent_status("req_1")
        assert request.status == HistoricalBackfillStatus.COMPLETED

    def test_all_cancelled_cancels_parent(self):
        executor, request = self._setup_executor_with_jobs(
            [BackfillJobStatus.CANCELLED, BackfillJobStatus.CANCELLED]
        )
        executor._update_parent_status("req_1")
        assert request.status == HistoricalBackfillStatus.CANCELLED

    def test_terminal_failure_fails_parent(self):
        executor, request = self._setup_executor_with_jobs(
            [BackfillJobStatus.SUCCESS, BackfillJobStatus.FAILED],
            can_retry_flags=[False, False],
        )
        executor._update_parent_status("req_1")
        assert request.status == HistoricalBackfillStatus.FAILED

    def test_retryable_failure_does_not_fail_parent(self):
        executor, request = self._setup_executor_with_jobs(
            [BackfillJobStatus.SUCCESS, BackfillJobStatus.FAILED],
            can_retry_flags=[False, True],  # Second job can still retry
        )
        executor._update_parent_status("req_1")
        # Should NOT be FAILED since the failed job can still retry
        assert request.status != HistoricalBackfillStatus.FAILED


class TestBackfillExecutorPauseResume:
    """Tests for pause/resume/cancel operations."""

    def test_pause_changes_queued_to_paused(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        job1 = MagicMock()
        job2 = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [
            job1, job2
        ]

        count = executor.pause_request("req_1")
        assert count == 2
        job1.mark_paused.assert_called_once()
        job2.mark_paused.assert_called_once()
        mock_db.commit.assert_called()

    def test_resume_changes_paused_to_queued(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        job = MagicMock()
        job.status = BackfillJobStatus.PAUSED
        mock_db.query.return_value.filter.return_value.all.return_value = [job]

        request = MagicMock()
        request.status = HistoricalBackfillStatus.RUNNING
        mock_db.query.return_value.filter.return_value.first.return_value = request

        count = executor.resume_request("req_1")
        assert count == 1
        assert job.status == BackfillJobStatus.QUEUED
        assert job.completed_at is None
        assert job.next_retry_at is None

    def test_cancel_request(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        job = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [job]
        # For _update_parent_status
        mock_db.query.return_value.filter.return_value.first.return_value = MagicMock()

        count = executor.cancel_request("req_1")
        assert count == 1
        job.mark_cancelled.assert_called_once()

    def test_pause_empty_returns_zero(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)
        mock_db.query.return_value.filter.return_value.all.return_value = []

        count = executor.pause_request("req_1")
        assert count == 0


class TestBackfillExecutorRecovery:
    """Tests for stale job recovery."""

    def test_recover_resets_stale_running_jobs(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        stale_job = MagicMock()
        stale_job.status = BackfillJobStatus.RUNNING
        mock_db.query.return_value.filter.return_value.all.return_value = [stale_job]

        recovered = executor.recover_stale_jobs()
        assert recovered == 1
        assert stale_job.status == BackfillJobStatus.QUEUED
        assert stale_job.next_retry_at is None
        assert stale_job.started_at is None
        mock_db.commit.assert_called_once()

    def test_no_stale_jobs_returns_zero(self):
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)
        mock_db.query.return_value.filter.return_value.all.return_value = []

        recovered = executor.recover_stale_jobs()
        assert recovered == 0
        mock_db.commit.assert_not_called()


class TestBackfillWorkerStats:
    """Tests for the worker stats dataclass."""

    def test_worker_stats_to_dict(self):
        from src.workers.backfill_worker import WorkerStats

        stats = WorkerStats()
        stats.cycles = 10
        stats.jobs_executed = 5
        stats.errors = 1

        d = stats.to_dict()
        assert d["cycles"] == 10
        assert d["jobs_executed"] == 5
        assert d["errors"] == 1
        assert "uptime_seconds" in d
        assert d["uptime_seconds"] >= 0

    def test_worker_stats_defaults(self):
        from src.workers.backfill_worker import WorkerStats

        stats = WorkerStats()
        assert stats.cycles == 0
        assert stats.jobs_executed == 0
        assert stats.requests_created == 0
        assert stats.jobs_recovered == 0
        assert stats.errors == 0


# =============================================================================
# Backfill State Guard Tests - Story 3.4 (downstream protection)
# =============================================================================

from src.services.backfill_state_guard import (
    BackfillStateGuard,
    BackfillGuardStatus,
    BACKFILL_DASHBOARD_MODE,
)
from src.models.data_availability import AvailabilityState, AvailabilityReason


class TestBackfillGuardStatus:
    """Tests for the BackfillGuardStatus dataclass."""

    def test_inactive_defaults(self):
        status = BackfillGuardStatus(is_backfill_active=False)
        assert status.is_backfill_active is False
        assert status.ai_insights_allowed is True
        assert status.data_availability_override is None
        assert status.active_request_ids == []
        assert status.affected_source_systems == []

    def test_active_status(self):
        status = BackfillGuardStatus(
            is_backfill_active=True,
            active_request_ids=["req_1"],
            affected_source_systems=["shopify"],
            affected_sla_keys=["shopify_orders"],
            dashboard_mode="warn",
            ai_insights_allowed=False,
            data_availability_override="stale",
        )
        assert status.is_backfill_active is True
        assert status.ai_insights_allowed is False
        assert status.data_availability_override == "stale"
        assert "shopify_orders" in status.affected_sla_keys

    def test_to_dict(self):
        status = BackfillGuardStatus(
            is_backfill_active=True,
            active_request_ids=["req_1"],
            affected_source_systems=["shopify"],
            affected_sla_keys=["shopify_orders"],
            dashboard_mode="warn",
            ai_insights_allowed=False,
            data_availability_override="stale",
        )
        d = status.to_dict()
        assert d["is_backfill_active"] is True
        assert d["ai_insights_allowed"] is False
        assert d["dashboard_mode"] == "warn"


class TestBackfillStateGuardInit:
    """Tests for BackfillStateGuard initialization."""

    def test_requires_tenant_id(self):
        with pytest.raises(ValueError, match="tenant_id is required"):
            BackfillStateGuard(MagicMock(), "")

    def test_accepts_valid_tenant_id(self):
        guard = BackfillStateGuard(MagicMock(), "tenant_123")
        assert guard.tenant_id == "tenant_123"


class TestBackfillStateGuardActive:
    """Tests for active backfill detection."""

    def test_no_active_backfills(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []
        mock_db.query.return_value.filter.return_value.first.return_value = None

        guard = BackfillStateGuard(mock_db, "tenant_1")
        assert guard.is_backfill_active() is False

    def test_active_backfill_detected(self):
        mock_db = MagicMock()
        mock_request = MagicMock()
        mock_request.source_system = "shopify"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_request

        guard = BackfillStateGuard(mock_db, "tenant_1")
        assert guard.is_backfill_active() is True

    def test_is_source_being_backfilled_match(self):
        mock_db = MagicMock()
        mock_request = MagicMock()
        mock_request.source_system = "shopify"
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_request]

        guard = BackfillStateGuard(mock_db, "tenant_1")
        assert guard.is_source_being_backfilled("shopify_orders") is True

    def test_is_source_being_backfilled_no_match(self):
        mock_db = MagicMock()
        mock_request = MagicMock()
        mock_request.source_system = "facebook"
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_request]

        guard = BackfillStateGuard(mock_db, "tenant_1")
        assert guard.is_source_being_backfilled("shopify_orders") is False

    def test_is_source_being_backfilled_no_active(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        guard = BackfillStateGuard(mock_db, "tenant_1")
        assert guard.is_source_being_backfilled("shopify_orders") is False


class TestBackfillStateGuardStatus:
    """Tests for full guard status."""

    def test_inactive_guard_status(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        guard = BackfillStateGuard(mock_db, "tenant_1")
        status = guard.get_guard_status()

        assert status.is_backfill_active is False
        assert status.ai_insights_allowed is True
        assert status.data_availability_override is None
        assert status.active_request_ids == []

    def test_active_guard_status(self):
        mock_db = MagicMock()
        mock_request = MagicMock()
        mock_request.id = "req_1"
        mock_request.source_system = "shopify"
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_request]

        guard = BackfillStateGuard(mock_db, "tenant_1")
        status = guard.get_guard_status()

        assert status.is_backfill_active is True
        assert status.ai_insights_allowed is False
        assert status.data_availability_override == "stale"
        assert "req_1" in status.active_request_ids
        assert "shopify" in status.affected_source_systems
        assert "shopify_orders" in status.affected_sla_keys

    def test_multiple_active_backfills(self):
        mock_db = MagicMock()
        req1 = MagicMock()
        req1.id = "req_1"
        req1.source_system = "shopify"
        req2 = MagicMock()
        req2.id = "req_2"
        req2.source_system = "facebook"
        mock_db.query.return_value.filter.return_value.all.return_value = [req1, req2]

        guard = BackfillStateGuard(mock_db, "tenant_1")
        status = guard.get_guard_status()

        assert len(status.active_request_ids) == 2
        assert len(status.affected_source_systems) == 2


class TestBackfillStateGuardCompletion:
    """Tests for completion hooks."""

    def test_on_backfill_completed_calls_freshness_recalc(self):
        mock_db = MagicMock()
        guard = BackfillStateGuard(mock_db, "tenant_1")

        with patch.object(guard, "_recalculate_freshness") as mock_recalc, \
             patch.object(guard, "_clear_caches"):
            guard.on_backfill_completed("req_1", "shopify")
            mock_recalc.assert_called_once_with("shopify_orders")

    def test_on_backfill_completed_clears_cache(self):
        mock_db = MagicMock()
        guard = BackfillStateGuard(mock_db, "tenant_1")

        with patch.object(guard, "_recalculate_freshness"), \
             patch.object(guard, "_clear_caches") as mock_clear:
            guard.on_backfill_completed("req_1", "shopify")
            mock_clear.assert_called_once()

    def test_on_backfill_completed_no_direct_audit(self):
        """Completion no longer emits audit directly (moved to executor)."""
        mock_db = MagicMock()
        guard = BackfillStateGuard(mock_db, "tenant_1")

        with patch.object(guard, "_recalculate_freshness"), \
             patch.object(guard, "_clear_caches"):
            guard.on_backfill_completed("req_1", "shopify")

        assert not hasattr(guard, "_log_backfill_completion")

    def test_completion_survives_freshness_failure(self):
        """Completion doesn't crash if freshness recalc fails."""
        mock_db = MagicMock()
        guard = BackfillStateGuard(mock_db, "tenant_1")

        # Test the internal error handling of _recalculate_freshness directly
        with patch(
            "src.services.data_availability_service.DataAvailabilityService",
            side_effect=Exception("DB down"),
        ):
            # Should not raise
            guard._recalculate_freshness("shopify_orders")

    def test_completion_survives_cache_failure(self):
        """Completion doesn't crash if cache clear fails."""
        mock_db = MagicMock()
        guard = BackfillStateGuard(mock_db, "tenant_1")

        with patch(
            "src.entitlements.cache.invalidate_tenant_entitlements",
            side_effect=Exception("Redis down"),
        ):
            # Should not raise
            guard._clear_caches()


class TestBackfillStateGuardStatic:
    """Tests for static convenience methods."""

    def test_check_backfill_active_static(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        result = BackfillStateGuard.check_backfill_active(mock_db, "tenant_1")
        assert result is False

    def test_get_status_static(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = []

        status = BackfillStateGuard.get_status(mock_db, "tenant_1")
        assert isinstance(status, BackfillGuardStatus)
        assert status.is_backfill_active is False


class TestAvailabilityReasonBackfill:
    """Tests for the BACKFILL_IN_PROGRESS reason code."""

    def test_backfill_reason_exists(self):
        assert hasattr(AvailabilityReason, "BACKFILL_IN_PROGRESS")
        assert AvailabilityReason.BACKFILL_IN_PROGRESS.value == "backfill_in_progress"

    def test_all_reasons_present(self):
        expected = {
            "sync_ok", "sla_exceeded", "grace_window_exceeded",
            "sync_failed", "never_synced", "backfill_in_progress",
        }
        actual = {r.value for r in AvailabilityReason}
        assert actual == expected


class TestDataAvailabilityBackfillOverride:
    """Tests for the backfill override in DataAvailabilityService."""

    @patch("src.services.data_availability_service.get_sla_thresholds", return_value=(1440, 2880))
    @patch("src.services.data_availability_service.DataAvailabilityService._get_latest_sync")
    @patch("src.services.data_availability_service.DataAvailabilityService._compute_state")
    @patch("src.services.data_availability_service.DataAvailabilityService._get_existing")
    @patch("src.services.data_availability_service.DataAvailabilityService._upsert")
    @patch("src.services.data_availability_service.DataAvailabilityService._check_backfill_override")
    def test_fresh_overridden_to_stale_during_backfill(
        self, mock_override, mock_upsert, mock_existing, mock_compute, mock_sync, mock_sla,
    ):
        """When backfill is active and state is FRESH, override to STALE."""
        from src.services.data_availability_service import DataAvailabilityService

        mock_sync.return_value = (datetime(2024, 1, 1, tzinfo=timezone.utc), "succeeded")
        mock_compute.return_value = (AvailabilityState.FRESH.value, AvailabilityReason.SYNC_OK.value)
        mock_existing.return_value = None
        mock_upsert.return_value = MagicMock()
        mock_override.return_value = (
            AvailabilityState.STALE.value,
            AvailabilityReason.BACKFILL_IN_PROGRESS.value,
        )

        mock_db = MagicMock()
        service = DataAvailabilityService(mock_db, "tenant_1")
        result = service.get_data_availability("shopify_orders")

        assert result.state == AvailabilityState.STALE.value
        assert result.reason == AvailabilityReason.BACKFILL_IN_PROGRESS.value

    @patch("src.services.data_availability_service.get_sla_thresholds", return_value=(1440, 2880))
    @patch("src.services.data_availability_service.DataAvailabilityService._get_latest_sync")
    @patch("src.services.data_availability_service.DataAvailabilityService._compute_state")
    @patch("src.services.data_availability_service.DataAvailabilityService._get_existing")
    @patch("src.services.data_availability_service.DataAvailabilityService._upsert")
    @patch("src.services.data_availability_service.DataAvailabilityService._check_backfill_override")
    def test_no_override_when_no_backfill(
        self, mock_override, mock_upsert, mock_existing, mock_compute, mock_sync, mock_sla,
    ):
        """When no backfill is active, FRESH state is preserved."""
        from src.services.data_availability_service import DataAvailabilityService

        mock_sync.return_value = (datetime(2024, 1, 1, tzinfo=timezone.utc), "succeeded")
        mock_compute.return_value = (AvailabilityState.FRESH.value, AvailabilityReason.SYNC_OK.value)
        mock_existing.return_value = None
        mock_upsert.return_value = MagicMock()
        mock_override.return_value = None  # No override

        mock_db = MagicMock()
        service = DataAvailabilityService(mock_db, "tenant_1")
        result = service.get_data_availability("shopify_orders")

        mock_override.assert_called_once_with("shopify_orders")

    @patch("src.services.data_availability_service.get_sla_thresholds", return_value=(1440, 2880))
    @patch("src.services.data_availability_service.DataAvailabilityService._get_latest_sync")
    @patch("src.services.data_availability_service.DataAvailabilityService._get_existing")
    @patch("src.services.data_availability_service.DataAvailabilityService._upsert")
    @patch("src.services.data_availability_service.DataAvailabilityService._check_backfill_override")
    def test_stale_not_overridden_during_backfill(
        self, mock_override, mock_upsert, mock_existing, mock_sync, mock_sla,
    ):
        """When state is already UNAVAILABLE, backfill override is not called."""
        from src.services.data_availability_service import DataAvailabilityService

        # Return None for sync (UNAVAILABLE state)
        mock_sync.return_value = (None, None)
        mock_existing.return_value = None
        mock_upsert.return_value = MagicMock()

        mock_db = MagicMock()
        service = DataAvailabilityService(mock_db, "tenant_1")
        result = service.get_data_availability("shopify_orders")

        # UNAVAILABLE state — override should NOT be called
        mock_override.assert_not_called()
        assert result.state == AvailabilityState.UNAVAILABLE.value


class TestExecutorCompletionHook:
    """Tests for the executor's completion hook integration."""

    def test_terminal_state_triggers_guard(self):
        """When all jobs succeed, _on_request_terminal is called."""
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        all_success_jobs = [MagicMock(status=BackfillJobStatus.SUCCESS, can_retry=False)]
        request = MagicMock()
        request.id = "req_1"
        request.tenant_id = "t1"
        request.source_system = "shopify"

        mock_db.query.return_value.filter.return_value.all.return_value = all_success_jobs
        mock_db.query.return_value.filter.return_value.first.return_value = request

        with patch.object(executor, "_on_request_terminal") as mock_hook:
            executor._update_parent_status("req_1")
            mock_hook.assert_called_once_with(request)

    def test_non_terminal_does_not_trigger_guard(self):
        """When jobs are still running, no completion hook fires."""
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        mixed_jobs = [
            MagicMock(status=BackfillJobStatus.SUCCESS, can_retry=False),
            MagicMock(status=BackfillJobStatus.QUEUED, can_retry=False),
        ]
        request = MagicMock()
        request.id = "req_1"

        mock_db.query.return_value.filter.return_value.all.return_value = mixed_jobs
        mock_db.query.return_value.filter.return_value.first.return_value = request

        with patch.object(executor, "_on_request_terminal") as mock_hook:
            executor._update_parent_status("req_1")
            mock_hook.assert_not_called()

    def test_on_request_terminal_calls_guard(self):
        """_on_request_terminal delegates to BackfillStateGuard."""
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        request = MagicMock()
        request.id = "req_1"
        request.tenant_id = "t1"
        request.source_system = "shopify"

        with patch(
            "src.services.backfill_state_guard.BackfillStateGuard"
        ) as MockGuard:
            mock_guard = MagicMock()
            MockGuard.return_value = mock_guard

            executor._on_request_terminal(request)

            MockGuard.assert_called_once_with(mock_db, "t1")
            mock_guard.on_backfill_completed.assert_called_once_with(
                "req_1", "shopify"
            )

    def test_on_request_terminal_survives_guard_failure(self):
        """_on_request_terminal doesn't crash if guard fails."""
        mock_db = MagicMock()
        executor = BackfillExecutor(mock_db)

        request = MagicMock()
        request.id = "req_1"
        request.tenant_id = "t1"
        request.source_system = "shopify"

        with patch(
            "src.services.backfill_state_guard.BackfillStateGuard",
            side_effect=Exception("guard broken"),
        ):
            # Should not raise
            executor._on_request_terminal(request)


# =====================================================================
# Backfill Status Service Tests (Story 3.4 - Status API)
# =====================================================================


def _make_mock_request(**overrides):
    """Helper to build a mock HistoricalBackfillRequest."""
    req = MagicMock()
    req.id = overrides.get("id", "req_1")
    req.tenant_id = overrides.get("tenant_id", "tenant_1")
    req.source_system = overrides.get("source_system", "shopify")
    req.start_date = overrides.get("start_date", date(2024, 1, 1))
    req.end_date = overrides.get("end_date", date(2024, 1, 28))
    req.status = overrides.get("status", HistoricalBackfillStatus.RUNNING)
    req.reason = overrides.get("reason", "Data gap after migration")
    req.requested_by = overrides.get("requested_by", "admin_user")
    req.idempotency_key = overrides.get("idempotency_key", "key_123")
    req.started_at = overrides.get("started_at", datetime(2024, 1, 1, tzinfo=timezone.utc))
    req.completed_at = overrides.get("completed_at", None)
    req.created_at = overrides.get("created_at", datetime(2024, 1, 1, tzinfo=timezone.utc))
    return req


def _make_mock_job(**overrides):
    """Helper to build a mock BackfillJob."""
    job = MagicMock()
    job.backfill_request_id = overrides.get("backfill_request_id", "req_1")
    job.chunk_index = overrides.get("chunk_index", 0)
    job.chunk_start_date = overrides.get("chunk_start_date", date(2024, 1, 1))
    job.chunk_end_date = overrides.get("chunk_end_date", date(2024, 1, 7))
    job.status = overrides.get("status", BackfillJobStatus.SUCCESS)
    job.attempt = overrides.get("attempt", 1)
    job.duration_seconds = overrides.get("duration_seconds", 120.0)
    job.rows_affected = overrides.get("rows_affected", 1000)
    job.error_message = overrides.get("error_message", None)
    job.is_terminal = overrides.get("is_terminal", True)
    job.can_retry = overrides.get("can_retry", False)
    return job


class TestBackfillStatusServiceEffectiveStatus:
    """Tests for _compute_effective_status."""

    def test_pending_status(self):
        """PENDING request maps to 'pending'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.PENDING)
        assert service._compute_effective_status(req, []) == "pending"

    def test_approved_maps_to_pending(self):
        """APPROVED request maps to 'pending'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.APPROVED)
        assert service._compute_effective_status(req, []) == "pending"

    def test_completed_status(self):
        """COMPLETED request maps to 'completed'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.COMPLETED)
        assert service._compute_effective_status(req, []) == "completed"

    def test_cancelled_maps_to_completed(self):
        """CANCELLED request maps to 'completed'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.CANCELLED)
        assert service._compute_effective_status(req, []) == "completed"

    def test_failed_status(self):
        """FAILED request maps to 'failed'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.FAILED)
        assert service._compute_effective_status(req, []) == "failed"

    def test_rejected_maps_to_failed(self):
        """REJECTED request maps to 'failed'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.REJECTED)
        assert service._compute_effective_status(req, []) == "failed"

    def test_running_status(self):
        """RUNNING request with active jobs maps to 'running'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.RUNNING)
        jobs = [
            _make_mock_job(status=BackfillJobStatus.SUCCESS, is_terminal=True),
            _make_mock_job(status=BackfillJobStatus.QUEUED, is_terminal=False),
        ]
        assert service._compute_effective_status(req, jobs) == "running"

    def test_running_with_all_paused_maps_to_paused(self):
        """RUNNING request where all non-terminal jobs are PAUSED → 'paused'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.RUNNING)
        jobs = [
            _make_mock_job(status=BackfillJobStatus.SUCCESS, is_terminal=True),
            _make_mock_job(status=BackfillJobStatus.PAUSED, is_terminal=False),
            _make_mock_job(status=BackfillJobStatus.PAUSED, is_terminal=False),
        ]
        assert service._compute_effective_status(req, jobs) == "paused"

    def test_running_with_no_jobs(self):
        """RUNNING request with no jobs yet → 'running'."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.RUNNING)
        assert service._compute_effective_status(req, []) == "running"


class TestBackfillStatusServicePercentComplete:
    """Tests for percent_complete calculation."""

    def test_zero_chunks(self):
        """No chunks → 0% complete."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.PENDING)
        result = service._build_status(req, [])
        assert result["percent_complete"] == 0.0

    def test_all_chunks_complete(self):
        """All chunks succeeded → 100%."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.COMPLETED)
        jobs = [
            _make_mock_job(chunk_index=0, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(chunk_index=1, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(chunk_index=2, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(chunk_index=3, status=BackfillJobStatus.SUCCESS),
        ]
        result = service._build_status(req, jobs)
        assert result["percent_complete"] == 100.0

    def test_partial_progress(self):
        """2 of 4 chunks done → 50%."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        req = _make_mock_request(status=HistoricalBackfillStatus.RUNNING)
        jobs = [
            _make_mock_job(chunk_index=0, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(chunk_index=1, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(chunk_index=2, status=BackfillJobStatus.RUNNING, is_terminal=False),
            _make_mock_job(chunk_index=3, status=BackfillJobStatus.QUEUED, is_terminal=False),
        ]
        result = service._build_status(req, jobs)
        assert result["percent_complete"] == 50.0


class TestBackfillStatusServiceCurrentChunk:
    """Tests for current_chunk tracking."""

    def test_running_chunk_returned(self):
        """Currently RUNNING chunk is returned."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(chunk_index=0, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(
                chunk_index=1,
                status=BackfillJobStatus.RUNNING,
                chunk_start_date=date(2024, 1, 8),
                chunk_end_date=date(2024, 1, 14),
                attempt=1,
            ),
        ]
        result = service._get_current_chunk(jobs)
        assert result is not None
        assert result["chunk_index"] == 1
        assert result["chunk_start_date"] == "2024-01-08"
        assert result["chunk_end_date"] == "2024-01-14"
        assert result["status"] == "running"

    def test_no_running_chunk(self):
        """No RUNNING chunk → None."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(chunk_index=0, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(chunk_index=1, status=BackfillJobStatus.QUEUED),
        ]
        result = service._get_current_chunk(jobs)
        assert result is None


class TestBackfillStatusServiceFailureReasons:
    """Tests for failure_reasons collection."""

    def test_collects_error_messages(self):
        """Failed chunks have their error messages collected."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(
                chunk_index=0, status=BackfillJobStatus.FAILED,
                error_message="Connection timeout",
                chunk_start_date=date(2024, 1, 1),
                chunk_end_date=date(2024, 1, 7),
            ),
            _make_mock_job(chunk_index=1, status=BackfillJobStatus.SUCCESS),
            _make_mock_job(
                chunk_index=2, status=BackfillJobStatus.FAILED,
                error_message="Rate limited",
                chunk_start_date=date(2024, 1, 15),
                chunk_end_date=date(2024, 1, 21),
            ),
        ]
        reasons = service._collect_failure_reasons(jobs)
        assert len(reasons) == 2
        assert "Chunk 0" in reasons[0]
        assert "Connection timeout" in reasons[0]
        assert "Chunk 2" in reasons[1]
        assert "Rate limited" in reasons[1]

    def test_no_failures(self):
        """No failed chunks → empty list."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(chunk_index=0, status=BackfillJobStatus.SUCCESS),
        ]
        assert service._collect_failure_reasons(jobs) == []

    def test_failed_without_message_skipped(self):
        """Failed chunk with None error_message is skipped."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(
                chunk_index=0, status=BackfillJobStatus.FAILED,
                error_message=None,
            ),
        ]
        assert service._collect_failure_reasons(jobs) == []


class TestBackfillStatusServiceETA:
    """Tests for estimated_seconds_remaining calculation."""

    def test_eta_based_on_avg_duration(self):
        """ETA = avg_chunk_duration × remaining_chunks."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(
                chunk_index=0, status=BackfillJobStatus.SUCCESS,
                duration_seconds=100.0,
            ),
            _make_mock_job(
                chunk_index=1, status=BackfillJobStatus.SUCCESS,
                duration_seconds=200.0,
            ),
            _make_mock_job(
                chunk_index=2, status=BackfillJobStatus.QUEUED,
                is_terminal=False,
            ),
            _make_mock_job(
                chunk_index=3, status=BackfillJobStatus.QUEUED,
                is_terminal=False,
            ),
        ]
        # avg = 150, remaining = 2
        result = service._estimate_remaining(jobs, 4, 2, 0)
        assert result == 300.0

    def test_eta_none_when_no_completed(self):
        """No completed chunks → None ETA."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(chunk_index=0, status=BackfillJobStatus.QUEUED),
        ]
        result = service._estimate_remaining(jobs, 4, 0, 0)
        assert result is None

    def test_eta_none_when_no_remaining(self):
        """All done → None ETA."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(
                chunk_index=0, status=BackfillJobStatus.SUCCESS,
                duration_seconds=100.0,
            ),
        ]
        result = service._estimate_remaining(jobs, 1, 1, 0)
        assert result is None

    def test_eta_excludes_failed_chunks(self):
        """Failed chunks reduce remaining count."""
        from src.services.backfill_status_service import BackfillStatusService

        service = BackfillStatusService(MagicMock())
        jobs = [
            _make_mock_job(
                chunk_index=0, status=BackfillJobStatus.SUCCESS,
                duration_seconds=60.0,
            ),
            _make_mock_job(
                chunk_index=1, status=BackfillJobStatus.FAILED,
                can_retry=False, is_terminal=True,
            ),
            _make_mock_job(
                chunk_index=2, status=BackfillJobStatus.QUEUED,
                is_terminal=False,
            ),
        ]
        # total=3, completed=1, failed=1, remaining=1
        result = service._estimate_remaining(jobs, 3, 1, 1)
        assert result == 60.0


class TestBackfillStatusServiceGetRequestStatus:
    """Tests for get_request_status."""

    def test_request_not_found(self):
        """Returns None when request doesn't exist."""
        from src.services.backfill_status_service import BackfillStatusService

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        service = BackfillStatusService(mock_db)

        assert service.get_request_status("nonexistent") is None

    def test_full_status_response(self):
        """Returns complete status dict for a running request."""
        from src.services.backfill_status_service import BackfillStatusService

        req = _make_mock_request()
        jobs = [
            _make_mock_job(
                chunk_index=0, status=BackfillJobStatus.SUCCESS,
                duration_seconds=100.0,
            ),
            _make_mock_job(
                chunk_index=1, status=BackfillJobStatus.RUNNING,
                is_terminal=False,
                chunk_start_date=date(2024, 1, 8),
                chunk_end_date=date(2024, 1, 14),
            ),
            _make_mock_job(
                chunk_index=2, status=BackfillJobStatus.QUEUED,
                is_terminal=False,
            ),
            _make_mock_job(
                chunk_index=3, status=BackfillJobStatus.QUEUED,
                is_terminal=False,
            ),
        ]

        mock_db = MagicMock()
        # First call: query for request (filter.first)
        # Second call: query for jobs (filter.order_by.all)
        mock_db.query.return_value.filter.return_value.first.return_value = req
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = jobs

        service = BackfillStatusService(mock_db)
        result = service.get_request_status("req_1")

        assert result is not None
        assert result["id"] == "req_1"
        assert result["status"] == "running"
        assert result["percent_complete"] == 25.0
        assert result["total_chunks"] == 4
        assert result["completed_chunks"] == 1
        assert result["failed_chunks"] == 0
        assert result["current_chunk"]["chunk_index"] == 1
        assert result["estimated_seconds_remaining"] is not None


class TestBackfillStatusServiceListRequests:
    """Tests for list_requests."""

    def test_empty_list(self):
        """Returns empty list when no requests exist."""
        from src.services.backfill_status_service import BackfillStatusService

        mock_db = MagicMock()
        mock_db.query.return_value.order_by.return_value.all.return_value = []
        service = BackfillStatusService(mock_db)

        result = service.list_requests()
        assert result == []

    def test_filters_by_tenant_id(self):
        """Applies tenant_id filter to query."""
        from src.services.backfill_status_service import BackfillStatusService

        mock_db = MagicMock()
        query_mock = mock_db.query.return_value
        filter_mock = query_mock.filter.return_value
        filter_mock.order_by.return_value.all.return_value = []

        service = BackfillStatusService(mock_db)
        service.list_requests(tenant_id="tenant_1")

        # Verify filter was called (tenant_id filtering)
        query_mock.filter.assert_called_once()

    def test_status_filter_applied(self):
        """Status filter excludes non-matching requests."""
        from src.services.backfill_status_service import BackfillStatusService

        req_pending = _make_mock_request(
            id="req_1", status=HistoricalBackfillStatus.PENDING
        )

        mock_db = MagicMock()
        # With DB pre-filter, chain is: query().filter().order_by().all()
        # MagicMock auto-chains, so set the terminal .all() to return
        # only the pre-filtered results (DB would have filtered out RUNNING).
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            req_pending,
        ]
        # Jobs batch query returns empty
        mock_db.query.return_value.filter.return_value.filter.return_value.order_by.return_value.all.return_value = []

        service = BackfillStatusService(mock_db)
        result = service.list_requests(status_filter="pending")

        assert len(result) == 1
        assert result[0]["status"] == "pending"


class TestBackfillStatusSchemas:
    """Tests for the status Pydantic schemas."""

    def test_backfill_status_response_valid(self):
        """BackfillStatusResponse accepts valid data."""
        from src.api.schemas.backfill_request import BackfillStatusResponse

        data = BackfillStatusResponse(
            id="req_1",
            tenant_id="t1",
            source_system="shopify",
            start_date="2024-01-01",
            end_date="2024-01-28",
            status="running",
            percent_complete=50.0,
            total_chunks=4,
            completed_chunks=2,
            failed_chunks=0,
            failure_reasons=[],
            reason="Data gap",
            requested_by="admin",
        )
        assert data.status == "running"
        assert data.percent_complete == 50.0
        assert data.current_chunk is None
        assert data.estimated_seconds_remaining is None

    def test_backfill_chunk_status_valid(self):
        """BackfillChunkStatus accepts valid data."""
        from src.api.schemas.backfill_request import BackfillChunkStatus

        chunk = BackfillChunkStatus(
            chunk_index=1,
            chunk_start_date="2024-01-08",
            chunk_end_date="2024-01-14",
            status="running",
            attempt=2,
            duration_seconds=120.5,
            rows_affected=500,
        )
        assert chunk.chunk_index == 1
        assert chunk.attempt == 2

    def test_backfill_status_list_response(self):
        """BackfillStatusListResponse wraps list correctly."""
        from src.api.schemas.backfill_request import (
            BackfillStatusResponse,
            BackfillStatusListResponse,
        )

        resp = BackfillStatusListResponse(
            backfills=[
                BackfillStatusResponse(
                    id="r1", tenant_id="t1", source_system="shopify",
                    start_date="2024-01-01", end_date="2024-01-28",
                    status="completed", percent_complete=100.0,
                    total_chunks=4, completed_chunks=4, failed_chunks=0,
                    failure_reasons=[], reason="Gap", requested_by="admin",
                ),
            ],
            total=1,
        )
        assert resp.total == 1
        assert len(resp.backfills) == 1
