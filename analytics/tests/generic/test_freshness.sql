{% test test_freshness(model, column_name, source_name=none, warn_after_hours=none, error_after_hours=none) %}

    {#-
    Generic test to check if a model's timestamp column is fresh (recently updated).

    Thresholds are resolved in this order:
      1. If source_name is provided, look up the SLA from config/data_freshness_sla.yml
         via the get_freshness_threshold() macro (tier-aware, no hardcoded values).
      2. If warn_after_hours / error_after_hours are provided explicitly, use those.
      3. Fall back to 24h warn / 48h error.

    The test fails when the most recent record is older than the error threshold.

    Args:
        model:            The model to test
        column_name:      The timestamp column to check (e.g., 'dbt_updated_at', 'airbyte_emitted_at')
        source_name:      SLA source key (e.g., 'shopify_orders', 'email'). When set,
                          thresholds are pulled from config/data_freshness_sla.yml.
        warn_after_hours: Explicit hours before warning  (ignored when source_name is set)
        error_after_hours: Explicit hours before error   (ignored when source_name is set)
    -#}

    {#- Resolve error threshold in minutes -#}
    {%- if source_name -%}
        {%- set error_minutes = get_freshness_threshold(source_name, 'error_after_minutes') | int -%}
    {%- elif error_after_hours is not none -%}
        {%- set error_minutes = error_after_hours | int * 60 -%}
    {%- else -%}
        {%- set error_minutes = 2880 -%}
    {%- endif -%}

    with max_timestamp as (
        select max({{ column_name }}) as max_ts
        from {{ model }}
        where {{ column_name }} is not null
    )

    select *
    from max_timestamp
    where max_ts < current_timestamp - interval '{{ error_minutes }} minutes'

{% endtest %}
