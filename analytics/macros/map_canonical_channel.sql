{% macro map_canonical_channel(source, platform_channel) %}
    {#
    Map platform-specific channel to canonical channel taxonomy.

    This macro centralizes channel taxonomy mapping to ensure consistent
    channel classification across all staging models and downstream reporting.

    Canonical Channels:
        - paid_social: Paid advertising on social platforms (Meta, TikTok, Snap, Pinterest)
        - paid_search: Paid search advertising (Google Search, Bing)
        - paid_shopping: Paid shopping/product ads (Google Shopping, Amazon, Pinterest Shopping)
        - email: Email marketing (Klaviyo, Mailchimp, Shopify Email)
        - sms: SMS marketing (Attentive, Postscript, SMSBump)
        - organic_social: Organic social media traffic
        - organic_search: Organic search engine traffic
        - direct: Direct traffic (no referrer)
        - referral: Referral from other websites
        - affiliate: Affiliate marketing traffic
        - other: Unclassified or unknown channels

    Args:
        source: The data source identifier (e.g., 'meta_ads', 'google_ads')
        platform_channel: The platform-specific channel/placement/campaign type

    Returns:
        Canonical channel string

    Example:
        {{ map_canonical_channel("'meta_ads'", 'placement') }}
    #}

    case
        -- Meta Ads: All paid social
        when {{ source }} = 'meta_ads' then 'paid_social'

        -- Google Ads: Differentiate search vs shopping
        when {{ source }} = 'google_ads' then
            case
                when lower({{ platform_channel }}) like '%shopping%' then 'paid_shopping'
                when lower({{ platform_channel }}) like '%pmax%' then 'paid_shopping'
                when lower({{ platform_channel }}) like '%performance_max%' then 'paid_shopping'
                when lower({{ platform_channel }}) in ('search', 'search_network') then 'paid_search'
                when lower({{ platform_channel }}) in ('display', 'display_network') then 'paid_social'
                when lower({{ platform_channel }}) in ('video', 'youtube') then 'paid_social'
                else 'paid_search'  -- Default for Google Ads
            end

        -- TikTok Ads: All paid social
        when {{ source }} = 'tiktok_ads' then 'paid_social'

        -- Pinterest Ads: Differentiate shopping vs social
        when {{ source }} = 'pinterest_ads' then
            case
                when lower({{ platform_channel }}) like '%shopping%' then 'paid_shopping'
                when lower({{ platform_channel }}) like '%catalog%' then 'paid_shopping'
                else 'paid_social'
            end

        -- Snap Ads: All paid social
        when {{ source }} = 'snap_ads' then 'paid_social'

        -- Amazon Ads: All paid shopping/marketplace
        when {{ source }} = 'amazon_ads' then 'paid_shopping'

        -- Klaviyo: All email
        when {{ source }} = 'klaviyo' then 'email'

        -- Shopify Email: All email
        when {{ source }} = 'shopify_email' then 'email'

        -- SMS Marketing Platforms
        when {{ source }} = 'attentive' then 'sms'
        when {{ source }} = 'postscript' then 'sms'
        when {{ source }} = 'smsbump' then 'sms'

        -- GA4: Requires UTM/source analysis
        when {{ source }} = 'ga4' then
            case
                when lower({{ platform_channel }}) in ('organic', 'organic search', '(organic)') then 'organic_search'
                when lower({{ platform_channel }}) in ('direct', '(direct)', '(none)') then 'direct'
                when lower({{ platform_channel }}) in ('referral') then 'referral'
                when lower({{ platform_channel }}) in ('email', 'newsletter') then 'email'
                when lower({{ platform_channel }}) in ('social', 'organic social') then 'organic_social'
                when lower({{ platform_channel }}) in ('cpc', 'ppc', 'paid search') then 'paid_search'
                when lower({{ platform_channel }}) in ('paid social', 'paidsocial') then 'paid_social'
                when lower({{ platform_channel }}) in ('affiliate') then 'affiliate'
                else 'other'
            end

        -- Shopify: Order source analysis
        when {{ source }} = 'shopify' then
            case
                when lower({{ platform_channel }}) like '%email%' then 'email'
                when lower({{ platform_channel }}) like '%direct%' then 'direct'
                when lower({{ platform_channel }}) like '%organic%' then 'organic_search'
                when lower({{ platform_channel }}) like '%social%' then 'organic_social'
                when lower({{ platform_channel }}) like '%referral%' then 'referral'
                else 'direct'  -- Default for Shopify orders
            end

        -- Recharge: Subscription/recurring - typically from existing customers
        when {{ source }} = 'recharge' then 'direct'

        -- Unknown source: Default to other
        else 'other'
    end
{% endmacro %}


{% macro get_canonical_channel_values() %}
    {#
    Returns the list of valid canonical channel values.
    Used for accepted_values tests in schema.yml.
    #}
    {{ return(['paid_social', 'paid_search', 'paid_shopping', 'email', 'sms', 'organic_social', 'organic_search', 'direct', 'referral', 'affiliate', 'other']) }}
{% endmacro %}
