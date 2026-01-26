"""
Row-Level Security (RLS) rules for Superset datasets.
These rules enforce tenant isolation at the dataset level.
"""

# RLS Rule Definition Template
RLS_RULES = {
    'fact_orders': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fact_orders'],
        'description': 'Isolate orders by tenant',
    },
    'fact_marketing_spend': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fact_marketing_spend'],
        'description': 'Isolate marketing spend by tenant',
    },
    'fact_campaign_performance': {
        'clause': "tenant_id = '{{ current_user.tenant_id }}'",
        'tables': ['fact_campaign_performance'],
        'description': 'Isolate campaign performance by tenant',
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


# RLS Configuration for Superset API
def create_rls_rules_for_superset(superset_client):
    """
    Apply RLS rules to all datasets in Superset.

    Args:
        superset_client: Authenticated Superset API client

    Returns:
        List of rule IDs created
    """
    rule_ids = []

    for dataset_name, rule_config in RLS_RULES.items():
        payload = {
            'name': f"{dataset_name}_tenant_isolation",
            'description': rule_config['description'],
            'filter_type': 'Regular',
            'tables': rule_config['tables'],
            'clause': rule_config['clause'],
        }

        response = superset_client.post(
            '/api/v1/rowlevelsecurity/rules/',
            json=payload
        )

        if response.status_code == 201:
            rule_ids.append(response.json()['id'])
        else:
            raise Exception(
                f"Failed to create RLS rule for {dataset_name}: {response.text}"
            )

    return rule_ids
