"""
Root test configuration and fixtures.

Provides database fixtures that can be used by all tests.
E2E tests have additional fixtures in e2e/conftest.py.

Story 2.3 shared fixtures:
- temp_config_dir: Temporary directory for YAML config files
- make_yaml_config: Factory for writing YAML configs to temp dir
"""

import os
import tempfile
import uuid
import pytest
import yaml
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ.setdefault("ENV", "test")


@pytest.fixture(scope="session", autouse=True)
def _httpx_app_kwarg_patch():
    """
    Compatibility patch for httpx>=0.28 where Client(app=...) is not supported.

    Starlette's TestClient (used by FastAPI) passes app= into httpx.Client.
    This patch removes the app kwarg to avoid TypeError in environments
    with newer httpx while remaining safe for older versions.
    """
    import httpx

    original_init = httpx.Client.__init__

    def patched_init(self, *args, **kwargs):
        kwargs.pop("app", None)
        return original_init(self, *args, **kwargs)

    httpx.Client.__init__ = patched_init
    try:
        yield
    finally:
        httpx.Client.__init__ = original_init


def _get_test_database_url() -> str:
    """Get database URL for tests."""
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        # Handle Render's postgres:// URL format
        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql://", 1)
        return database_url

    # Default to SQLite for unit tests if no PostgreSQL available
    return "sqlite:///:memory:"


def _is_postgres() -> bool:
    """Check if using PostgreSQL."""
    url = _get_test_database_url()
    return url.startswith("postgresql")


@pytest.fixture(scope="session")
def db_engine():
    """
    Create database engine for tests.

    Uses PostgreSQL if DATABASE_URL is set, otherwise SQLite in-memory.
    """
    database_url = _get_test_database_url()

    if _is_postgres():
        try:
            engine = create_engine(database_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as e:
            pytest.skip(
                f"PostgreSQL not available. Set DATABASE_URL or use SQLite. Error: {e}"
            )
    else:
        # SQLite in-memory for fast unit tests
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    # Import and create all tables
    from src.db_base import Base
    from src.models import user, tenant, organization, user_tenant_roles, tenant_invite
    from src.models import dashboard_metric_binding  # noqa: F401 - Story 2.3
    from src.models import connector_credential  # noqa: F401 - Credential Vault
    from src.models import connection_consent  # noqa: F401 - Consent Flow
    from src.models import explore_guardrail_exception  # noqa: F401 - Story 5.4
    from src.models import role, user_role_assignment  # noqa: F401 - Story 5.5.1
    from src.models import agency_access_request  # noqa: F401 - Story 5.5.2
    from src.models import access_revocation  # noqa: F401 - Story 5.5.4
    from src.platform import audit  # noqa: F401 - Audit log model
    # Custom Reports & Dashboard Builder models
    from src.models import report_template  # noqa: F401
    from src.models import custom_dashboard  # noqa: F401
    from src.models import custom_report  # noqa: F401
    from src.models import dashboard_version  # noqa: F401
    from src.models import dashboard_share  # noqa: F401
    from src.models import dashboard_audit  # noqa: F401

    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator[Session, None, None]:
    """
    Create database session with transaction rollback for test isolation.

    Each test gets a fresh session that rolls back after the test completes.
    """
    connection = db_engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = SessionLocal()

    if _is_postgres():
        # Use savepoints for PostgreSQL
        nested = connection.begin_nested()

        @event.listens_for(session, "after_transaction_end")
        def restart_savepoint(session, transaction):
            nonlocal nested
            if transaction.nested and not transaction._parent.nested:
                nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# Alias for backwards compatibility
@pytest.fixture
def test_db_session(db_session):
    """Alias for db_session fixture."""
    return db_session


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test")
    config.addinivalue_line("markers", "security: mark test as security-focused")
    config.addinivalue_line("markers", "slow: mark test as slow-running")


# =============================================================================
# Story 2.3 - Shared Config Fixtures
# =============================================================================


@pytest.fixture
def temp_config_dir():
    """Create a temporary directory for YAML config files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def make_yaml_config(temp_config_dir):
    """
    Factory fixture that writes a YAML config file and returns its path.

    Usage:
        config_path = make_yaml_config("consumers.yaml", {"dashboards": {...}})
    """
    def _make(filename: str, config: dict) -> Path:
        config_path = temp_config_dir / filename
        with open(config_path, "w") as f:
            yaml.dump(config, f)
        return config_path
    return _make
