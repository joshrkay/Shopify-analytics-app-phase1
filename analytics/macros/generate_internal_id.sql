{% macro generate_internal_id(tenant_id, source, platform_id) %}
    {#
    Generate a deterministic internal ID from tenant, source, and platform ID.

    This macro implements Option B ID normalization: generate internal normalized IDs
    while keeping platform IDs as attributes. The internal ID is a stable hash that
    can be used for joins across different ad platforms.

    Args:
        tenant_id: Expression for the tenant identifier
        source: Expression for the source/platform name (e.g., 'meta_ads', 'google_ads')
        platform_id: Expression for the platform-specific ID (account_id, campaign_id, etc.)

    Returns:
        MD5 hash of concatenated values, or NULL if any input is NULL

    Example:
        {{ generate_internal_id('tenant_id', "'meta_ads'", 'ad_account_id') }}
        -- Returns: md5(tenant_id || '|' || 'meta_ads' || '|' || ad_account_id)
    #}

    case
        when {{ tenant_id }} is null
            or {{ source }} is null
            or {{ platform_id }} is null
        then null
        else md5(
            cast({{ tenant_id }} as text)
            || '|'
            || cast({{ source }} as text)
            || '|'
            || cast({{ platform_id }} as text)
        )
    end
{% endmacro %}
