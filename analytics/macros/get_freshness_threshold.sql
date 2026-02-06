{%- macro get_freshness_threshold(source_name, threshold_type='warn_after_minutes', tier=none) -%}
{#-
    Return a freshness threshold (in minutes) from dbt vars.

    Values mirror config/data_freshness_sla.yml — keep both in sync.
    Backend reads the YAML file; dbt reads the var('freshness_sla') dict.

    Args:
        source_name:    Key in the SLA config, e.g. 'shopify_orders', 'email'.
        threshold_type: 'warn_after_minutes' or 'error_after_minutes'.
        tier:           Billing tier override. Falls back to dbt var 'billing_tier',
                        then to 'free'.

    Note: Custom macros are NOT available during source YAML parsing in dbt 1.11+.
    Sources use inline var() lookups. This macro is for tests and models only.

    Usage in tests / models:
        {{ get_freshness_threshold('email', 'error_after_minutes', 'enterprise') }}
-#}

{%- set sla = var('freshness_sla', {}) -%}

{#- Resolve billing tier: explicit arg > dbt var > free -#}
{%- set effective_tier = tier or var('billing_tier', 'free') -%}

{%- set source_cfg = sla.get(source_name, {}) -%}
{%- set tier_cfg = source_cfg.get(effective_tier, {}) -%}

{#- Fall back to free tier when the requested tier is missing for this source -#}
{%- if not tier_cfg -%}
    {%- set tier_cfg = source_cfg.get('free', {}) -%}
{%- endif -%}

{#- Hardcoded last resort: 24 h warn / 48 h error -#}
{%- set defaults = {'warn_after_minutes': 1440, 'error_after_minutes': 2880} -%}

{{ tier_cfg.get(threshold_type, defaults.get(threshold_type, 1440)) }}
{%- endmacro -%}
