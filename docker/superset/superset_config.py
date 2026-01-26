import os
from datetime import timedelta

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
FEATURE_FLAGS = {
    'EMBEDDED_SUPERSET': True,
    'ENABLE_SUPERSET_META_DB_COMMENTS': True,
    'SQLLAB_BACKEND_PERSISTENCE': False,
}

# Disable SQL Lab
SQLLAB_QUERY_COST_ESTIMATE_ENABLED = False
SQL_MAX_ROW = 100000  # Row limit
SQLLAB_ASYNC_TIME_LIMIT_SEC = 30  # Query timeout (30 seconds)

# Disable dataset creation for non-admins
ALLOWED_USER_CSV_UPLOAD = False

# Cache Configuration (Redis)
CACHE_CONFIG = {
    'CACHE_TYPE': 'RedisCache',
    'CACHE_REDIS_URL': os.getenv('REDIS_URL', 'redis://redis:6379/0'),
    'CACHE_DEFAULT_TIMEOUT': 3600,  # 1 hour TTL
}

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

# Webserver Timeout
SUPERSET_WEBSERVER_TIMEOUT = 60

# Public role disabled (no public dashboards)
PUBLIC_ROLE_LIKE_GAMMA = False

# Allow only HTTPS connections
TALISMAN_ENABLED = True
TALISMAN_CONFIG = {
    'force_https': True,
    'strict_transport_security': True,
    'strict_transport_security_max_age': 31536000,
}
