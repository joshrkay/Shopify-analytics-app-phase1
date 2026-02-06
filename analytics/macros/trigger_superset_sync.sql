{#-
    Emit sync trigger metadata at the end of each dbt run (non-blocking).

    Logs a single JSON line to stdout so CI or a listener can trigger
    Superset dataset sync. No HTTP calls, no blocking I/O.

    Registered in on-run-end in dbt_project.yml (after dq_result_emitter).

    Output format (logged to stdout):
        SUPERSET_SYNC_TRIGGER: {"trigger": "dbt_on_run_end", "manifest_path": "...", ...}

    Consumers:
        - CI step: parse log and call backend DbtRunListener.on_dbt_run_complete()
        - Backend job: optional polling of dbt run output
-#}

{% macro trigger_superset_sync() %}
    {% if execute %}
        {% set failed_count = 0 %}
        {% for r in results %}
            {% if r.status == 'fail' %}
                {% set failed_count = failed_count + 1 %}
            {% endif %}
        {% endfor %}
        {% set sync_meta = {
            'trigger': 'dbt_on_run_end',
            'manifest_path': target.path ~ '/manifest.json',
            'run_id': invocation_id,
            'models_run': results | length,
            'test_failures': failed_count,
        } %}
        {{ log("SUPERSET_SYNC_TRIGGER: " ~ sync_meta | tojson, info=True) }}
    {% endif %}
{% endmacro %}
