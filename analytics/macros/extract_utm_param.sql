{% macro extract_utm_param(note_attributes_json, param_name) %}
    {#
    Macro to extract a UTM parameter from Shopify order note_attributes JSON array.
    
    Shopify stores UTM parameters in note_attributes as:
    [{"name": "utm_source", "value": "google"}, {"name": "utm_medium", "value": "cpc"}, ...]
    
    Args:
        note_attributes_json: JSONB column containing the note_attributes array
        param_name: Name of the UTM parameter to extract (e.g., 'utm_source', 'utm_campaign')
        
    Returns:
        The value of the UTM parameter, or null if not found
    #}
    
    (
        select trim(attr->>'value')
        from jsonb_array_elements(
            case 
                when {{ note_attributes_json }} is null or trim({{ note_attributes_json }}::text) = '' then '[]'::jsonb
                when {{ note_attributes_json }}::text ~ '^\s*\['
                    then {{ note_attributes_json }}::jsonb
                else '[]'::jsonb
            end
        ) as attr
        where trim(attr->>'name') = {{ param_name }}
        limit 1
    )
{% endmacro %}
