"""
Integration tests for agency and auth route prefix migration.

Verifies that:
- /api/agency/* routes exist and are reachable (not 404)
- /api/auth/refresh-jwt route exists and is reachable (not 404)
- Old unprefixed paths (/agency/*, /auth/*) do NOT match API routes

NOTE: These tests run without DATABASE_URL, so the tenant context middleware
may return 500 (DB not configured) or 503 (auth not configured). Any of
401, 403, 422, 500, 503 proves the route was matched by FastAPI — a 404
would mean the route doesn't exist.
"""

import pytest


def _get_client():
    """Create a TestClient for the app."""
    from fastapi.testclient import TestClient
    import importlib
    main = importlib.import_module("main")
    return TestClient(main.app, raise_server_exceptions=False)


# Statuses that prove a route exists and was processed by middleware/handler.
# 404 is the only status that means "route not found".
ROUTE_EXISTS_STATUSES = {401, 403, 422, 500, 503}


class TestAgencyRoutePrefix:
    """Agency routes must be at /api/agency/*, not /agency/*."""

    def test_api_agency_stores_exists(self):
        """GET /api/agency/stores should hit the agency router (not 404)."""
        client = _get_client()
        resp = client.get("/api/agency/stores")
        assert resp.status_code != 404, (
            f"Route /api/agency/stores not found (got {resp.status_code})"
        )

    def test_old_agency_stores_path_does_not_match_api(self):
        """GET /agency/stores should NOT match the agency API route."""
        client = _get_client()
        resp = client.get("/agency/stores")
        # Without the /api/ prefix, this should hit the SPA catch-all (200 HTML)
        # or return something other than an auth error.
        # It MUST NOT return 401/503 because that would mean the path is being
        # handled by the API middleware (auth bypass vulnerability).
        if resp.status_code in (401, 403, 503):
            pytest.fail(
                f"Old path /agency/stores is hitting auth middleware "
                f"(status {resp.status_code}). Route prefix migration incomplete."
            )

    def test_api_agency_me_exists(self):
        client = _get_client()
        resp = client.get("/api/agency/me")
        assert resp.status_code != 404

    def test_api_agency_store_access_exists(self):
        client = _get_client()
        resp = client.get("/api/agency/stores/test-tenant/access")
        assert resp.status_code != 404


class TestAuthRefreshRoutePrefix:
    """Auth refresh route must be at /api/auth/*, not /auth/*."""

    def test_api_auth_refresh_jwt_exists(self):
        """POST /api/auth/refresh-jwt should hit the auth router (not 404)."""
        client = _get_client()
        resp = client.post("/api/auth/refresh-jwt")
        assert resp.status_code != 404, (
            f"Route /api/auth/refresh-jwt not found (got {resp.status_code})"
        )

    def test_old_auth_path_does_not_match_api(self):
        """POST /auth/refresh-jwt should NOT match the auth API route."""
        client = _get_client()
        resp = client.post("/auth/refresh-jwt")
        if resp.status_code in (401, 403, 503):
            pytest.fail(
                f"Old path /auth/refresh-jwt is hitting auth middleware "
                f"(status {resp.status_code}). Route prefix migration incomplete."
            )
