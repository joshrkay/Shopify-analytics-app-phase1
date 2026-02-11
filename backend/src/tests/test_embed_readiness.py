"""Tests for embed readiness endpoint."""

import os
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes.embed import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)


def _restore_env(old_secret, old_url, old_dashboards):
    if old_secret is None:
        os.environ.pop('SUPERSET_JWT_SECRET', None)
    else:
        os.environ['SUPERSET_JWT_SECRET'] = old_secret

    if old_url is None:
        os.environ.pop('SUPERSET_EMBED_URL', None)
    else:
        os.environ['SUPERSET_EMBED_URL'] = old_url

    if old_dashboards is None:
        os.environ.pop('ALLOWED_EMBED_DASHBOARDS', None)
    else:
        os.environ['ALLOWED_EMBED_DASHBOARDS'] = old_dashboards


def test_embed_readiness_ready_when_all_env_present():
    old_secret = os.environ.get('SUPERSET_JWT_SECRET')
    old_url = os.environ.get('SUPERSET_EMBED_URL')
    old_dashboards = os.environ.get('ALLOWED_EMBED_DASHBOARDS')

    os.environ['SUPERSET_JWT_SECRET'] = 'secret'
    os.environ['SUPERSET_EMBED_URL'] = 'https://analytics.example.com'
    os.environ['ALLOWED_EMBED_DASHBOARDS'] = 'overview,sales'

    try:
        response = client.get('/api/v1/embed/health/readiness')
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'ready'
        assert body['embed_configured'] is True
        assert body['superset_url_configured'] is True
        assert body['allowed_dashboards_configured'] is True
    finally:
        _restore_env(old_secret, old_url, old_dashboards)


def test_embed_readiness_not_ready_when_dashboards_missing():
    old_secret = os.environ.get('SUPERSET_JWT_SECRET')
    old_url = os.environ.get('SUPERSET_EMBED_URL')
    old_dashboards = os.environ.get('ALLOWED_EMBED_DASHBOARDS')

    os.environ['SUPERSET_JWT_SECRET'] = 'secret'
    os.environ['SUPERSET_EMBED_URL'] = 'https://analytics.example.com'
    os.environ['ALLOWED_EMBED_DASHBOARDS'] = ''

    try:
        response = client.get('/api/v1/embed/health/readiness')
        assert response.status_code == 200
        body = response.json()
        assert body['status'] == 'not_ready'
        assert body['message'] == 'ALLOWED_EMBED_DASHBOARDS not configured'
        assert body['allowed_dashboards_configured'] is False
    finally:
        _restore_env(old_secret, old_url, old_dashboards)
