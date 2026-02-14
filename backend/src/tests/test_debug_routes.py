"""
Tests for debug endpoint production gating.

Debug endpoints expose env var prefixes, JWKS key IDs, and decoded JWTs.
They MUST return 404 in production to prevent information leakage.
"""

import os
from unittest.mock import patch

import pytest


def _get_client():
    """Create a TestClient for the app."""
    from fastapi.testclient import TestClient
    import importlib
    main = importlib.import_module("main")
    return TestClient(main.app)


class TestDebugEnvStatus:
    """Tests for /debug/env-status endpoint."""

    def test_blocked_in_production(self):
        with patch.dict(os.environ, {"ENV": "production"}):
            client = _get_client()
            resp = client.get("/debug/env-status")
            assert resp.status_code == 404

    def test_allowed_in_development(self):
        with patch.dict(os.environ, {"ENV": "development"}):
            client = _get_client()
            resp = client.get("/debug/env-status")
            assert resp.status_code == 200

    def test_allowed_when_env_unset(self):
        env = os.environ.copy()
        env.pop("ENV", None)
        with patch.dict(os.environ, env, clear=True):
            client = _get_client()
            resp = client.get("/debug/env-status")
            assert resp.status_code == 200


class TestDebugAuthCheck:
    """Tests for /debug/auth-check endpoint."""

    def test_blocked_in_production(self):
        with patch.dict(os.environ, {"ENV": "production"}):
            client = _get_client()
            resp = client.get("/debug/auth-check")
            assert resp.status_code == 404

    def test_allowed_in_staging(self):
        with patch.dict(os.environ, {"ENV": "staging"}):
            client = _get_client()
            resp = client.get("/debug/auth-check")
            # May fail JWKS fetch without CLERK_FRONTEND_API, but shouldn't 404
            assert resp.status_code != 404
