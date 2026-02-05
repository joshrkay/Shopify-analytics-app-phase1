{% macro get_lookback_days(source_name) %}
    {#
    Get the lookback window in days for a specific source.

    Used by incremental models to determine how far back to look for
    late-arriving data. Each source may have different data latency
    characteristics.

    Args:
        source_name: The source identifier (e.g., 'shopify', 'meta_ads', 'google_ads')

    Returns:
        Integer number of days for lookback window

    Example:
        {% set lookback = get_lookback_days('meta_ads') %}
        WHERE report_date >= current_date - {{ lookback }}
    #}

    {% set source_var = 'lookback_days_' ~ source_name %}
    {% set default_var = 'lookback_days_default' %}

    {{ var(source_var, var(default_var, 3)) }}
{% endmacro %}


{% macro get_incremental_filter(source_name, date_column) %}
    {#
    Generate the incremental filter clause for a staging model.

    This macro generates the WHERE clause for incremental models,
    using the source-specific lookback window.

    Args:
        source_name: The source identifier for lookback config
        date_column: The date column to filter on (e.g., 'report_date')

    Returns:
        SQL WHERE clause for incremental filtering

    Example:
        {{ get_incremental_filter('meta_ads', 'report_date') }}
        -- Returns: WHERE report_date >= current_date - 3
    #}

    {% if is_incremental() %}
        where {{ date_column }} >= current_date - {{ get_lookback_days(source_name) }}
    {% endif %}
{% endmacro %}
