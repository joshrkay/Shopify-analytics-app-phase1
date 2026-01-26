# Multi-stage build for Apache Superset 3.x
FROM python:3.11-slim as builder

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY superset/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Final stage
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

COPY superset/superset_config.py /app/
COPY superset/rls_rules.py /app/

ENV SUPERSET_HOME=/app/superset
ENV FLASK_APP=superset.app:create_app()

RUN mkdir -p $SUPERSET_HOME

# Run DB migrations on startup
CMD superset db upgrade && \
    superset init && \
    gunicorn \
    --workers 4 \
    --worker-class gevent \
    --bind 0.0.0.0:8088 \
    --timeout 60 \
    superset.app:create_app()

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8088/health || exit 1

EXPOSE 8088
