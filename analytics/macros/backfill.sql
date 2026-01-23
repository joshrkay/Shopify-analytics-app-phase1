{% macro backfill_date_filter(date_column, start_date, end_date) %}
    {#
    Macro to filter incremental models by date range for backfills.
    
    This macro allows overriding the default incremental filter (which uses
    max(ingested_at)) with a specific date range. This is useful for:
    - Reprocessing historical data after model changes
    - Backfilling missing data
    - Recalculating metrics for specific date ranges
    
    SECURITY: Tenant isolation must still be enforced via tenant_id filters
    in the model itself. This macro only handles date filtering.
    
    Args:
        date_column: The timestamp column to filter on (e.g., airbyte_emitted_at, created_at)
        start_date: Start date for backfill (inclusive). Format: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MI:SS'
        end_date: End date for backfill (inclusive). Format: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MI:SS'
        
    Returns:
        SQL condition that filters the date column to the specified range
        
    Usage in model:
        {% if var('backfill_start_date', none) and var('backfill_end_date', none) %}
            and {{ backfill_date_filter('airbyte_emitted_at', var('backfill_start_date'), var('backfill_end_date')) }}
        {% elif is_incremental() %}
            and airbyte_emitted_at > (
                select coalesce(max(ingested_at), '1970-01-01'::timestamp with time zone)
                from {{ this }}
            )
        {% endif %}
    #}
    
    {{ date_column }} >= '{{ start_date }}'::timestamp with time zone
        and {{ date_column }} <= '{{ end_date }}'::timestamp with time zone
{% endmacro %}
