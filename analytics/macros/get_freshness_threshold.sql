{%- macro get_freshness_threshold(source_name, threshold_type='warn_after_minutes', tier=none) -%}
{#-
    Return a freshness threshold (in minutes) from config/data_freshness_sla.yml.

    Args:
        source_name:    Key in the SLA config, e.g. 'shopify_orders', 'email'.
        threshold_type: 'warn_after_minutes' or 'error_after_minutes'.
        tier:           Billing tier override. Falls back to dbt var 'billing_tier',
                        then to the config's default_tier.

    Usage in sources.yml:
        freshness:
          warn_after:
            count: {{ get_freshness_threshold('shopify_orders', 'warn_after_minutes') }}
            period: minute

    Usage in tests / models:
        {{ get_freshness_threshold('email', 'error_after_minutes', 'enterprise') }}
-#}

{%- set sla_yaml = load_file_contents('../config/data_freshness_sla.yml') -%}
{%- set sla = fromyaml(sla_yaml) -%}

{#- Resolve billing tier: explicit arg > dbt var > config default -#}
{%- set effective_tier = tier or var('billing_tier', sla.get('default_tier', 'free')) -%}

{%- set source_cfg = sla.get('sources', {}).get(source_name, {}) -%}
{%- set tier_cfg = source_cfg.get(effective_tier, {}) -%}

{#- Fall back to free tier when the requested tier is missing for this source -#}
{%- if not tier_cfg -%}
    {%- set tier_cfg = source_cfg.get('free', {}) -%}
{%- endif -%}

{#- Hardcoded last resort: 24 h warn / 48 h error -#}
{%- set defaults = {'warn_after_minutes': 1440, 'error_after_minutes': 2880} -%}

{{ tier_cfg.get(threshold_type, defaults.get(threshold_type, 1440)) }}
{%- endmacro -%}
