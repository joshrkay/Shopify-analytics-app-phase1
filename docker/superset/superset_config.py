import os
from datetime import timedelta

# Import Explore Guardrails
from explore_guardrails import (
    PERFORMANCE_GUARDRAILS,
    EXPLORE_FEATURE_FLAGS,
    ExploreGuardrailEnforcer,
)

# Flask App Configuration
SECRET_KEY = os.getenv('SUPERSET_SECRET_KEY')
SQLALCHEMY_DATABASE_URI = os.getenv(
    'SUPERSET_METADATA_DB_URI',
    'postgresql://user:password@postgres:5432/superset'
)

# Security & HTTPS
PREFERRED_URL_SCHEME = 'https'
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
WTF_CSRF_CHECK_DEFAULT = True

# Security Headers (HSTS, CSP, X-Frame-Options)
HTTP_HEADERS = {
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'X-Frame-Options': 'DENY',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "frame-ancestors 'self' https://admin.shopify.com",
    'Referrer-Policy': 'strict-origin',
}

# JWT Embedded Authentication
SUPERSET_JWT_SECRET = os.getenv('SUPERSET_JWT_SECRET_CURRENT')
SUPERSET_JWT_SECRET_PREVIOUS = os.getenv('SUPERSET_JWT_SECRET_PREVIOUS')

# Feature Flags
# Base flags merged with Explore guardrail flags
_BASE_FEATURE_FLAGS = {
    'EMBEDDED_SUPERSET': True,
    'ENABLE_SUPERSET_META_DB_COMMENTS': True,
    'SQLLAB_BACKEND_PERSISTENCE': False,
}

# Merge with Explore guardrail feature flags
FEATURE_FLAGS = {**_BASE_FEATURE_FLAGS, **EXPLORE_FEATURE_FLAGS}

# Disable SQL Lab
SQLLAB_QUERY_COST_ESTIMATE_ENABLED = False

# =============================================================================
# EXPLORE MODE GUARDRAILS
# These limits are enforced for all Explore mode queries
# =============================================================================
SQL_MAX_ROW = PERFORMANCE_GUARDRAILS.row_limit  # 50,000 rows max
ROW_LIMIT = PERFORMANCE_GUARDRAILS.row_limit
SQLLAB_ASYNC_TIME_LIMIT_SEC = PERFORMANCE_GUARDRAILS.query_timeout_seconds  # 20 seconds
SQLLAB_TIMEOUT = PERFORMANCE_GUARDRAILS.query_timeout_seconds

# Explore-specific restrictions
EXPLORE_ROW_LIMIT = PERFORMANCE_GUARDRAILS.row_limit
SAMPLES_ROW_LIMIT = 1000  # Limit sample data preview

# Disable data export features
ALLOW_FILE_EXPORT = False
ENABLE_PIVOT_TABLE_DATA_EXPORT = False
CSV_EXPORT = False

# Disable dataset creation for non-admins
ALLOWED_USER_CSV_UPLOAD = False

# Cache Configuration (Redis)
# Explore mode uses 30-minute TTL for fresh data visibility
EXPLORE_CACHE_TTL = PERFORMANCE_GUARDRAILS.cache_ttl_minutes * 60  # 30 min in seconds

CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://redis:6379/0'),
    'CACHE_DEFAULT_TIMEOUT': EXPLORE_CACHE_TTL,  # 30 minutes for Explore
    'CACHE_REDIS_DB': 0,
    'CACHE_REDIS_SOCKET_CONNECT_TIMEOUT': 5,
    'CACHE_REDIS_SOCKET_TIMEOUT': 5,
}

# Data cache for Explore queries
DATA_CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://redis:6379/0'),
    'CACHE_DEFAULT_TIMEOUT': EXPLORE_CACHE_TTL,
    'CACHE_KEY_PREFIX': 'explore_data_',
}

# Cache Invalidation Strategy
# TTL-based: 30 minute timeout for Explore data freshness
# Manual: triggered by dbt deploy or dashboard refresh button

# Performance Indices (to be created in PostgreSQL for optimal query performance)
# Expected improvement: ~5s -> ~200-300ms for date-based queries
# CREATE INDEX IF NOT EXISTS idx_orders_tenant_date ON fact_orders (tenant_id, order_date);
# CREATE INDEX IF NOT EXISTS idx_spend_tenant_channel ON fact_marketing_spend (tenant_id, channel);
# CREATE INDEX IF NOT EXISTS idx_campaign_performance_tenant ON fact_campaign_performance (tenant_id, campaign_id);

# Session Configuration
PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
SESSION_REFRESH_EACH_REQUEST = True

# Logging Configuration
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default'],
            'level': 'INFO',
            'propagate': True
        }
    }
}

# Datadog APM Integration
DATADOG_ENABLED = os.getenv('DATADOG_ENABLED', 'false').lower() == 'true'
if DATADOG_ENABLED:
    DATADOG_TRACE_ENABLED = True
    DATADOG_SERVICE_NAME = 'superset-analytics'

# Webserver Timeout (query timeout + processing buffer)
SUPERSET_WEBSERVER_TIMEOUT = PERFORMANCE_GUARDRAILS.query_timeout_seconds + 10

# Public role disabled (no public dashboards)
PUBLIC_ROLE_LIKE_GAMMA = False

# Allow only HTTPS connections
TALISMAN_ENABLED = True
TALISMAN_CONFIG = {
    'force_https': True,
    'strict_transport_security': True,
    'strict_transport_security_max_age': 31536000,
}

# =============================================================================
# EXPLORE MODE GUARDRAILS SUMMARY
# =============================================================================
# The following guardrails are enforced for all Explore mode queries:
#
# | Guardrail              | Value       | Enforcement                    |
# |------------------------|-------------|--------------------------------|
# | Max date range         | 90 days     | ExplorePermissionValidator     |
# | Query timeout          | 20 seconds  | SQLLAB_ASYNC_TIME_LIMIT_SEC    |
# | Row limit              | 50,000      | SQL_MAX_ROW / ROW_LIMIT        |
# | Max group-by dims      | 2           | ExplorePermissionValidator     |
# | Cache TTL              | 30 minutes  | CACHE_DEFAULT_TIMEOUT          |
#
# Disabled Features:
# - Custom SQL queries (SQL_QUERIES_ALLOWED = False)
# - Custom metrics (ENABLE_CUSTOM_METRICS = False)
# - Data export (CSV_EXPORT = False, ALLOW_FILE_EXPORT = False)
# - Ad-hoc subqueries (ALLOW_ADHOC_SUBQUERY = False)
#
# See explore_guardrails.py for full implementation details.
# =============================================================================
