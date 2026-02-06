{% test test_volume_anomaly(model, date_column, min_daily_records=1, lookback_days=7, threshold_pct=50) %}

    {#-
    Generic test to detect volume anomalies by comparing today's row count
    against a rolling baseline (mean of the previous N days).

    Triggers if today's count deviates from the rolling average by more than
    threshold_pct, OR falls below min_daily_records (absolute floor).

    Args:
        model: The model to test
        date_column: The date column to group by (e.g., 'order_created_at', 'performance_date')
        min_daily_records: Minimum number of records expected per day (default: 1)
        lookback_days: Number of days to look back for baseline (default: 7)
        threshold_pct: Maximum allowed deviation % from rolling average (default: 50)
    -#}

    with daily_counts as (
        select
            date({{ date_column }}) as dt,
            count(*) as record_count
        from {{ model }}
        where {{ date_column }} >= current_date - interval '{{ lookback_days + 1 }} days'
            and {{ date_column }} < current_date + interval '1 day'
            and {{ date_column }} is not null
        group by date({{ date_column }})
    ),

    baseline as (
        select
            avg(record_count) as avg_count,
            count(*) as baseline_days
        from daily_counts
        where dt < current_date
            and dt >= current_date - interval '{{ lookback_days }} days'
    ),

    today as (
        select coalesce(
            (select record_count from daily_counts where dt = current_date),
            0
        ) as today_count
    )

    -- Return rows when anomaly detected (empty result = pass)
    select
        t.today_count,
        b.avg_count as rolling_avg,
        b.baseline_days,
        case
            when b.avg_count > 0
            then round(((b.avg_count - t.today_count) / b.avg_count * 100)::numeric, 2)
            else 0
        end as deviation_pct,
        {{ threshold_pct }} as threshold_pct
    from today t
    cross join baseline b
    where
        -- Sufficient baseline exists (at least 2 days)
        b.baseline_days >= 2
        and b.avg_count > 0
        and (
            -- Volume drop exceeds threshold
            t.today_count < b.avg_count * (1.0 - {{ threshold_pct }} / 100.0)
            -- Volume spike exceeds threshold
            or t.today_count > b.avg_count * (1.0 + {{ threshold_pct }} / 100.0)
        )

    union all

    -- Absolute floor check (independent of baseline)
    select
        t.today_count,
        null as rolling_avg,
        0 as baseline_days,
        0 as deviation_pct,
        {{ threshold_pct }} as threshold_pct
    from today t
    where t.today_count < {{ min_daily_records }}
        and t.today_count is not null

{% endtest %}
