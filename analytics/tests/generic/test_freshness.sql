{% test test_freshness(model, column_name, warn_after_hours=24, error_after_hours=48) %}

    {#-
    Generic test to check if a model's timestamp column is fresh (recently updated).
    
    This test checks if the most recent record in the model is within the error threshold.
    If the most recent record is older than error_after_hours, the test fails.
    
    Args:
        model: The model to test
        column_name: The timestamp column to check (e.g., 'dbt_updated_at', 'ingested_at')
        warn_after_hours: Number of hours before warning (default: 24)
        error_after_hours: Number of hours before error (default: 48)
    -#}
    
    with max_timestamp as (
        select max({{ column_name }}) as max_ts
        from {{ model }}
        where {{ column_name }} is not null
    )
    
    select *
    from max_timestamp
    where max_ts < current_timestamp - interval '{{ error_after_hours }} hours'

{% endtest %}
