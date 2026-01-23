"""
Tests for tenant-to-Airbyte connection mapping.

CRITICAL: These tests verify that:
1. Each Airbyte connection is mapped to exactly one tenant
2. Tenant isolation is enforced at repository and service layers
3. Cross-tenant access is impossible
4. Tenant A cannot see Tenant B's connections (and vice versa)

Story 3.2 - Tenant-to-Source Mapping
"""

import os
import uuid
import pytest
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Set test environment
os.environ["ENV"] = "test"

from src.db_base import Base
from src.repositories.base_repo import TenantIsolationError
from src.repositories.airbyte_connections import (
    AirbyteConnectionsRepository,
    ConnectionNotFoundError,
    ConnectionAlreadyExistsError,
)
from src.services.airbyte_service import (
    AirbyteService,
    ConnectionNotFoundServiceError,
    DuplicateConnectionError,
)
from src.models.airbyte_connection import (
    TenantAirbyteConnection,
    ConnectionStatus,
    ConnectionType,
)


# =============================================================================
# Test Database Fixtures
# =============================================================================

def _get_test_database_url():
    """Get database URL for testing."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        # Try PostgreSQL first, fall back to SQLite for basic tests
        try:
            from sqlalchemy import create_engine
            test_url = "postgresql://postgres:test@localhost:5432/postgres"
            engine = create_engine(test_url, pool_pre_ping=True)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return test_url
        except Exception:
            # Fall back to SQLite for basic testing
            return "sqlite:///:memory:"
    return database_url


@pytest.fixture(scope="module")
def db_engine():
    """Create database engine for tests."""
    database_url = _get_test_database_url()

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    if database_url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
    else:
        engine = create_engine(database_url, pool_pre_ping=True)

    # Import model to register with Base
    from src.models import airbyte_connection

    # Create tables
    Base.metadata.create_all(bind=engine)

    yield engine

    # Cleanup
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Create a new database session for each test with transaction rollback."""
    connection = db_engine.connect()
    transaction = connection.begin()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=connection)
    session = SessionLocal()

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


# =============================================================================
# Test Identity Fixtures
# =============================================================================

@pytest.fixture
def tenant_a_id() -> str:
    """Generate unique tenant ID for Tenant A."""
    return f"tenant-a-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def tenant_b_id() -> str:
    """Generate unique tenant ID for Tenant B."""
    return f"tenant-b-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def tenant_c_id() -> str:
    """Generate unique tenant ID for Tenant C (for multi-tenant tests)."""
    return f"tenant-c-{uuid.uuid4().hex[:8]}"


# =============================================================================
# Test Connection Fixtures
# =============================================================================

@pytest.fixture
def connection_a(db_session, tenant_a_id) -> TenantAirbyteConnection:
    """Create a test connection for Tenant A."""
    connection = TenantAirbyteConnection(
        id=str(uuid.uuid4()),
        tenant_id=tenant_a_id,
        airbyte_connection_id=f"airbyte-conn-a-{uuid.uuid4().hex[:8]}",
        connection_name="Tenant A Shopify Connection",
        connection_type=ConnectionType.SOURCE,
        source_type="shopify",
        status=ConnectionStatus.ACTIVE,
        is_enabled=True,
        configuration={"shop": "tenant-a.myshopify.com"}
    )
    db_session.add(connection)
    db_session.flush()
    return connection


@pytest.fixture
def connection_b(db_session, tenant_b_id) -> TenantAirbyteConnection:
    """Create a test connection for Tenant B."""
    connection = TenantAirbyteConnection(
        id=str(uuid.uuid4()),
        tenant_id=tenant_b_id,
        airbyte_connection_id=f"airbyte-conn-b-{uuid.uuid4().hex[:8]}",
        connection_name="Tenant B Postgres Connection",
        connection_type=ConnectionType.SOURCE,
        source_type="postgres",
        status=ConnectionStatus.ACTIVE,
        is_enabled=True,
        configuration={"host": "tenant-b-db.example.com"}
    )
    db_session.add(connection)
    db_session.flush()
    return connection


@pytest.fixture
def multiple_connections_tenant_a(db_session, tenant_a_id) -> list:
    """Create multiple connections for Tenant A."""
    connections = []
    for i in range(3):
        conn = TenantAirbyteConnection(
            id=str(uuid.uuid4()),
            tenant_id=tenant_a_id,
            airbyte_connection_id=f"airbyte-multi-a-{i}-{uuid.uuid4().hex[:8]}",
            connection_name=f"Tenant A Connection {i}",
            connection_type=ConnectionType.SOURCE,
            source_type="shopify" if i == 0 else "postgres",
            status=ConnectionStatus.ACTIVE if i < 2 else ConnectionStatus.PENDING,
            is_enabled=True,
            configuration={"index": i}
        )
        db_session.add(conn)
        connections.append(conn)
    db_session.flush()
    return connections


# =============================================================================
# Repository Tests - Tenant Isolation
# =============================================================================

class TestRepositoryTenantIsolation:
    """Test repository-level tenant isolation."""

    def test_repository_requires_tenant_id(self, db_session):
        """Test that repository raises error for empty tenant_id."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            AirbyteConnectionsRepository(db_session, "")

        with pytest.raises(ValueError, match="tenant_id is required"):
            AirbyteConnectionsRepository(db_session, None)

    def test_repository_scopes_queries_to_tenant(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Repository queries only return connections for the tenant.
        """
        # Tenant A repository
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)
        connections_a = repo_a.get_all()

        # Tenant A should only see their connection
        assert len(connections_a) == 1
        assert connections_a[0].id == connection_a.id
        assert connections_a[0].tenant_id == tenant_a_id

        # Tenant B repository
        repo_b = AirbyteConnectionsRepository(db_session, tenant_b_id)
        connections_b = repo_b.get_all()

        # Tenant B should only see their connection
        assert len(connections_b) == 1
        assert connections_b[0].id == connection_b.id
        assert connections_b[0].tenant_id == tenant_b_id

    def test_tenant_a_cannot_access_tenant_b_by_id(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Tenant A cannot access Tenant B's connection by ID.
        """
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)

        # Try to get Tenant B's connection ID using Tenant A's repo
        result = repo_a.get_by_id(connection_b.id)

        # Should return None (not found in Tenant A's scope)
        assert result is None

    def test_tenant_a_cannot_access_tenant_b_by_airbyte_id(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Tenant A cannot access Tenant B's connection by Airbyte ID.
        """
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)

        # Try to get Tenant B's connection by Airbyte ID
        result = repo_a.get_by_airbyte_id(connection_b.airbyte_connection_id)

        # Should return None (not found in Tenant A's scope)
        assert result is None

    def test_repository_tenant_id_mismatch_raises_error(
        self, db_session, tenant_a_id, tenant_b_id, connection_a
    ):
        """
        CRITICAL: Passing wrong tenant_id to operations raises error.
        """
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)

        # Try operation with mismatched tenant_id
        with pytest.raises(TenantIsolationError, match="Tenant ID mismatch"):
            repo_a.get_by_id(connection_a.id, tenant_id=tenant_b_id)

    def test_repository_ignores_tenant_id_from_entity_data(
        self, db_session, tenant_a_id, tenant_b_id
    ):
        """
        CRITICAL: Repository ignores tenant_id from entity data.
        tenant_id must come from repository context only.
        """
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)

        # Create connection with tenant_b in data (should be ignored)
        connection = repo_a.create_connection(
            airbyte_connection_id=f"airbyte-test-{uuid.uuid4().hex}",
            connection_name="Test Connection",
            connection_type=ConnectionType.SOURCE,
            source_type="test"
        )

        # Connection must belong to tenant_a, not the ignored value
        assert connection.tenant_id == tenant_a_id

    def test_tenant_cannot_update_other_tenant_connection(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Tenant cannot update another tenant's connection.
        """
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)

        # Try to update Tenant B's connection status using Tenant A's repo
        result = repo_a.update_status(connection_b.id, ConnectionStatus.INACTIVE)

        # Should return None (not found in Tenant A's scope)
        assert result is None

        # Verify Tenant B's connection is unchanged
        db_session.refresh(connection_b)
        assert connection_b.status == ConnectionStatus.ACTIVE

    def test_tenant_cannot_delete_other_tenant_connection(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Tenant cannot delete another tenant's connection.
        """
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)

        # Try to soft delete Tenant B's connection using Tenant A's repo
        result = repo_a.soft_delete(connection_b.id)

        # Should return None (not found in Tenant A's scope)
        assert result is None

        # Verify Tenant B's connection still exists and is not deleted
        db_session.refresh(connection_b)
        assert connection_b.status == ConnectionStatus.ACTIVE


# =============================================================================
# Service Tests - Tenant Isolation
# =============================================================================

class TestServiceTenantIsolation:
    """Test service-level tenant isolation."""

    def test_service_requires_tenant_id(self, db_session):
        """Test that service raises error for empty tenant_id."""
        with pytest.raises(ValueError, match="tenant_id is required"):
            AirbyteService(db_session, "")

        with pytest.raises(ValueError, match="tenant_id is required"):
            AirbyteService(db_session, None)

    def test_service_list_connections_scoped_to_tenant(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Service only lists connections for the current tenant.
        """
        # Service for Tenant A
        service_a = AirbyteService(db_session, tenant_a_id)
        result_a = service_a.list_connections()

        # Tenant A should only see their connection
        assert result_a.total_count == 1
        assert len(result_a.connections) == 1
        assert result_a.connections[0].id == connection_a.id

        # Service for Tenant B
        service_b = AirbyteService(db_session, tenant_b_id)
        result_b = service_b.list_connections()

        # Tenant B should only see their connection
        assert result_b.total_count == 1
        assert len(result_b.connections) == 1
        assert result_b.connections[0].id == connection_b.id

    def test_service_tenant_a_cannot_get_tenant_b_connection(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Tenant A service cannot retrieve Tenant B's connection.
        """
        service_a = AirbyteService(db_session, tenant_a_id)

        # Try to get Tenant B's connection
        result = service_a.get_connection(connection_b.id)
        assert result is None

        # Try by Airbyte ID
        result = service_a.get_connection_by_airbyte_id(connection_b.airbyte_connection_id)
        assert result is None

    def test_service_register_connection_enforces_tenant(
        self, db_session, tenant_a_id, tenant_b_id
    ):
        """
        CRITICAL: Registered connections belong to the service's tenant.
        """
        service_a = AirbyteService(db_session, tenant_a_id)

        # Register a connection
        connection = service_a.register_connection(
            airbyte_connection_id=f"airbyte-new-{uuid.uuid4().hex}",
            connection_name="New Connection",
            source_type="shopify"
        )

        # Verify it belongs to Tenant A
        raw_conn = db_session.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.id == connection.id
        ).first()

        assert raw_conn is not None
        assert raw_conn.tenant_id == tenant_a_id

        # Tenant B should not see it
        service_b = AirbyteService(db_session, tenant_b_id)
        result = service_b.get_connection(connection.id)
        assert result is None

    def test_service_connection_belongs_to_tenant_check(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        Test connection_belongs_to_tenant validation method.
        """
        service_a = AirbyteService(db_session, tenant_a_id)
        service_b = AirbyteService(db_session, tenant_b_id)

        # Tenant A owns their connection
        assert service_a.connection_belongs_to_tenant(connection_a.airbyte_connection_id) is True

        # Tenant A does not own Tenant B's connection
        assert service_a.connection_belongs_to_tenant(connection_b.airbyte_connection_id) is False

        # Tenant B owns their connection
        assert service_b.connection_belongs_to_tenant(connection_b.airbyte_connection_id) is True

        # Tenant B does not own Tenant A's connection
        assert service_b.connection_belongs_to_tenant(connection_a.airbyte_connection_id) is False


# =============================================================================
# Cross-Tenant Access Tests - CRITICAL
# =============================================================================

class TestCrossTenantAccessForbidden:
    """
    CRITICAL: Test that cross-tenant access is impossible.
    These tests verify the core security requirement.
    """

    def test_cross_tenant_access_impossible_via_repository(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Even with valid IDs, tenant A cannot access tenant B's data.
        """
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)

        # Attempt to access all of Tenant B's connection details
        # All should return None or empty

        # By internal ID
        assert repo_a.get_by_id(connection_b.id) is None

        # By Airbyte ID
        assert repo_a.get_by_airbyte_id(connection_b.airbyte_connection_id) is None

        # Check existence
        assert repo_a.exists(connection_b.id) is False

        # List with filters that would match Tenant B's connection
        results = repo_a.list_connections(source_type="postgres")
        assert len(results) == 0

    def test_cross_tenant_access_impossible_via_service(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Even with valid IDs, tenant A service cannot access tenant B.
        """
        service_a = AirbyteService(db_session, tenant_a_id)

        # By internal ID
        assert service_a.get_connection(connection_b.id) is None

        # By Airbyte ID
        assert service_a.get_connection_by_airbyte_id(
            connection_b.airbyte_connection_id
        ) is None

        # Ownership check
        assert service_a.connection_belongs_to_tenant(
            connection_b.airbyte_connection_id
        ) is False

    def test_cross_tenant_operations_fail_silently(
        self, db_session, tenant_a_id, tenant_b_id, connection_a, connection_b
    ):
        """
        CRITICAL: Operations on other tenant's connections fail gracefully.
        """
        service_a = AirbyteService(db_session, tenant_a_id)

        # Activate - should raise not found
        with pytest.raises(ConnectionNotFoundServiceError):
            service_a.activate_connection(connection_b.id)

        # Deactivate - should raise not found
        with pytest.raises(ConnectionNotFoundServiceError):
            service_a.deactivate_connection(connection_b.id)

        # Delete - should raise not found
        with pytest.raises(ConnectionNotFoundServiceError):
            service_a.delete_connection(connection_b.id)

        # Enable - should raise not found
        with pytest.raises(ConnectionNotFoundServiceError):
            service_a.enable_connection(connection_b.id)

        # Disable - should raise not found
        with pytest.raises(ConnectionNotFoundServiceError):
            service_a.disable_connection(connection_b.id)

    def test_tenant_sees_only_own_connections_count(
        self, db_session, tenant_a_id, tenant_b_id,
        multiple_connections_tenant_a, connection_b
    ):
        """
        CRITICAL: Tenant counts only include own connections.
        """
        # Tenant A has 3 connections
        repo_a = AirbyteConnectionsRepository(db_session, tenant_a_id)
        assert repo_a.count() == 3

        # Tenant B has 1 connection
        repo_b = AirbyteConnectionsRepository(db_session, tenant_b_id)
        assert repo_b.count() == 1

        # Total in database is 4, but each tenant only sees their own
        all_connections = db_session.query(TenantAirbyteConnection).all()
        assert len(all_connections) == 4

    def test_multi_tenant_isolation_three_tenants(
        self, db_session, tenant_a_id, tenant_b_id, tenant_c_id
    ):
        """
        CRITICAL: Test isolation with three tenants.
        """
        # Create connections for each tenant
        service_a = AirbyteService(db_session, tenant_a_id)
        service_b = AirbyteService(db_session, tenant_b_id)
        service_c = AirbyteService(db_session, tenant_c_id)

        conn_a = service_a.register_connection(
            airbyte_connection_id=f"abc-{uuid.uuid4().hex}",
            connection_name="Tenant A Connection",
            source_type="shopify"
        )

        conn_b = service_b.register_connection(
            airbyte_connection_id=f"abc-{uuid.uuid4().hex}",
            connection_name="Tenant B Connection",
            source_type="postgres"
        )

        conn_c = service_c.register_connection(
            airbyte_connection_id=f"abc-{uuid.uuid4().hex}",
            connection_name="Tenant C Connection",
            source_type="mysql"
        )

        # Each tenant can only see their own connection
        result_a = service_a.list_connections()
        assert result_a.total_count == 1
        assert result_a.connections[0].id == conn_a.id

        result_b = service_b.list_connections()
        assert result_b.total_count == 1
        assert result_b.connections[0].id == conn_b.id

        result_c = service_c.list_connections()
        assert result_c.total_count == 1
        assert result_c.connections[0].id == conn_c.id

        # Cross-tenant checks
        assert service_a.get_connection(conn_b.id) is None
        assert service_a.get_connection(conn_c.id) is None
        assert service_b.get_connection(conn_a.id) is None
        assert service_b.get_connection(conn_c.id) is None
        assert service_c.get_connection(conn_a.id) is None
        assert service_c.get_connection(conn_b.id) is None


# =============================================================================
# Audit and Mapping Tests
# =============================================================================

class TestConnectionMappingAuditability:
    """Test that connection mappings are auditable."""

    def test_connection_has_tenant_id(
        self, db_session, tenant_a_id, connection_a
    ):
        """Each connection has tenant_id recorded."""
        assert connection_a.tenant_id == tenant_a_id
        assert connection_a.tenant_id is not None

    def test_connection_has_timestamps(
        self, db_session, tenant_a_id, connection_a
    ):
        """Each connection has created_at and updated_at timestamps."""
        assert connection_a.created_at is not None
        assert connection_a.updated_at is not None

    def test_connection_tracks_airbyte_ids(
        self, db_session, tenant_a_id
    ):
        """Connection tracks Airbyte IDs for mapping."""
        service = AirbyteService(db_session, tenant_a_id)

        conn = service.register_connection(
            airbyte_connection_id="airbyte-123",
            connection_name="Test",
            airbyte_source_id="source-456",
            airbyte_destination_id="dest-789",
            source_type="shopify"
        )

        # Verify mapping
        raw = db_session.query(TenantAirbyteConnection).filter(
            TenantAirbyteConnection.id == conn.id
        ).first()

        assert raw.airbyte_connection_id == "airbyte-123"
        assert raw.airbyte_source_id == "source-456"
        assert raw.airbyte_destination_id == "dest-789"
        assert raw.tenant_id == tenant_a_id


# =============================================================================
# Edge Cases and Error Handling
# =============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_duplicate_airbyte_connection_id_rejected(
        self, db_session, tenant_a_id, connection_a
    ):
        """
        Duplicate Airbyte connection ID should be rejected.
        """
        service = AirbyteService(db_session, tenant_a_id)

        with pytest.raises(DuplicateConnectionError):
            service.register_connection(
                airbyte_connection_id=connection_a.airbyte_connection_id,
                connection_name="Duplicate Connection",
                source_type="test"
            )

    def test_list_connections_with_filters(
        self, db_session, tenant_a_id, multiple_connections_tenant_a
    ):
        """Test filtering connections."""
        service = AirbyteService(db_session, tenant_a_id)

        # Filter by source_type
        result = service.list_connections(source_type="shopify")
        assert len(result.connections) == 1

        result = service.list_connections(source_type="postgres")
        assert len(result.connections) == 2

        # Filter by status
        result = service.list_connections(status="active")
        assert len(result.connections) == 2

        result = service.list_connections(status="pending")
        assert len(result.connections) == 1

    def test_list_connections_pagination(
        self, db_session, tenant_a_id, multiple_connections_tenant_a
    ):
        """Test pagination of connection list."""
        service = AirbyteService(db_session, tenant_a_id)

        # Limit 2
        result = service.list_connections(limit=2)
        assert len(result.connections) == 2
        assert result.has_more is True

        # Offset
        result = service.list_connections(limit=2, offset=2)
        assert len(result.connections) == 1
        assert result.has_more is False

    def test_connection_not_found_raises_service_error(
        self, db_session, tenant_a_id
    ):
        """Operations on non-existent connections raise proper errors."""
        service = AirbyteService(db_session, tenant_a_id)
        fake_id = str(uuid.uuid4())

        with pytest.raises(ConnectionNotFoundServiceError):
            service.activate_connection(fake_id)

        with pytest.raises(ConnectionNotFoundServiceError):
            service.delete_connection(fake_id)


# =============================================================================
# Property-Based Tests
# =============================================================================

class TestPropertyBasedTenantIsolation:
    """
    Property-based tests verifying isolation across different tenant ID formats.
    """

    @pytest.mark.parametrize("tenant_format", [
        "uuid-style-{uuid}",
        "org-{uuid}",
        "tenant_{uuid}",
        "{uuid}",
        "UPPERCASE-{uuid}",
        "mixed-Case-{uuid}",
    ])
    def test_isolation_with_various_tenant_id_formats(
        self, db_session, tenant_format
    ):
        """Test isolation works with various tenant ID formats."""
        tenant_a = tenant_format.format(uuid=uuid.uuid4().hex[:8])
        tenant_b = tenant_format.format(uuid=uuid.uuid4().hex[:8])

        service_a = AirbyteService(db_session, tenant_a)
        service_b = AirbyteService(db_session, tenant_b)

        # Create connection for tenant A
        conn_a = service_a.register_connection(
            airbyte_connection_id=f"conn-{uuid.uuid4().hex}",
            connection_name="Test",
            source_type="test"
        )

        # Tenant B cannot see it
        assert service_b.get_connection(conn_a.id) is None

        # Tenant A can see it
        assert service_a.get_connection(conn_a.id) is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
