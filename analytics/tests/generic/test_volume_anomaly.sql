{% test test_volume_anomaly(model, date_column, min_daily_records=1, lookback_days=7) %}

    {#-
    Generic test to detect volume anomalies by checking if daily record counts
    are above a minimum threshold over a lookback period.
    
    Args:
        model: The model to test
        date_column: The date column to group by (e.g., 'order_created_at', 'performance_date')
        min_daily_records: Minimum number of records expected per day (default: 1)
        lookback_days: Number of days to look back (default: 7)
    -#}
    
    with daily_counts as (
        select
            date({{ date_column }}) as date,
            count(*) as record_count
        from {{ model }}
        where {{ date_column }} >= current_date - interval '{{ lookback_days }} days'
            and {{ date_column }} is not null
        group by date({{ date_column }})
    )
    
    select *
    from daily_counts
    where record_count < {{ min_daily_records }}

{% endtest %}
