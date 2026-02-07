"""
Explore Guardrails Tests

CRITICAL: These tests verify that Explore mode guardrails are enforced.
All tests must pass before enabling Explore mode for users.

Acceptance Tests Coverage:
- QA: Attempt >90-day query -> blocked
- QA: Attempt new metric -> denied
- Perf: Worst-case query config validates guardrails
- Security: RLS integration verified
"""

import pytest
from datetime import datetime, timedelta
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from explore_guardrails import (
    ExplorePersona,
    ExplorePermissionValidator,
    ExploreGuardrailEnforcer,
    PerformanceGuardrails,
    PERFORMANCE_GUARDRAILS,
    DATASET_EXPLORE_CONFIGS,
    PERSONA_CONFIGS,
    EXPLORE_FEATURE_FLAGS,
    VisualizationType,
    ValidationResult,
    GuardrailBypassException,
    InMemoryGuardrailBypassStore,
    get_allowed_dimensions_for_dataset,
    get_allowed_metrics_for_dataset,
    get_allowed_visualizations_for_dataset,
    get_explorable_datasets,
    get_guardrail_bypass_banner,
    get_heavy_query_warnings,
    validate_explore_request,
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def merchant_validator():
    """Validator for merchant persona."""
    return ExplorePermissionValidator(ExplorePersona.MERCHANT)


@pytest.fixture
def agency_validator():
    """Validator for agency persona."""
    return ExplorePermissionValidator(ExplorePersona.AGENCY)


@pytest.fixture
def enforcer():
    """Guardrail enforcer instance."""
    return ExploreGuardrailEnforcer()


# ============================================================================
# TEST SUITE: DATE RANGE GUARDRAILS (QA Acceptance Test)
# ============================================================================

class TestDateRangeGuardrails:
    """
    ACCEPTANCE TEST: Attempt >90-day query -> blocked
    """

    def test_90_day_range_allowed(self, merchant_validator):
        """Exactly 90 days should be allowed."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)

        result = merchant_validator.validate_date_range(start_date, end_date)
        assert result.is_valid is True

    def test_89_day_range_allowed(self, merchant_validator):
        """89 days should be allowed."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=89)

        result = merchant_validator.validate_date_range(start_date, end_date)
        assert result.is_valid is True

    def test_91_day_range_blocked(self, merchant_validator):
        """CRITICAL: 91 days should be BLOCKED."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=91)

        result = merchant_validator.validate_date_range(start_date, end_date)
        assert result.is_valid is False
        assert result.error_code == "DATE_RANGE_EXCEEDED"
        assert "90 days" in result.error_message

    def test_180_day_range_blocked(self, merchant_validator):
        """CRITICAL: 180 days should be BLOCKED."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=180)

        result = merchant_validator.validate_date_range(start_date, end_date)
        assert result.is_valid is False
        assert result.error_code == "DATE_RANGE_EXCEEDED"

    def test_inverted_date_range_blocked(self, merchant_validator):
        """End date before start date should be blocked."""
        start_date = datetime.now()
        end_date = start_date - timedelta(days=30)

        result = merchant_validator.validate_date_range(start_date, end_date)
        assert result.is_valid is False
        assert result.error_code == "INVALID_DATE_RANGE"

    def test_7_day_range_allowed(self, merchant_validator):
        """Short ranges should be allowed."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)

        result = merchant_validator.validate_date_range(start_date, end_date)
        assert result.is_valid is True


# ============================================================================
# TEST SUITE: METRIC RESTRICTIONS (QA Acceptance Test)
# ============================================================================

class TestMetricRestrictions:
    """
    ACCEPTANCE TEST: Attempt new metric -> denied
    """

    def test_allowed_metric_accepted(self, merchant_validator):
        """Predefined metrics should be allowed."""
        result = merchant_validator.validate_metrics(
            'fact_orders',
            ['SUM(revenue)', 'COUNT(order_id)']
        )
        assert result.is_valid is True

    def test_custom_metric_denied(self, merchant_validator):
        """CRITICAL: Custom metrics should be DENIED."""
        result = merchant_validator.validate_metrics(
            'fact_orders',
            ['SUM(revenue * discount_percent)']
        )
        assert result.is_valid is False
        assert result.error_code == "METRIC_NOT_ALLOWED"

    def test_arbitrary_aggregate_denied(self, merchant_validator):
        """CRITICAL: Arbitrary aggregates should be DENIED."""
        result = merchant_validator.validate_metrics(
            'fact_orders',
            ['MAX(customer_email)']
        )
        assert result.is_valid is False
        assert result.error_code == "METRIC_NOT_ALLOWED"

    def test_subquery_metric_denied(self, merchant_validator):
        """CRITICAL: Subquery metrics should be DENIED."""
        result = merchant_validator.validate_metrics(
            'fact_orders',
            ['(SELECT SUM(revenue) FROM fact_orders)']
        )
        assert result.is_valid is False
        assert result.error_code == "METRIC_NOT_ALLOWED"

    def test_too_many_metrics_denied(self, merchant_validator):
        """Too many metrics in single query should be denied."""
        metrics = [
            'SUM(revenue)',
            'COUNT(order_id)',
            'AVG(revenue)',
            'COUNT(DISTINCT customer_id)',
            'SUM(revenue)',  # Duplicate but counts
            'AVG(revenue)',  # Duplicate but counts
        ]
        result = merchant_validator.validate_metrics('fact_orders', metrics)
        assert result.is_valid is False
        assert result.error_code == "TOO_MANY_METRICS"


# ============================================================================
# TEST SUITE: DATASET ACCESS CONTROL
# ============================================================================

class TestDatasetAccessControl:
    """Test dataset-level access control."""

    def test_allowed_dataset_accessible(self, merchant_validator):
        """Approved datasets should be accessible."""
        result = merchant_validator.validate_dataset('fact_orders')
        assert result.is_valid is True

        result = merchant_validator.validate_dataset('fact_marketing_spend')
        assert result.is_valid is True

        result = merchant_validator.validate_dataset('fact_campaign_performance')
        assert result.is_valid is True

    def test_disabled_dataset_blocked(self, merchant_validator):
        """CRITICAL: Disabled datasets should be BLOCKED."""
        result = merchant_validator.validate_dataset('dim_customers')
        assert result.is_valid is False
        assert result.error_code == "DATASET_DISABLED"

        result = merchant_validator.validate_dataset('dim_products')
        assert result.is_valid is False
        assert result.error_code == "DATASET_DISABLED"

    def test_unknown_dataset_blocked(self, merchant_validator):
        """Unknown datasets should be blocked."""
        result = merchant_validator.validate_dataset('internal_admin_table')
        assert result.is_valid is False
        assert result.error_code == "DATASET_NOT_FOUND"


# ============================================================================
# TEST SUITE: DIMENSION RESTRICTIONS
# ============================================================================

class TestDimensionRestrictions:
    """Test dimension access control."""

    def test_allowed_dimensions_accepted(self, merchant_validator):
        """Allowed dimensions should be accepted."""
        result = merchant_validator.validate_dimensions(
            'fact_orders',
            ['order_date', 'channel', 'campaign_id']
        )
        assert result.is_valid is True

    def test_restricted_dimension_denied(self, merchant_validator):
        """CRITICAL: Restricted dimensions should be DENIED."""
        result = merchant_validator.validate_dimensions(
            'fact_orders',
            ['customer_email']
        )
        assert result.is_valid is False

    def test_pii_column_denied(self, merchant_validator):
        """CRITICAL: PII columns should be DENIED."""
        pii_columns = ['customer_phone', 'customer_address', 'payment_method_details']
        for column in pii_columns:
            result = merchant_validator.validate_dimensions('fact_orders', [column])
            assert result.is_valid is False, f"PII column {column} should be denied"


# ============================================================================
# TEST SUITE: GROUP-BY LIMITS
# ============================================================================

class TestGroupByLimits:
    """Test group-by dimension limits."""

    def test_single_group_by_allowed(self, merchant_validator):
        """Single group-by should be allowed."""
        result = merchant_validator.validate_group_by_count(['channel'])
        assert result.is_valid is True

    def test_two_group_by_allowed(self, merchant_validator):
        """Two group-by dimensions should be allowed."""
        result = merchant_validator.validate_group_by_count(['channel', 'order_date'])
        assert result.is_valid is True

    def test_three_group_by_denied(self, merchant_validator):
        """CRITICAL: Three group-by dimensions should be DENIED."""
        result = merchant_validator.validate_group_by_count(
            ['channel', 'order_date', 'product_category']
        )
        assert result.is_valid is False
        assert result.error_code == "TOO_MANY_GROUP_BY"
        assert "2" in result.error_message

    def test_no_group_by_allowed(self, merchant_validator):
        """No group-by (aggregate all) should be allowed."""
        result = merchant_validator.validate_group_by_count([])
        assert result.is_valid is True


# ============================================================================
# TEST SUITE: VISUALIZATION RESTRICTIONS
# ============================================================================

class TestVisualizationRestrictions:
    """Test visualization type restrictions."""

    def test_allowed_viz_accepted(self, merchant_validator):
        """Allowed visualizations should be accepted."""
        allowed_types = ['line', 'bar', 'table', 'number']
        for viz in allowed_types:
            result = merchant_validator.validate_visualization('fact_orders', viz)
            assert result.is_valid is True, f"Viz type {viz} should be allowed"

    def test_pie_allowed_for_orders(self, merchant_validator):
        """Pie chart is allowed for orders dataset."""
        result = merchant_validator.validate_visualization('fact_orders', 'pie')
        assert result.is_valid is True

    def test_unknown_viz_denied(self, merchant_validator):
        """Unknown visualization types should be denied."""
        result = merchant_validator.validate_visualization('fact_orders', 'unknown_chart')
        assert result.is_valid is False
        assert result.error_code == "VIZ_NOT_RECOGNIZED"


# ============================================================================
# TEST SUITE: PERSONA DIFFERENCES
# ============================================================================

class TestPersonaDifferences:
    """Test differences between merchant and agency personas."""

    def test_both_personas_access_same_datasets(
        self,
        merchant_validator,
        agency_validator
    ):
        """Both personas should access the same datasets."""
        for dataset in ['fact_orders', 'fact_marketing_spend', 'fact_campaign_performance']:
            merchant_result = merchant_validator.validate_dataset(dataset)
            agency_result = agency_validator.validate_dataset(dataset)
            assert merchant_result.is_valid is True
            assert agency_result.is_valid is True

    def test_agency_has_roas_metric(self):
        """Agency should have access to ROAS calculation."""
        agency_metrics = get_allowed_metrics_for_dataset(
            'fact_campaign_performance',
            ExplorePersona.AGENCY
        )
        assert 'SUM(revenue)/NULLIF(SUM(spend), 0)' in agency_metrics


# ============================================================================
# TEST SUITE: QUERY ENFORCER
# ============================================================================

class TestQueryEnforcer:
    """Test query-level enforcement."""

    def test_row_limit_added(self, enforcer):
        """Row limit should be added to queries without LIMIT."""
        query = "SELECT * FROM fact_orders"
        result = enforcer.add_row_limit(query)
        assert "LIMIT 50000" in result

    def test_row_limit_enforced(self, enforcer):
        """Existing high LIMIT should be blocked."""
        query = "SELECT * FROM fact_orders LIMIT 100000"
        with pytest.raises(ValueError):
            enforcer.add_row_limit(query)

    def test_low_row_limit_preserved(self, enforcer):
        """Low LIMIT should be preserved."""
        query = "SELECT * FROM fact_orders LIMIT 100"
        result = enforcer.add_row_limit(query)
        assert "LIMIT 100" in result

    def test_timeout_config(self, enforcer):
        """Timeout config should be set correctly."""
        config = enforcer.get_timeout_config()
        assert config['SQLLAB_ASYNC_TIME_LIMIT_SEC'] == 20
        assert config['SQLLAB_TIMEOUT'] == 20

    def test_cache_config(self, enforcer):
        """Cache config should use 30-minute TTL."""
        config = enforcer.get_cache_config()
        assert config['CACHE_DEFAULT_TIMEOUT'] == 1800  # 30 minutes in seconds


class TestGuardrailBypass:
    """Test approved guardrail bypass behavior."""

    def test_bypass_allows_extended_date_range(self):
        """Approved bypass should allow longer date range."""
        now = datetime.utcnow()
        exception = GuardrailBypassException(
            id="bypass-1",
            user_id="user-123",
            requested_by_role="super_admin",
            approved_by="tech-lead-1",
            approved_by_role="analytics_tech_lead",
            dataset_names=("fact_orders",),
            expires_at=now + timedelta(minutes=30),
            reason="Investigation",
            created_at=now,
        )
        store = InMemoryGuardrailBypassStore([exception])

        query_params = {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)"],
            "group_by": ["order_date"],
            "start_date": now - timedelta(days=180),
            "end_date": now,
            "filters": [],
            "viz_type": "line",
        }

        is_valid, error = validate_explore_request(
            "merchant",
            "fact_orders",
            query_params,
            user_id="user-123",
            bypass_store=store,
        )
        assert is_valid is True
        assert error is None

    def test_bypass_does_not_allow_disabled_dataset(self):
        """Bypass must not allow PII-disabled datasets."""
        now = datetime.utcnow()
        exception = GuardrailBypassException(
            id="bypass-2",
            user_id="user-123",
            requested_by_role="super_admin",
            approved_by="security-1",
            approved_by_role="security_engineer",
            dataset_names=("dim_customers",),
            expires_at=now + timedelta(minutes=30),
            reason="Investigation",
            created_at=now,
        )
        store = InMemoryGuardrailBypassStore([exception])

        query_params = {
            "dimensions": [],
            "metrics": [],
            "group_by": [],
            "filters": [],
        }

        is_valid, error = validate_explore_request(
            "merchant",
            "dim_customers",
            query_params,
            user_id="user-123",
            bypass_store=store,
        )
        assert is_valid is False
        assert error == "Dataset 'dim_customers' is not available for exploration"

    def test_bypass_rejected_with_invalid_roles(self):
        """Bypass must require super admin request and approved roles."""
        now = datetime.utcnow()
        exception = GuardrailBypassException(
            id="bypass-3",
            user_id="user-123",
            requested_by_role="analyst",
            approved_by="tech-lead-1",
            approved_by_role="analytics_tech_lead",
            dataset_names=("fact_orders",),
            expires_at=now + timedelta(minutes=30),
            reason="Investigation",
            created_at=now,
        )
        store = InMemoryGuardrailBypassStore([exception])

        query_params = {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)"],
            "group_by": ["order_date"],
            "start_date": now - timedelta(days=180),
            "end_date": now,
            "filters": [],
            "viz_type": "line",
        }

        is_valid, error = validate_explore_request(
            "merchant",
            "fact_orders",
            query_params,
            user_id="user-123",
            bypass_store=store,
        )
        assert is_valid is False
        assert error == "Date range of 180 days exceeds maximum of 90 days"

    def test_bypass_banner_displays_remaining_minutes(self):
        """Bypass banner shows remaining minutes until expiry."""
        now = datetime.utcnow()
        exception = GuardrailBypassException(
            id="bypass-4",
            user_id="user-123",
            requested_by_role="super_admin",
            approved_by="security-1",
            approved_by_role="security_engineer",
            dataset_names=("fact_orders",),
            expires_at=now + timedelta(minutes=37),
            reason="Investigation",
            created_at=now,
        )
        banner = get_guardrail_bypass_banner(exception, now=now)
        assert "expires in 37 minutes" in banner


class TestHeavyQueryWarnings:
    """Test inline warning generation for heavy queries."""

    def test_warns_on_high_limits(self):
        query_params = {
            "dimensions": ["order_date"],
            "metrics": ["SUM(revenue)"] * PERFORMANCE_GUARDRAILS.max_metrics_per_query,
            "group_by": ["order_date"] * PERFORMANCE_GUARDRAILS.max_group_by_dimensions,
            "start_date": datetime.utcnow() - timedelta(
                days=int(PERFORMANCE_GUARDRAILS.max_date_range_days * 0.8)
            ),
            "end_date": datetime.utcnow(),
            "filters": [{}] * PERFORMANCE_GUARDRAILS.max_filters,
        }
        warnings = get_heavy_query_warnings(query_params, PERFORMANCE_GUARDRAILS)
        assert warnings


# ============================================================================
# TEST SUITE: FEATURE FLAGS
# ============================================================================

class TestFeatureFlags:
    """Test Superset feature flags configuration."""

    def test_custom_metrics_disabled(self):
        """CRITICAL: Custom metrics must be disabled."""
        assert EXPLORE_FEATURE_FLAGS['ENABLE_CUSTOM_METRICS'] is False

    def test_sql_queries_disabled(self):
        """CRITICAL: SQL queries must be disabled."""
        assert EXPLORE_FEATURE_FLAGS['SQL_QUERIES_ALLOWED'] is False

    def test_csv_export_disabled(self):
        """CRITICAL: CSV export must be disabled."""
        assert EXPLORE_FEATURE_FLAGS['CSV_EXPORT'] is False

    def test_adhoc_subquery_disabled(self):
        """CRITICAL: Ad-hoc subqueries must be disabled."""
        assert EXPLORE_FEATURE_FLAGS['ALLOW_ADHOC_SUBQUERY'] is False

    def test_metric_edit_disabled(self):
        """CRITICAL: Metric editing must be disabled."""
        assert EXPLORE_FEATURE_FLAGS['ALLOW_USER_METRIC_EDIT'] is False

    def test_template_processing_disabled(self):
        """CRITICAL: Template processing (Jinja) must be disabled."""
        assert EXPLORE_FEATURE_FLAGS['ENABLE_TEMPLATE_PROCESSING'] is False


# ============================================================================
# TEST SUITE: COMPREHENSIVE QUERY VALIDATION
# ============================================================================

class TestComprehensiveQueryValidation:
    """Test full query validation flow."""

    def test_valid_query_passes(self, merchant_validator):
        """Valid query should pass all checks."""
        query_params = {
            'dimensions': ['order_date', 'channel'],
            'metrics': ['SUM(revenue)', 'COUNT(order_id)'],
            'group_by': ['order_date', 'channel'],
            'start_date': datetime.now() - timedelta(days=30),
            'end_date': datetime.now(),
            'viz_type': 'line',
            'filters': [{'column': 'channel', 'op': 'IN', 'value': ['facebook']}],
        }

        result = merchant_validator.validate_query('fact_orders', query_params)
        assert result.is_valid is True

    def test_invalid_date_range_fails(self, merchant_validator):
        """Query with invalid date range should fail."""
        query_params = {
            'dimensions': ['order_date'],
            'metrics': ['SUM(revenue)'],
            'group_by': ['order_date'],
            'start_date': datetime.now() - timedelta(days=100),
            'end_date': datetime.now(),
            'viz_type': 'line',
            'filters': [],
        }

        result = merchant_validator.validate_query('fact_orders', query_params)
        assert result.is_valid is False
        assert result.error_code == "DATE_RANGE_EXCEEDED"

    def test_invalid_metric_fails(self, merchant_validator):
        """Query with invalid metric should fail."""
        query_params = {
            'dimensions': ['order_date'],
            'metrics': ['CUSTOM_METRIC(revenue)'],
            'group_by': ['order_date'],
            'start_date': datetime.now() - timedelta(days=30),
            'end_date': datetime.now(),
            'viz_type': 'line',
            'filters': [],
        }

        result = merchant_validator.validate_query('fact_orders', query_params)
        assert result.is_valid is False
        assert result.error_code == "METRIC_NOT_ALLOWED"

    def test_too_many_group_by_fails(self, merchant_validator):
        """Query with too many group-by dimensions should fail."""
        query_params = {
            'dimensions': ['order_date', 'channel', 'product_category'],
            'metrics': ['SUM(revenue)'],
            'group_by': ['order_date', 'channel', 'product_category'],
            'start_date': datetime.now() - timedelta(days=30),
            'end_date': datetime.now(),
            'viz_type': 'table',
            'filters': [],
        }

        result = merchant_validator.validate_query('fact_orders', query_params)
        assert result.is_valid is False
        assert result.error_code == "TOO_MANY_GROUP_BY"


# ============================================================================
# TEST SUITE: CONVENIENCE FUNCTIONS
# ============================================================================

class TestConvenienceFunctions:
    """Test helper/convenience functions."""

    def test_get_explorable_datasets(self):
        """Should return only enabled datasets for persona."""
        datasets = get_explorable_datasets(ExplorePersona.MERCHANT)
        assert 'fact_orders' in datasets
        assert 'fact_marketing_spend' in datasets
        assert 'fact_campaign_performance' in datasets
        assert 'dim_customers' not in datasets
        assert 'dim_products' not in datasets

    def test_get_allowed_dimensions(self):
        """Should return allowed dimensions for dataset."""
        dimensions = get_allowed_dimensions_for_dataset('fact_orders')
        assert 'order_date' in dimensions
        assert 'channel' in dimensions
        assert 'customer_email' not in dimensions

    def test_get_allowed_visualizations(self):
        """Should return allowed viz types for dataset."""
        viz_types = get_allowed_visualizations_for_dataset('fact_orders')
        assert 'line' in viz_types
        assert 'bar' in viz_types
        assert 'table' in viz_types

    def test_validate_explore_request_valid(self):
        """Convenience function should validate valid requests."""
        is_valid, error = validate_explore_request(
            'merchant',
            'fact_orders',
            {
                'dimensions': ['order_date'],
                'metrics': ['SUM(revenue)'],
                'group_by': ['order_date'],
            }
        )
        assert is_valid is True
        assert error is None

    def test_validate_explore_request_invalid_persona(self):
        """Convenience function should reject invalid persona."""
        is_valid, error = validate_explore_request(
            'superadmin',
            'fact_orders',
            {}
        )
        assert is_valid is False
        assert 'persona' in error.lower()


# ============================================================================
# TEST SUITE: PERFORMANCE GUARDRAILS VALUES
# ============================================================================

class TestPerformanceGuardrailsValues:
    """Verify performance guardrail values are correct."""

    def test_max_date_range(self):
        """Max date range should be 90 days."""
        assert PERFORMANCE_GUARDRAILS.max_date_range_days == 90

    def test_query_timeout(self):
        """Query timeout should be 20 seconds."""
        assert PERFORMANCE_GUARDRAILS.query_timeout_seconds == 20

    def test_row_limit(self):
        """Row limit should be 50,000."""
        assert PERFORMANCE_GUARDRAILS.row_limit == 50000

    def test_max_group_by(self):
        """Max group-by should be 2."""
        assert PERFORMANCE_GUARDRAILS.max_group_by_dimensions == 2

    def test_cache_ttl(self):
        """Cache TTL should be 30 minutes."""
        assert PERFORMANCE_GUARDRAILS.cache_ttl_minutes == 30


# ============================================================================
# TEST SUITE: INVALID PERSONA HANDLING
# ============================================================================

class TestInvalidPersonaHandling:
    """Test handling of invalid personas."""

    def test_invalid_persona_raises_error(self):
        """Invalid persona should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            ExplorePermissionValidator("superadmin")
        assert "Invalid persona" in str(exc_info.value)


# ============================================================================
# TEST SUITE: SECURITY - RLS INTEGRATION
# ============================================================================

class TestRLSIntegration:
    """
    SECURITY: Verify RLS rules are documented for Explore datasets.

    Note: Actual RLS enforcement happens in Superset via rls_rules.py.
    These tests verify that all explorable datasets have RLS defined.
    """

    def test_all_explorable_datasets_have_tenant_id(self):
        """All explorable datasets should have tenant_id for RLS."""
        # This test verifies that datasets enabled for explore
        # are the same ones covered by RLS rules
        explorable = get_explorable_datasets(ExplorePersona.MERCHANT)
        rls_covered = ['fact_orders', 'fact_marketing_spend', 'fact_campaign_performance']

        for dataset in explorable:
            assert dataset in rls_covered, \
                f"Dataset {dataset} is explorable but not covered by RLS rules"

    def test_disabled_datasets_excluded_from_explore(self):
        """PII-containing datasets should be disabled for explore."""
        assert DATASET_EXPLORE_CONFIGS['dim_customers'].enabled is False
        assert DATASET_EXPLORE_CONFIGS['dim_products'].enabled is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
