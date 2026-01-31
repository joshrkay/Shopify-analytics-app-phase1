"""
Integration tests for shop_domain uniqueness validation.

Tests TIER 1 mitigations for OAuth data leakage prevention:
- Database unique constraint
- Application-level validation
- shop_domain normalization consistency

CRITICAL: These tests verify that duplicate shop_domains cannot be created,
preventing data leakage via DBT JOIN on shop_domain.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from src.services.airbyte_service import AirbyteService, DuplicateConnectionError
from src.models.airbyte_connection import TenantAirbyteConnection, ConnectionStatus


class TestShopDomainNormalization:
    """Test that shop_domain normalization is consistent across all layers."""

    def test_normalize_shop_domain_basic(self, db_session):
        """Test basic shop_domain normalization."""
        service = AirbyteService(db_session, "test-tenant-1")

        test_cases = [
            ("store.myshopify.com", "store.myshopify.com"),
            ("Store.myshopify.com", "store.myshopify.com"),  # Lowercase
            ("STORE.MYSHOPIFY.COM", "store.myshopify.com"),  # Uppercase
        ]

        for input_domain, expected in test_cases:
            assert service._normalize_shop_domain(input_domain) == expected

    def test_normalize_shop_domain_with_protocol(self, db_session):
        """Test normalization strips protocols."""
        service = AirbyteService(db_session, "test-tenant-1")

        test_cases = [
            ("https://store.myshopify.com", "store.myshopify.com"),
            ("http://store.myshopify.com", "store.myshopify.com"),
            ("https://Store.myshopify.com", "store.myshopify.com"),  # Combined
        ]

        for input_domain, expected in test_cases:
            assert service._normalize_shop_domain(input_domain) == expected

    def test_normalize_shop_domain_with_trailing_slash(self, db_session):
        """Test normalization strips trailing slashes."""
        service = AirbyteService(db_session, "test-tenant-1")

        test_cases = [
            ("store.myshopify.com/", "store.myshopify.com"),
            ("store.myshopify.com//", "store.myshopify.com"),
            ("https://store.myshopify.com/", "store.myshopify.com"),  # Combined
        ]

        for input_domain, expected in test_cases:
            assert service._normalize_shop_domain(input_domain) == expected

    def test_normalize_shop_domain_empty(self, db_session):
        """Test normalization handles empty strings."""
        service = AirbyteService(db_session, "test-tenant-1")

        assert service._normalize_shop_domain("") == ""
        assert service._normalize_shop_domain(None) == ""

    def test_normalize_shop_domain_complex(self, db_session):
        """Test complex normalization (all rules combined)."""
        service = AirbyteService(db_session, "test-tenant-1")

        test_cases = [
            (
                "HTTPS://STORE.myshopify.com/",
                "store.myshopify.com"
            ),
            (
                "HTTP://Test-Store-123.MYSHOPIFY.COM//",
                "test-store-123.myshopify.com"
            ),
        ]

        for input_domain, expected in test_cases:
            assert service._normalize_shop_domain(input_domain) == expected


class TestShopDomainValidation:
    """Test application-level shop_domain validation."""

    def test_validate_shop_domain_unique_success(self, db_session):
        """Test validation passes for unique shop_domain."""
        service = AirbyteService(db_session, "test-tenant-new")

        # Should not raise - shop doesn't exist yet
        service._validate_shop_domain_unique(
            shop_domain="new-unique-store.myshopify.com",
            source_type="shopify"
        )

    def test_validate_shop_domain_duplicate_different_tenant(
        self,
        db_session,
        create_test_connection
    ):
        """
        Test validation blocks duplicate shop_domain for different tenant.

        CRITICAL: This is the main data leakage prevention test.
        """
        # Tenant A creates connection with shop_domain
        tenant_a_id = "test-tenant-a"
        shop_domain = "victim-store.myshopify.com"

        create_test_connection(
            db_session,
            tenant_id=tenant_a_id,
            shop_domain=shop_domain,
            status=ConnectionStatus.ACTIVE,
        )
        db_session.commit()

        # Tenant B tries to create connection with SAME shop_domain
        tenant_b_service = AirbyteService(db_session, "test-tenant-b")

        with pytest.raises(DuplicateConnectionError) as exc_info:
            tenant_b_service._validate_shop_domain_unique(
                shop_domain=shop_domain,
                source_type="shopify"
            )

        # Verify error message is user-friendly
        assert "already connected to another account" in str(exc_info.value)
        assert shop_domain in str(exc_info.value)

    def test_validate_shop_domain_duplicate_same_tenant(
        self,
        db_session,
        create_test_connection
    ):
        """Test validation blocks duplicate connection by same tenant."""
        tenant_id = "test-tenant-same"
        shop_domain = "duplicate-store.myshopify.com"

        create_test_connection(
            db_session,
            tenant_id=tenant_id,
            shop_domain=shop_domain,
            status=ConnectionStatus.ACTIVE,
        )
        db_session.commit()

        # Same tenant tries to create another connection
        service = AirbyteService(db_session, tenant_id)

        with pytest.raises(DuplicateConnectionError) as exc_info:
            service._validate_shop_domain_unique(
                shop_domain=shop_domain,
                source_type="shopify"
            )

        # Verify error message mentions existing connection
        assert "already connected" in str(exc_info.value)

    def test_validate_shop_domain_case_insensitive(
        self,
        db_session,
        create_test_connection
    ):
        """Test validation detects duplicates regardless of case."""
        tenant_a_id = "test-tenant-case-a"
        shop_domain_lower = "case-test.myshopify.com"

        create_test_connection(
            db_session,
            tenant_id=tenant_a_id,
            shop_domain=shop_domain_lower,
            status=ConnectionStatus.ACTIVE,
        )
        db_session.commit()

        # Tenant B tries with different case
        tenant_b_service = AirbyteService(db_session, "test-tenant-case-b")

        shop_domain_upper = "CASE-TEST.myshopify.com"

        with pytest.raises(DuplicateConnectionError):
            tenant_b_service._validate_shop_domain_unique(
                shop_domain=shop_domain_upper,
                source_type="shopify"
            )

    def test_validate_shop_domain_protocol_variations(
        self,
        db_session,
        create_test_connection
    ):
        """Test validation detects duplicates with different protocols."""
        tenant_a_id = "test-tenant-proto-a"
        shop_domain = "protocol-test.myshopify.com"

        create_test_connection(
            db_session,
            tenant_id=tenant_a_id,
            shop_domain=shop_domain,
            status=ConnectionStatus.ACTIVE,
        )
        db_session.commit()

        # Tenant B tries with https:// prefix
        tenant_b_service = AirbyteService(db_session, "test-tenant-proto-b")

        with pytest.raises(DuplicateConnectionError):
            tenant_b_service._validate_shop_domain_unique(
                shop_domain=f"https://{shop_domain}",
                source_type="shopify"
            )

    def test_validate_shop_domain_inactive_connection_allowed(
        self,
        db_session,
        create_test_connection
    ):
        """Test validation allows connection if existing one is inactive."""
        tenant_a_id = "test-tenant-inactive-a"
        shop_domain = "inactive-test.myshopify.com"

        # Create INACTIVE connection
        create_test_connection(
            db_session,
            tenant_id=tenant_a_id,
            shop_domain=shop_domain,
            status=ConnectionStatus.INACTIVE,  # Not active
        )
        db_session.commit()

        # New tenant should be able to connect
        tenant_b_service = AirbyteService(db_session, "test-tenant-inactive-b")

        # Should not raise
        tenant_b_service._validate_shop_domain_unique(
            shop_domain=shop_domain,
            source_type="shopify"
        )

    def test_validate_shop_domain_disabled_connection_allowed(
        self,
        db_session,
        create_test_connection
    ):
        """Test validation allows connection if existing one is disabled."""
        tenant_a_id = "test-tenant-disabled-a"
        shop_domain = "disabled-test.myshopify.com"

        # Create disabled connection (active but not enabled)
        connection = create_test_connection(
            db_session,
            tenant_id=tenant_a_id,
            shop_domain=shop_domain,
            status=ConnectionStatus.ACTIVE,
        )
        connection.is_enabled = False  # Disabled
        db_session.commit()

        # New tenant should be able to connect
        tenant_b_service = AirbyteService(db_session, "test-tenant-disabled-b")

        # Should not raise
        tenant_b_service._validate_shop_domain_unique(
            shop_domain=shop_domain,
            source_type="shopify"
        )

    def test_validate_shop_domain_non_shopify_skipped(
        self,
        db_session,
        create_test_connection
    ):
        """Test validation only applies to Shopify sources."""
        # Create Google Ads connection
        service = AirbyteService(db_session, "test-tenant-google")

        # Validation should be skipped for non-Shopify sources
        # (This would normally fail if it tried to validate)
        service._validate_shop_domain_unique(
            shop_domain="some-domain.com",
            source_type="google-ads"  # Not Shopify
        )


class TestRegisterConnectionValidation:
    """Test that register_connection enforces shop_domain validation."""

    def test_register_connection_validates_shop_domain(
        self,
        db_session,
        create_test_connection
    ):
        """Test register_connection calls validation for Shopify sources."""
        tenant_a_id = "test-tenant-reg-a"
        shop_domain = "register-test.myshopify.com"

        # Tenant A creates connection
        create_test_connection(
            db_session,
            tenant_id=tenant_a_id,
            shop_domain=shop_domain,
            status=ConnectionStatus.ACTIVE,
        )
        db_session.commit()

        # Tenant B tries to register connection with same shop
        tenant_b_service = AirbyteService(db_session, "test-tenant-reg-b")

        with pytest.raises(DuplicateConnectionError):
            tenant_b_service.register_connection(
                airbyte_connection_id="test-airbyte-conn-123",
                connection_name="Duplicate Shop Connection",
                source_type="shopify",
                configuration={"shop_domain": shop_domain}
            )

    def test_register_connection_allows_unique_shop(
        self,
        db_session
    ):
        """Test register_connection succeeds for unique shop_domain."""
        service = AirbyteService(db_session, "test-tenant-unique")

        # Should succeed - unique shop
        connection_info = service.register_connection(
            airbyte_connection_id="test-airbyte-unique-123",
            connection_name="Unique Shop Connection",
            source_type="shopify",
            configuration={"shop_domain": "unique-new-shop.myshopify.com"}
        )

        assert connection_info is not None
        assert connection_info.connection_name == "Unique Shop Connection"


class TestDatabaseConstraintEnforcement:
    """
    Test that database constraint blocks duplicates as last line of defense.

    These tests verify the database-level enforcement works even if
    application validation is bypassed.
    """

    def test_database_blocks_duplicate_shop_domain(
        self,
        db_session,
        create_test_connection
    ):
        """
        Test database constraint blocks duplicate shop_domain.

        CRITICAL: This is the ultimate safety net.
        """
        shop_domain = "db-constraint-test.myshopify.com"

        # Create first connection
        create_test_connection(
            db_session,
            tenant_id="test-tenant-db-a",
            shop_domain=shop_domain,
            status=ConnectionStatus.ACTIVE,
        )
        db_session.commit()

        # Try to create duplicate directly (bypassing service validation)
        duplicate = TenantAirbyteConnection(
            id="test-conn-db-duplicate",
            tenant_id="test-tenant-db-b",  # Different tenant
            airbyte_connection_id="test-airbyte-db-duplicate",
            connection_name="Duplicate DB Test",
            source_type="shopify",
            status=ConnectionStatus.ACTIVE,
            is_enabled=True,
            configuration={"shop_domain": shop_domain}  # SAME shop
        )

        db_session.add(duplicate)

        # Should raise IntegrityError due to unique constraint
        with pytest.raises(IntegrityError) as exc_info:
            db_session.commit()

        # Verify it's the shop_domain constraint
        assert "ix_tenant_airbyte_connections_shop_domain_unique" in str(exc_info.value)

        # Cleanup failed transaction
        db_session.rollback()

    def test_database_allows_inactive_duplicate(
        self,
        db_session,
        create_test_connection
    ):
        """Test database allows duplicate for inactive connections."""
        shop_domain = "db-inactive-test.myshopify.com"

        # Create inactive connection
        create_test_connection(
            db_session,
            tenant_id="test-tenant-db-inactive-a",
            shop_domain=shop_domain,
            status=ConnectionStatus.INACTIVE,  # Not active
        )
        db_session.commit()

        # Should succeed - constraint only applies to active connections
        active_connection = TenantAirbyteConnection(
            id="test-conn-db-active",
            tenant_id="test-tenant-db-inactive-b",
            airbyte_connection_id="test-airbyte-db-active",
            connection_name="Active DB Test",
            source_type="shopify",
            status=ConnectionStatus.ACTIVE,  # Active
            is_enabled=True,
            configuration={"shop_domain": shop_domain}
        )

        db_session.add(active_connection)
        db_session.commit()  # Should succeed


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def create_test_connection():
    """Factory fixture for creating test connections."""
    def _create(
        db_session,
        tenant_id: str,
        shop_domain: str,
        status: ConnectionStatus = ConnectionStatus.ACTIVE,
    ):
        """Create a test connection with given parameters."""
        import uuid

        connection = TenantAirbyteConnection(
            id=f"test-conn-{uuid.uuid4()}",
            tenant_id=tenant_id,
            airbyte_connection_id=f"test-airbyte-{uuid.uuid4()}",
            connection_name=f"Test Shop: {shop_domain}",
            source_type="shopify",
            status=status,
            is_enabled=True,
            configuration={"shop_domain": shop_domain}
        )

        db_session.add(connection)
        return connection

    return _create


# =============================================================================
# Integration Test Scenarios
# =============================================================================

class TestEndToEndOAuthFlow:
    """
    End-to-end tests simulating complete OAuth flows.

    These tests verify the complete flow from OAuth callback to connection creation.
    """

    def test_oauth_flow_prevents_duplicate_shop(
        self,
        db_session,
        create_test_connection
    ):
        """
        Simulate complete OAuth flow that detects duplicate shop.

        Flow:
        1. Tenant A completes OAuth for shop
        2. Connection created successfully
        3. Tenant B attempts OAuth for SAME shop
        4. Validation blocks duplicate before Airbyte connection created
        """
        shop_domain = "e2e-oauth-test.myshopify.com"

        # Step 1-2: Tenant A completes OAuth
        tenant_a_service = AirbyteService(db_session, "test-tenant-oauth-a")

        connection_a = tenant_a_service.register_connection(
            airbyte_connection_id="test-airbyte-oauth-a",
            connection_name=f"OAuth: {shop_domain}",
            source_type="shopify",
            configuration={"shop_domain": shop_domain}
        )
        assert connection_a is not None

        # Step 3-4: Tenant B attempts OAuth for same shop
        tenant_b_service = AirbyteService(db_session, "test-tenant-oauth-b")

        with pytest.raises(DuplicateConnectionError) as exc_info:
            tenant_b_service.register_connection(
                airbyte_connection_id="test-airbyte-oauth-b",
                connection_name=f"Duplicate OAuth: {shop_domain}",
                source_type="shopify",
                configuration={"shop_domain": shop_domain}
            )

        # Verify error message
        assert "already connected to another account" in str(exc_info.value)

    def test_oauth_flow_allows_reconnect_after_disconnect(
        self,
        db_session,
        create_test_connection
    ):
        """
        Test tenant can reconnect after disconnecting.

        Flow:
        1. Tenant A connects shop
        2. Tenant A disconnects (status = inactive)
        3. Tenant B can now connect same shop
        """
        shop_domain = "reconnect-test.myshopify.com"

        # Step 1: Tenant A connects
        connection_a = create_test_connection(
            db_session,
            tenant_id="test-tenant-reconnect-a",
            shop_domain=shop_domain,
            status=ConnectionStatus.ACTIVE,
        )
        db_session.commit()

        # Step 2: Tenant A disconnects
        connection_a.status = ConnectionStatus.INACTIVE
        db_session.commit()

        # Step 3: Tenant B connects
        tenant_b_service = AirbyteService(db_session, "test-tenant-reconnect-b")

        # Should succeed - previous connection is inactive
        connection_b = tenant_b_service.register_connection(
            airbyte_connection_id="test-airbyte-reconnect-b",
            connection_name=f"Reconnect: {shop_domain}",
            source_type="shopify",
            configuration={"shop_domain": shop_domain}
        )
        assert connection_b is not None


# =============================================================================
# Performance Tests
# =============================================================================

class TestValidationPerformance:
    """Test that validation doesn't significantly impact performance."""

    def test_validation_query_performance(self, db_session):
        """Test validation query completes quickly."""
        import time

        service = AirbyteService(db_session, "test-tenant-perf")

        start = time.time()

        # Run validation (should use indexed query)
        service._validate_shop_domain_unique(
            shop_domain="perf-test.myshopify.com",
            source_type="shopify"
        )

        duration = time.time() - start

        # Should complete in < 100ms (generous threshold)
        assert duration < 0.1, f"Validation took {duration}s (expected < 0.1s)"
