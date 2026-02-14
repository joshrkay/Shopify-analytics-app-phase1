"""
Test that all API routes follow the /api/ prefix convention.

The TenantContextMiddleware exempts paths that do NOT start with /api/ from
JWT verification. Any API route without the /api/ prefix bypasses auth entirely.
This test catches that class of bug at CI time.
"""

import pytest
from starlette.routing import Mount


def _get_app():
    """Import the app lazily so test collection doesn't fail if deps are missing."""
    import importlib
    main = importlib.import_module("main")
    return main.app


# Paths that are intentionally exempt from the /api/ prefix convention.
EXEMPT_EXACT = {"/", "/health", "/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"}
EXEMPT_PREFIXES = ("/debug/",)


class TestRoutePrefix:
    """Ensure every non-exempt route starts with /api/."""

    def test_all_api_routes_have_prefix(self):
        app = _get_app()

        violations = []
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path:
                continue

            # Skip exempt paths
            if path in EXEMPT_EXACT:
                continue
            if any(path.startswith(p) for p in EXEMPT_PREFIXES):
                continue

            # Skip Mount (StaticFiles, sub-apps) — only check APIRoute
            if isinstance(route, Mount):
                continue

            # The catch-all SPA route /{full_path:path} is exempt
            if "{full_path" in path:
                continue

            if not path.startswith("/api/"):
                violations.append(path)

        assert violations == [], (
            f"Routes missing /api/ prefix (bypasses auth): {violations}"
        )

    def test_agency_routes_have_api_prefix(self):
        """Regression: agency routes previously used /agency/ without /api/."""
        app = _get_app()

        agency_routes = [
            getattr(r, "path", "")
            for r in app.routes
            if "agency" in getattr(r, "path", "")
        ]
        for path in agency_routes:
            assert path.startswith("/api/"), (
                f"Agency route {path} must start with /api/"
            )

    def test_auth_refresh_route_has_api_prefix(self):
        """Regression: auth/refresh-jwt previously used /auth/ without /api/."""
        app = _get_app()

        auth_routes = [
            getattr(r, "path", "")
            for r in app.routes
            if "refresh-jwt" in getattr(r, "path", "")
        ]
        assert len(auth_routes) > 0, "Expected /api/auth/refresh-jwt route to exist"
        for path in auth_routes:
            assert path.startswith("/api/"), (
                f"Auth route {path} must start with /api/"
            )
