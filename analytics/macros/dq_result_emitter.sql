{#-
    Emit structured DQ test result metadata at the end of each dbt run.

    Logs a JSON-formatted summary of all test results to stdout,
    enabling downstream systems (CI pipelines, backend DQ service)
    to parse and act on test outcomes.

    This macro is registered as an on-run-end hook in dbt_project.yml.

    Output format (logged to stdout):
        DQ_TEST_RESULTS: [{"test_name": "...", "status": "pass|fail|error", ...}]

    Consumers:
        - CI pipeline: parse from dbt logs to gate deployment
        - Backend DQ service: future integration with DataAvailabilityService
-#}

{% macro dq_result_emitter() %}
    {% if execute %}
        {% set test_results = [] %}
        {% for result in results if result.node.resource_type == 'test' %}
            {% set test_meta = {} %}
            {% if result.node.test_metadata %}
                {% set test_meta = {
                    'test_type': result.node.test_metadata.name | default(''),
                    'kwargs': result.node.test_metadata.kwargs | default({})
                } %}
            {% endif %}

            {% do test_results.append({
                'test_name': result.node.name,
                'status': result.status,
                'failures': result.failures | default(0),
                'severity': result.node.config.severity | default('error'),
                'execution_time': result.execution_time,
                'test_metadata': test_meta,
            }) %}
        {% endfor %}

        {% set total = test_results | length %}
        {% set failed = test_results | selectattr('status', 'equalto', 'fail') | list | length %}
        {% set errored = test_results | selectattr('status', 'equalto', 'error') | list | length %}

        {{ log("DQ_TEST_RESULTS: " ~ test_results | tojson, info=True) }}
        {{ log("DQ_TEST_SUMMARY: total=" ~ total ~ " passed=" ~ (total - failed - errored) ~ " failed=" ~ failed ~ " errored=" ~ errored, info=True) }}
    {% endif %}
{% endmacro %}
