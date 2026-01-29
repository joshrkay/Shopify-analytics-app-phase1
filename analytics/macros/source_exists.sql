{% macro source_exists(source_name, table_name) %}
    {#
    Check if a source table exists in the database.

    This macro is used to make staging models defensive against missing
    source tables (e.g., when an Airbyte connector hasn't been set up yet).

    Args:
        source_name: The source name as defined in sources.yml
        table_name: The table name within the source

    Returns:
        Boolean indicating whether the source table exists

    Example:
        {% if source_exists('airbyte_raw', '_airbyte_raw_tiktok_ads') %}
            select * from {{ source('airbyte_raw', '_airbyte_raw_tiktok_ads') }}
        {% else %}
            select null limit 0
        {% endif %}
    #}

    {% set source_relation = adapter.get_relation(
        database=source(source_name, table_name).database,
        schema=source(source_name, table_name).schema,
        identifier=source(source_name, table_name).identifier
    ) %}

    {{ return(source_relation is not none) }}
{% endmacro %}


{% macro empty_staging_result(columns) %}
    {#
    Return an empty result set with the specified columns.
    Used when the source table doesn't exist yet.

    Args:
        columns: List of column definitions as dicts with 'name' and 'type' keys

    Example:
        {{ empty_staging_result([
            {'name': 'tenant_id', 'type': 'text'},
            {'name': 'event_id', 'type': 'text'},
            {'name': 'spend', 'type': 'numeric'}
        ]) }}
    #}
    select
    {% for col in columns %}
        cast(null as {{ col.type }}) as {{ col.name }}{% if not loop.last %},{% endif %}
    {% endfor %}
    where 1=0
{% endmacro %}
