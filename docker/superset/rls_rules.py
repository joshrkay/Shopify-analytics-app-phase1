"""
Row-Level Security (RLS) rules for Superset datasets.
These rules enforce tenant isolation at the dataset level.

RLS Flow (ASCII):
    User Query
        ↓
    Superset Dataset
        ↓
    RLS WHERE tenant_id = X
        ↓
    Fact Table (filtered)
"""

from typing import Any


# RLS Rule Definition Template
RLS_RULES: dict[str, dict[str, Any]] = {
    'fact_orders': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fact_orders'],
        'description': 'Isolate orders by tenant',
        'group_key': 'tenant_isolation',
    },
    'fact_ad_spend': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fact_ad_spend'],
        'description': 'Isolate ad spend by tenant',
        'group_key': 'tenant_isolation',
    },
    'fact_campaign_performance': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fact_campaign_performance'],
        'description': 'Isolate campaign performance by tenant',
        'group_key': 'tenant_isolation',
    },
    # Metrics layer tables
    'fct_revenue': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fct_revenue'],
        'description': 'Isolate revenue metrics by tenant',
        'group_key': 'tenant_isolation',
    },
    'fct_roas': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fct_roas'],
        'description': 'Isolate ROAS metrics by tenant',
        'group_key': 'tenant_isolation',
    },
    'fct_aov': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fct_aov'],
        'description': 'Isolate AOV metrics by tenant',
        'group_key': 'tenant_isolation',
    },
    'fct_cac': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fct_cac'],
        'description': 'Isolate CAC metrics by tenant',
        'group_key': 'tenant_isolation',
    },
    # Mart tables
    'mart_revenue_metrics': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['mart_revenue_metrics'],
        'description': 'Isolate revenue mart by tenant',
        'group_key': 'tenant_isolation',
    },
    'mart_marketing_metrics': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['mart_marketing_metrics'],
        'description': 'Isolate marketing mart by tenant',
        'group_key': 'tenant_isolation',
    },
}

# SQL to validate RLS enforcement (manual test)
RLS_VALIDATION_SQL = """
-- Run this query in Superset as a logged-in user
-- Expected result: 0 rows (no cross-tenant data visible)
SELECT COUNT(*) as cross_tenant_rows
FROM fact_orders
WHERE tenant_id != '{{ current_user.tenant_id }}';
"""

# SQL to validate RLS on all tables
RLS_VALIDATION_ALL_TABLES_SQL = """
-- Comprehensive RLS validation for all fact tables
-- Run as logged-in user, should return 0 for all counts

SELECT 'fact_orders' as table_name, COUNT(*) as cross_tenant_rows
FROM analytics.fact_orders
WHERE tenant_id != '{{ current_user.tenant_id }}'

UNION ALL

SELECT 'fact_ad_spend' as table_name, COUNT(*) as cross_tenant_rows
FROM analytics.fact_ad_spend
WHERE tenant_id != '{{ current_user.tenant_id }}'

UNION ALL

SELECT 'fact_campaign_performance' as table_name, COUNT(*) as cross_tenant_rows
FROM analytics.fact_campaign_performance
WHERE tenant_id != '{{ current_user.tenant_id }}';
"""


# RLS Configuration for Superset API
def create_rls_rules_for_superset(superset_client, datasets: list[str] | None = None):
    """
    Apply RLS rules to datasets in Superset.

    Args:
        superset_client: Authenticated Superset API client
        datasets: Optional list of dataset names to apply rules to.
                  If None, applies to all datasets in RLS_RULES.

    Returns:
        List of rule IDs created

    Raises:
        Exception: If rule creation fails for any dataset
    """
    rule_ids = []
    target_datasets = datasets if datasets else list(RLS_RULES.keys())

    for dataset_name in target_datasets:
        if dataset_name not in RLS_RULES:
            continue

        rule_config = RLS_RULES[dataset_name]
        payload = {
            'name': f"{dataset_name}_tenant_isolation",
            'description': rule_config['description'],
            'filter_type': 'Regular',
            'tables': rule_config['tables'],
            'clause': rule_config['clause'],
            'group_key': rule_config.get('group_key', 'tenant_isolation'),
        }

        response = superset_client.post(
            '/api/v1/rowlevelsecurity/rules/',
            json=payload
        )

        if response.status_code == 201:
            rule_ids.append(response.json()['id'])
        elif response.status_code == 409:
            # Rule already exists, skip
            continue
        else:
            raise Exception(
                f"Failed to create RLS rule for {dataset_name}: {response.text}"
            )

    return rule_ids


def get_rls_clause(dataset_name: str) -> str | None:
    """
    Get RLS clause for a dataset.

    Args:
        dataset_name: Name of the dataset

    Returns:
        RLS clause string or None if not found
    """
    rule = RLS_RULES.get(dataset_name)
    return rule['clause'] if rule else None


def validate_rls_coverage(dataset_names: list[str]) -> list[str]:
    """
    Check if all datasets have RLS rules defined.

    Args:
        dataset_names: List of dataset names to validate

    Returns:
        List of datasets missing RLS rules
    """
    return [name for name in dataset_names if name not in RLS_RULES]


def get_all_rls_tables() -> list[str]:
    """Get list of all tables with RLS rules."""
    tables = []
    for rule in RLS_RULES.values():
        tables.extend(rule['tables'])
    return list(set(tables))
