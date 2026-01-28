{% macro convert_to_tenant_local_date(timestamp_col, timezone_col) %}
{#
    Converts a UTC timestamp to a tenant-local DATE.

    This macro normalizes timestamps to tenant local dates for consistent
    reporting across timezones (per user story 7.7.1).

    Args:
        timestamp_col: Column containing UTC timestamp
        timezone_col: Column containing IANA timezone string (e.g., 'America/New_York')

    Returns:
        DATE in tenant's local timezone

    Example usage:
        {{ convert_to_tenant_local_date('order_created_at', 'timezone') }} as date_local

    Note: When timezone is 'UTC', returns the same date as UTC.
    PostgreSQL syntax used - adjust for other databases.
#}
({{ timestamp_col }} AT TIME ZONE 'UTC' AT TIME ZONE {{ timezone_col }})::date
{% endmacro %}


{% macro get_tenant_local_date(timestamp_col, tenant_id_col) %}
{#
    Helper macro that looks up tenant timezone and converts timestamp to local date.

    Use this when you don't have timezone pre-joined.

    Args:
        timestamp_col: Column containing UTC timestamp
        tenant_id_col: Column containing tenant_id for timezone lookup

    Returns:
        DATE in tenant's local timezone

    Example usage:
        {{ get_tenant_local_date('order_created_at', 'tenant_id') }} as date_local
#}
(
    {{ timestamp_col }} AT TIME ZONE 'UTC' AT TIME ZONE coalesce(
        (select timezone from {{ ref('dim_tenant') }} dt where dt.tenant_id = {{ tenant_id_col }} limit 1),
        'UTC'
    )
)::date
{% endmacro %}
