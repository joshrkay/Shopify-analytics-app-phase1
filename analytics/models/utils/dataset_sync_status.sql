{{
    config(
        materialized='table',
        schema='utils',
        tags=['utils', 'observability', 'dataset_sync']
    )
}}

-- Dataset Sync Status (observability)
--
-- Schema for dataset-level sync status tracking. Populated by the backend
-- SupersetDatasetSync service (DatasetMetrics table is source of truth in
-- the backend DB). This model creates the same schema in the analytics DB
-- for optional mirroring or reporting.
--
-- Story 5.2 — Dataset-level observability

select
    cast(null as varchar(255)) as dataset_name,
    cast(null as varchar(255)) as schema_name,
    cast(null as varchar(50)) as current_version,
    cast(null as int) as column_count,
    cast(null as int) as exposed_column_count,
    cast(null as timestamptz) as last_sync_at,
    cast(null as timestamptz) as last_sync_attempted_at,
    cast(null as varchar(20)) as sync_status,
    cast(null as text) as sync_error,
    cast(null as timestamptz) as last_schema_check_at,
    cast(null as boolean) as schema_compatible,
    cast(null as text) as breaking_changes_json,
    cast(null as int) as query_count_24h,
    cast(null as float) as avg_query_latency_ms,
    current_timestamp as dbt_updated_at
where false
