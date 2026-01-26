"""
Row-Level Security (RLS) rules for Superset datasets.
These rules enforce tenant isolation at the dataset level.

ROLE-BASED RLS STRATEGY:
- Merchant users: tenant_id = '{{ current_user.tenant_id }}'
- Agency users: tenant_id IN ({{ current_user.allowed_tenants | tojson }})
- Super admin: 1=1 (no filtering)

CRITICAL: RLS rules are the LAST line of defense for tenant isolation.
Even if other security layers fail, RLS ensures data cannot leak.
"""

from enum import Enum
from typing import List, Dict, Any, Optional


class UserRoleType(Enum):
    """User role types for RLS rule selection."""
    MERCHANT = "merchant"
    AGENCY = "agency"
    SUPER_ADMIN = "super_admin"


# Base RLS clause templates by role type
RLS_CLAUSE_TEMPLATES = {
    UserRoleType.MERCHANT: "tenant_id = '{{ current_user.tenant_id }}'",
    UserRoleType.AGENCY: "tenant_id IN ({{ current_user.allowed_tenants | tojson }})",
    UserRoleType.SUPER_ADMIN: "1=1",  # No filtering for super admin
}


# Tables that require RLS enforcement
RLS_PROTECTED_TABLES = [
    'fact_orders',
    'fact_marketing_spend',
    'fact_campaign_performance',
    'dim_products',
    'dim_customers',
    'fact_inventory',
]


# RLS Rules by Role Type
RLS_RULES_BY_ROLE = {
    'merchant_admin': {
        'clause': RLS_CLAUSE_TEMPLATES[UserRoleType.MERCHANT],
        'description': 'Merchant admin sees only own store data',
        'tables': RLS_PROTECTED_TABLES,
        'role_type': UserRoleType.MERCHANT,
    },
    'merchant_viewer': {
        'clause': RLS_CLAUSE_TEMPLATES[UserRoleType.MERCHANT],
        'description': 'Merchant viewer sees only own store data (read-only)',
        'tables': RLS_PROTECTED_TABLES,
        'role_type': UserRoleType.MERCHANT,
    },
    'agency_admin': {
        'clause': RLS_CLAUSE_TEMPLATES[UserRoleType.AGENCY],
        'description': 'Agency admin sees assigned client stores',
        'tables': RLS_PROTECTED_TABLES,
        'role_type': UserRoleType.AGENCY,
    },
    'agency_viewer': {
        'clause': RLS_CLAUSE_TEMPLATES[UserRoleType.AGENCY],
        'description': 'Agency viewer sees limited assigned client stores',
        'tables': RLS_PROTECTED_TABLES,
        'role_type': UserRoleType.AGENCY,
    },
    'super_admin': {
        'clause': RLS_CLAUSE_TEMPLATES[UserRoleType.SUPER_ADMIN],
        'description': 'Super admin sees all data',
        'tables': RLS_PROTECTED_TABLES,
        'role_type': UserRoleType.SUPER_ADMIN,
    },
}


# Legacy RLS Rules (backward compatible with existing roles)
RLS_RULES = {
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


# SQL to validate agency RLS enforcement
RLS_AGENCY_VALIDATION_SQL = """
-- Run this query as an agency user
-- Expected result: 0 rows (only assigned tenants visible)
SELECT COUNT(*) as unauthorized_tenant_rows
FROM fact_orders
WHERE tenant_id NOT IN ({{ current_user.allowed_tenants | tojson }});
"""


def get_rls_clause_for_role(role: str) -> str:
    """
    Get the appropriate RLS clause for a given role.

    Args:
        role: User role name (e.g., 'merchant_admin', 'agency_viewer')

    Returns:
        RLS WHERE clause template
    """
    role_config = RLS_RULES_BY_ROLE.get(role.lower())
    if role_config:
        return role_config['clause']

    # Default to strict merchant-style isolation
    return RLS_CLAUSE_TEMPLATES[UserRoleType.MERCHANT]


def get_rls_clause_for_user(
    is_agency_user: bool,
    is_super_admin: bool = False
) -> str:
    """
    Get the appropriate RLS clause based on user type.

    Args:
        is_agency_user: True if user has multi-tenant access
        is_super_admin: True if user is super admin

    Returns:
        RLS WHERE clause template
    """
    if is_super_admin:
        return RLS_CLAUSE_TEMPLATES[UserRoleType.SUPER_ADMIN]
    if is_agency_user:
        return RLS_CLAUSE_TEMPLATES[UserRoleType.AGENCY]
    return RLS_CLAUSE_TEMPLATES[UserRoleType.MERCHANT]


def create_superset_rls_rule_payload(
    role: str,
    dataset_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Generate Superset RLS rule API payload for a role.

    Args:
        role: User role name
        dataset_id: Optional specific dataset ID

    Returns:
        Dictionary payload for Superset RLS API
    """
    rule_config = RLS_RULES_BY_ROLE.get(role.lower())
    if not rule_config:
        raise ValueError(f"Unknown role: {role}")

    payload = {
        'name': f'{role}_tenant_isolation',
        'description': rule_config['description'],
        'filter_type': 'Regular',
        'tables': rule_config['tables'],
        'clause': rule_config['clause'],
    }

    if dataset_id:
        payload['dataset_id'] = dataset_id

    return payload


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


def create_role_based_rls_rules(superset_client):
    """
    Apply role-based RLS rules to Superset.

    Creates RLS rules for each role type:
    - merchant_admin/merchant_viewer: Single tenant isolation
    - agency_admin/agency_viewer: Multi-tenant isolation via allowed_tenants
    - super_admin: No filtering

    Args:
        superset_client: Authenticated Superset API client

    Returns:
        Dict mapping role -> list of rule IDs created
    """
    role_rule_ids = {}

    for role, rule_config in RLS_RULES_BY_ROLE.items():
        rule_ids = []
        payload = create_superset_rls_rule_payload(role)

        response = superset_client.post(
            '/api/v1/rowlevelsecurity/rules/',
            json=payload
        )

        if response.status_code == 201:
            rule_ids.append(response.json()['id'])
        else:
            raise Exception(
                f"Failed to create RLS rule for role {role}: {response.text}"
            )

        role_rule_ids[role] = rule_ids

    return role_rule_ids


# JWT Claims to Superset User Context Mapping
JWT_TO_SUPERSET_CONTEXT = """
# In superset_config.py, add custom user context:

from flask import g

def get_user_context():
    '''
    Extract tenant context from JWT for RLS evaluation.

    Returns dict with:
    - tenant_id: Current active tenant
    - allowed_tenants: List of accessible tenants (for agency users)
    - is_agency_user: Boolean flag
    '''
    user = g.user
    return {
        'tenant_id': getattr(user, 'tenant_id', None),
        'allowed_tenants': getattr(user, 'allowed_tenants', []),
        'is_agency_user': getattr(user, 'is_agency_user', False),
    }
"""
