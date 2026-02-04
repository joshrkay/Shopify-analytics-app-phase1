"""
Tests for Clerk webhook handlers and sync services.

Tests cover:
- Webhook signature verification
- User event handling (created, updated, deleted)
- Organization event handling (created, updated, deleted)
- Membership event handling (created, updated, deleted)
- Idempotency and error handling
"""

import pytest
import json
import hmac
import hashlib
import base64
import time
from unittest.mock import patch, MagicMock

from sqlalchemy.orm import Session

from src.models.organization import Organization
from src.models.tenant import Tenant, TenantStatus
from src.models.user import User
from src.models.user_tenant_roles import UserTenantRole
from src.services.clerk_sync_service import ClerkSyncService
from src.services.clerk_webhook_handler import ClerkWebhookHandler
from src.api.routes.webhooks_clerk import verify_clerk_webhook, _verify_signature_manual


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def db_session(test_db_session):
    """Use the test database session."""
    return test_db_session


@pytest.fixture
def sync_service(db_session):
    """Create a ClerkSyncService instance."""
    return ClerkSyncService(db_session)


@pytest.fixture
def webhook_handler(db_session):
    """Create a ClerkWebhookHandler instance."""
    return ClerkWebhookHandler(db_session)


@pytest.fixture
def webhook_secret():
    """Test webhook secret."""
    return "whsec_" + base64.b64encode(b"test_secret_key_12345").decode()


@pytest.fixture
def sample_user_data():
    """Sample Clerk user data."""
    return {
        "id": "user_clerk_123",
        "email_addresses": [
            {
                "id": "email_1",
                "email_address": "test@example.com",
            }
        ],
        "primary_email_address_id": "email_1",
        "first_name": "John",
        "last_name": "Doe",
        "image_url": "https://example.com/avatar.jpg",
        "public_metadata": {"plan": "free"},
    }


@pytest.fixture
def sample_org_data():
    """Sample Clerk organization data."""
    return {
        "id": "org_clerk_123",
        "name": "Test Organization",
        "slug": "test-org",
        "public_metadata": {"tier": "growth"},
    }


@pytest.fixture
def sample_membership_data(sample_user_data, sample_org_data):
    """Sample Clerk membership data."""
    return {
        "id": "mem_123",
        "organization": {
            "id": sample_org_data["id"],
            "name": sample_org_data["name"],
            "slug": sample_org_data["slug"],
        },
        "public_user_data": {
            "user_id": sample_user_data["id"],
            "identifier": "test@example.com",
            "first_name": sample_user_data["first_name"],
            "last_name": sample_user_data["last_name"],
        },
        "role": "org:admin",
    }


# =============================================================================
# Signature Verification Tests
# =============================================================================

class TestSignatureVerification:
    """Tests for Clerk webhook signature verification."""

    def test_verify_signature_missing_headers(self, webhook_secret):
        """Test that missing headers fail verification."""
        payload = b'{"type": "test"}'

        # Missing svix_id
        assert verify_clerk_webhook(
            payload=payload,
            svix_id="",
            svix_timestamp="12345",
            svix_signature="v1,sig",
            webhook_secret=webhook_secret,
        ) is False

    def test_verify_signature_missing_secret(self):
        """Test that missing secret fails verification."""
        payload = b'{"type": "test"}'

        assert verify_clerk_webhook(
            payload=payload,
            svix_id="msg_123",
            svix_timestamp="12345",
            svix_signature="v1,sig",
            webhook_secret="",
        ) is False

    def test_manual_signature_verification_valid(self, webhook_secret):
        """Test manual signature verification with valid signature."""
        payload = b'{"type": "test"}'
        svix_id = "msg_123"
        timestamp = str(int(time.time()))

        # Compute expected signature
        secret_key = base64.b64decode(webhook_secret[6:])
        signed_content = f"{svix_id}.{timestamp}.".encode() + payload
        computed = hmac.new(secret_key, signed_content, hashlib.sha256)
        signature = base64.b64encode(computed.digest()).decode()

        result = _verify_signature_manual(
            payload=payload,
            svix_id=svix_id,
            svix_timestamp=timestamp,
            svix_signature=f"v1,{signature}",
            webhook_secret=webhook_secret,
        )

        assert result is True

    def test_manual_signature_verification_invalid(self, webhook_secret):
        """Test manual signature verification with invalid signature."""
        payload = b'{"type": "test"}'

        result = _verify_signature_manual(
            payload=payload,
            svix_id="msg_123",
            svix_timestamp=str(int(time.time())),
            svix_signature="v1,invalid_signature",
            webhook_secret=webhook_secret,
        )

        assert result is False

    def test_manual_signature_verification_expired_timestamp(self, webhook_secret):
        """Test that expired timestamps fail verification."""
        payload = b'{"type": "test"}'
        old_timestamp = str(int(time.time()) - 400)  # 6+ minutes old

        result = _verify_signature_manual(
            payload=payload,
            svix_id="msg_123",
            svix_timestamp=old_timestamp,
            svix_signature="v1,sig",
            webhook_secret=webhook_secret,
        )

        assert result is False

    def test_manual_signature_verification_future_timestamp(self, webhook_secret):
        """Test that future timestamps fail verification."""
        payload = b'{"type": "test"}'
        future_timestamp = str(int(time.time()) + 400)  # 6+ minutes in future

        result = _verify_signature_manual(
            payload=payload,
            svix_id="msg_123",
            svix_timestamp=future_timestamp,
            svix_signature="v1,sig",
            webhook_secret=webhook_secret,
        )

        assert result is False


# =============================================================================
# ClerkSyncService Tests
# =============================================================================

class TestClerkSyncService:
    """Tests for ClerkSyncService."""

    def test_sync_user_creates_new_user(self, sync_service, db_session):
        """Test that sync_user creates a new user."""
        user = sync_service.sync_user(
            clerk_user_id="user_new_123",
            email="newuser@example.com",
            first_name="New",
            last_name="User",
        )
        db_session.flush()

        assert user.id is not None
        assert user.clerk_user_id == "user_new_123"
        assert user.email == "newuser@example.com"
        assert user.first_name == "New"
        assert user.last_name == "User"
        assert user.is_active is True

    def test_sync_user_updates_existing_user(self, sync_service, db_session):
        """Test that sync_user updates an existing user."""
        # Create user first
        user = sync_service.sync_user(
            clerk_user_id="user_update_123",
            email="original@example.com",
            first_name="Original",
        )
        db_session.flush()
        original_id = user.id

        # Update user
        updated_user = sync_service.sync_user(
            clerk_user_id="user_update_123",
            email="updated@example.com",
            first_name="Updated",
        )

        assert updated_user.id == original_id
        assert updated_user.email == "updated@example.com"
        assert updated_user.first_name == "Updated"

    def test_get_or_create_user_creates_new(self, sync_service, db_session):
        """Test get_or_create_user creates new user if not exists."""
        user = sync_service.get_or_create_user(
            clerk_user_id="user_getorcreate_123",
            email="getorcreate@example.com",
        )
        db_session.flush()

        assert user.clerk_user_id == "user_getorcreate_123"
        assert user.email == "getorcreate@example.com"

    def test_get_or_create_user_returns_existing(self, sync_service, db_session):
        """Test get_or_create_user returns existing user."""
        # Create user first
        original = sync_service.sync_user(
            clerk_user_id="user_existing_123",
            email="existing@example.com",
        )
        db_session.flush()

        # Get or create should return existing
        user = sync_service.get_or_create_user(
            clerk_user_id="user_existing_123",
            email="different@example.com",  # Different email shouldn't matter
        )

        assert user.id == original.id
        assert user.email == "existing@example.com"  # Original email preserved

    def test_deactivate_user(self, sync_service, db_session):
        """Test user deactivation."""
        user = sync_service.sync_user(
            clerk_user_id="user_deactivate_123",
            email="deactivate@example.com",
        )
        db_session.flush()

        result = sync_service.deactivate_user("user_deactivate_123")

        assert result is True
        assert user.is_active is False

    def test_deactivate_user_not_found(self, sync_service):
        """Test deactivating non-existent user."""
        result = sync_service.deactivate_user("user_nonexistent")
        assert result is False

    def test_sync_organization(self, sync_service, db_session):
        """Test organization sync."""
        org = sync_service.sync_organization(
            clerk_org_id="org_sync_123",
            name="Sync Test Org",
            slug="sync-test-org",
        )
        db_session.flush()

        assert org.id is not None
        assert org.clerk_org_id == "org_sync_123"
        assert org.name == "Sync Test Org"
        assert org.slug == "sync-test-org"

    def test_sync_tenant_from_org(self, sync_service, db_session):
        """Test tenant creation from org."""
        tenant = sync_service.sync_tenant_from_org(
            clerk_org_id="org_tenant_123",
            name="Tenant from Org",
            slug="tenant-from-org",
            billing_tier="growth",
        )
        db_session.flush()

        assert tenant.id is not None
        assert tenant.clerk_org_id == "org_tenant_123"
        assert tenant.name == "Tenant from Org"
        assert tenant.billing_tier == "growth"
        assert tenant.status == TenantStatus.ACTIVE

    def test_sync_membership(self, sync_service, db_session):
        """Test membership sync creates UserTenantRole."""
        # Create user and tenant first
        user = sync_service.sync_user(
            clerk_user_id="user_member_123",
            email="member@example.com",
        )
        tenant = sync_service.sync_tenant_from_org(
            clerk_org_id="org_member_123",
            name="Member Org",
        )
        db_session.flush()

        # Sync membership
        role = sync_service.sync_membership(
            clerk_user_id="user_member_123",
            clerk_org_id="org_member_123",
            role="org:admin",
        )

        assert role is not None
        assert role.user_id == user.id
        assert role.tenant_id == tenant.id
        assert role.role == "MERCHANT_ADMIN"  # Mapped from org:admin
        assert role.is_active is True

    def test_remove_membership(self, sync_service, db_session):
        """Test membership removal."""
        # Create user, tenant, and membership
        user = sync_service.sync_user(
            clerk_user_id="user_remove_123",
            email="remove@example.com",
        )
        tenant = sync_service.sync_tenant_from_org(
            clerk_org_id="org_remove_123",
            name="Remove Org",
        )
        db_session.flush()

        sync_service.sync_membership(
            clerk_user_id="user_remove_123",
            clerk_org_id="org_remove_123",
            role="org:member",
        )
        db_session.flush()

        # Remove membership
        result = sync_service.remove_membership(
            clerk_user_id="user_remove_123",
            clerk_org_id="org_remove_123",
        )

        assert result is True

        # Check role is deactivated
        role = db_session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
        ).first()
        assert role.is_active is False


# =============================================================================
# ClerkWebhookHandler Tests
# =============================================================================

class TestClerkWebhookHandler:
    """Tests for ClerkWebhookHandler event handling."""

    def test_handle_user_created(self, webhook_handler, db_session, sample_user_data):
        """Test user.created event handling."""
        payload = {"type": "user.created", "data": sample_user_data}

        result = webhook_handler.handle_event("user.created", payload)

        assert result["status"] == "success"
        assert "user_id" in result["result"]

        # Verify user was created
        user = db_session.query(User).filter(
            User.clerk_user_id == sample_user_data["id"]
        ).first()
        assert user is not None
        assert user.email == "test@example.com"
        assert user.first_name == "John"

    def test_handle_user_updated(self, webhook_handler, db_session, sample_user_data):
        """Test user.updated event handling."""
        # Create user first
        payload = {"type": "user.created", "data": sample_user_data}
        webhook_handler.handle_event("user.created", payload)

        # Update user
        sample_user_data["first_name"] = "Jane"
        sample_user_data["email_addresses"][0]["email_address"] = "jane@example.com"
        update_payload = {"type": "user.updated", "data": sample_user_data}

        result = webhook_handler.handle_event("user.updated", update_payload)

        assert result["status"] == "success"

        user = db_session.query(User).filter(
            User.clerk_user_id == sample_user_data["id"]
        ).first()
        assert user.first_name == "Jane"
        assert user.email == "jane@example.com"

    def test_handle_user_deleted(self, webhook_handler, db_session, sample_user_data):
        """Test user.deleted event handling."""
        # Create user first
        payload = {"type": "user.created", "data": sample_user_data}
        webhook_handler.handle_event("user.created", payload)

        # Delete user
        delete_payload = {"type": "user.deleted", "data": {"id": sample_user_data["id"]}}
        result = webhook_handler.handle_event("user.deleted", delete_payload)

        assert result["status"] == "success"
        assert result["result"]["deactivated"] is True

        user = db_session.query(User).filter(
            User.clerk_user_id == sample_user_data["id"]
        ).first()
        assert user.is_active is False

    def test_handle_organization_created(self, webhook_handler, db_session, sample_org_data):
        """Test organization.created event handling."""
        payload = {"type": "organization.created", "data": sample_org_data}

        result = webhook_handler.handle_event("organization.created", payload)

        assert result["status"] == "success"
        assert "organization_id" in result["result"]
        assert "tenant_id" in result["result"]

        # Verify organization was created
        org = db_session.query(Organization).filter(
            Organization.clerk_org_id == sample_org_data["id"]
        ).first()
        assert org is not None
        assert org.name == "Test Organization"

        # Verify tenant was created
        tenant = db_session.query(Tenant).filter(
            Tenant.clerk_org_id == sample_org_data["id"]
        ).first()
        assert tenant is not None

    def test_handle_organization_deleted(self, webhook_handler, db_session, sample_org_data):
        """Test organization.deleted event handling."""
        # Create org first
        payload = {"type": "organization.created", "data": sample_org_data}
        webhook_handler.handle_event("organization.created", payload)

        # Delete org
        delete_payload = {"type": "organization.deleted", "data": {"id": sample_org_data["id"]}}
        result = webhook_handler.handle_event("organization.deleted", delete_payload)

        assert result["status"] == "success"

        org = db_session.query(Organization).filter(
            Organization.clerk_org_id == sample_org_data["id"]
        ).first()
        assert org.is_active is False

        tenant = db_session.query(Tenant).filter(
            Tenant.clerk_org_id == sample_org_data["id"]
        ).first()
        assert tenant.status == TenantStatus.DEACTIVATED

    def test_handle_membership_created(
        self, webhook_handler, db_session, sample_membership_data, sample_user_data, sample_org_data
    ):
        """Test organizationMembership.created event handling."""
        payload = {"type": "organizationMembership.created", "data": sample_membership_data}

        result = webhook_handler.handle_event("organizationMembership.created", payload)

        assert result["status"] == "success"

        # Verify user was created (lazy sync)
        user = db_session.query(User).filter(
            User.clerk_user_id == sample_user_data["id"]
        ).first()
        assert user is not None

        # Verify tenant was created
        tenant = db_session.query(Tenant).filter(
            Tenant.clerk_org_id == sample_org_data["id"]
        ).first()
        assert tenant is not None

        # Verify role was created
        role = db_session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
        ).first()
        assert role is not None
        assert role.role == "MERCHANT_ADMIN"

    def test_handle_membership_deleted(
        self, webhook_handler, db_session, sample_membership_data
    ):
        """Test organizationMembership.deleted event handling."""
        # Create membership first
        create_payload = {"type": "organizationMembership.created", "data": sample_membership_data}
        webhook_handler.handle_event("organizationMembership.created", create_payload)

        # Delete membership
        delete_payload = {"type": "organizationMembership.deleted", "data": sample_membership_data}
        result = webhook_handler.handle_event("organizationMembership.deleted", delete_payload)

        assert result["status"] == "success"
        assert result["result"]["removed"] is True

    def test_handle_unsupported_event(self, webhook_handler):
        """Test unsupported event handling."""
        payload = {"type": "unsupported.event", "data": {}}

        result = webhook_handler.handle_event("unsupported.event", payload)

        assert result["status"] == "ignored"
        assert "Unsupported event type" in result["reason"]

    def test_handle_event_missing_id(self, webhook_handler):
        """Test event handling with missing required ID."""
        payload = {"type": "user.created", "data": {}}  # Missing id

        with pytest.raises(ValueError, match="Missing user id"):
            webhook_handler.handle_event("user.created", payload)


# =============================================================================
# Idempotency Tests
# =============================================================================

class TestIdempotency:
    """Tests for idempotent webhook handling."""

    def test_duplicate_user_created(self, webhook_handler, db_session, sample_user_data):
        """Test handling duplicate user.created events."""
        payload = {"type": "user.created", "data": sample_user_data}

        # First event
        result1 = webhook_handler.handle_event("user.created", payload)
        user_id_1 = result1["result"]["user_id"]

        # Duplicate event
        result2 = webhook_handler.handle_event("user.created", payload)
        user_id_2 = result2["result"]["user_id"]

        # Should return same user
        assert user_id_1 == user_id_2

        # Should only have one user
        count = db_session.query(User).filter(
            User.clerk_user_id == sample_user_data["id"]
        ).count()
        assert count == 1

    def test_duplicate_organization_created(self, webhook_handler, db_session, sample_org_data):
        """Test handling duplicate organization.created events."""
        payload = {"type": "organization.created", "data": sample_org_data}

        # First event
        result1 = webhook_handler.handle_event("organization.created", payload)
        org_id_1 = result1["result"]["organization_id"]

        # Duplicate event
        result2 = webhook_handler.handle_event("organization.created", payload)
        org_id_2 = result2["result"]["organization_id"]

        # Should return same org
        assert org_id_1 == org_id_2

    def test_duplicate_membership_created(
        self, webhook_handler, db_session, sample_membership_data
    ):
        """Test handling duplicate membership.created events."""
        payload = {"type": "organizationMembership.created", "data": sample_membership_data}

        # First event
        webhook_handler.handle_event("organizationMembership.created", payload)

        # Duplicate event should not create duplicate role
        webhook_handler.handle_event("organizationMembership.created", payload)

        # Count roles
        user = db_session.query(User).filter(
            User.clerk_user_id == sample_membership_data["public_user_data"]["user_id"]
        ).first()
        tenant = db_session.query(Tenant).filter(
            Tenant.clerk_org_id == sample_membership_data["organization"]["id"]
        ).first()

        count = db_session.query(UserTenantRole).filter(
            UserTenantRole.user_id == user.id,
            UserTenantRole.tenant_id == tenant.id,
            UserTenantRole.role == "MERCHANT_ADMIN",
        ).count()
        assert count == 1


# =============================================================================
# Role Mapping Tests
# =============================================================================

class TestRoleMapping:
    """Tests for Clerk to app role mapping."""

    def test_map_admin_role(self, sync_service):
        """Test org:admin maps to MERCHANT_ADMIN."""
        assert sync_service._map_clerk_role("org:admin") == "MERCHANT_ADMIN"

    def test_map_owner_role(self, sync_service):
        """Test org:owner maps to MERCHANT_ADMIN."""
        assert sync_service._map_clerk_role("org:owner") == "MERCHANT_ADMIN"

    def test_map_member_role(self, sync_service):
        """Test org:member maps to MERCHANT_VIEWER."""
        assert sync_service._map_clerk_role("org:member") == "MERCHANT_VIEWER"

    def test_map_unknown_role(self, sync_service):
        """Test unknown role defaults to MERCHANT_VIEWER."""
        assert sync_service._map_clerk_role("org:custom_role") == "MERCHANT_VIEWER"

    def test_map_role_without_prefix(self, sync_service):
        """Test role without org: prefix."""
        assert sync_service._map_clerk_role("admin") == "MERCHANT_ADMIN"
        assert sync_service._map_clerk_role("member") == "MERCHANT_VIEWER"
