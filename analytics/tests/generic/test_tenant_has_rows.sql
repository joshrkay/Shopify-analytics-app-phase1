{% test test_tenant_has_rows(model, tenant_id_column='tenant_id', min_rows=1) %}

    {#-
    Generic test to verify each tenant has at least a minimum number of rows.

    Per user story 7.7.1: "row count > 0 per tenant after sync"

    This test ensures that after data sync, every tenant present in the
    canonical fact tables has at least some data. A failure indicates
    a potential sync issue or data loss for specific tenants.

    Args:
        model: The model to test
        tenant_id_column: The tenant ID column name (default: 'tenant_id')
        min_rows: Minimum number of rows expected per tenant (default: 1)

    Returns:
        Rows for tenants that have fewer than min_rows records (test fails if any rows returned)
    -#}

    with tenant_row_counts as (
        select
            {{ tenant_id_column }} as tenant_id,
            count(*) as row_count
        from {{ model }}
        where {{ tenant_id_column }} is not null
        group by {{ tenant_id_column }}
    )

    select
        tenant_id,
        row_count
    from tenant_row_counts
    where row_count < {{ min_rows }}

{% endtest %}
