"""
Clerk Webhook Handler for processing Clerk webhook events.

Handles the following event types:
- user.created, user.updated, user.deleted
- organization.created, organization.updated, organization.deleted
- organizationMembership.created, organizationMembership.updated, organizationMembership.deleted

Each handler extracts relevant data from the Clerk payload and uses
ClerkSyncService to update the local database.
"""

import logging
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session

from src.services.clerk_sync_service import ClerkSyncService

logger = logging.getLogger(__name__)


class ClerkWebhookHandler:
    """
    Handler for Clerk webhook events.

    Routes events to appropriate handler methods and manages database transactions.
    """

    def __init__(self, session: Session):
        """
        Initialize handler with database session.

        Args:
            session: SQLAlchemy session for database operations
        """
        self.session = session
        self.sync_service = ClerkSyncService(session)

    def handle_event(self, event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Route webhook event to appropriate handler.

        Args:
            event_type: Clerk event type (e.g., 'user.created')
            payload: Event payload from Clerk

        Returns:
            Dict with handling result

        Raises:
            ValueError: If event type is not supported
        """
        handlers = {
            # User events
            "user.created": self.handle_user_created,
            "user.updated": self.handle_user_updated,
            "user.deleted": self.handle_user_deleted,
            # Organization events
            "organization.created": self.handle_organization_created,
            "organization.updated": self.handle_organization_updated,
            "organization.deleted": self.handle_organization_deleted,
            # Membership events
            "organizationMembership.created": self.handle_membership_created,
            "organizationMembership.updated": self.handle_membership_updated,
            "organizationMembership.deleted": self.handle_membership_deleted,
        }

        handler = handlers.get(event_type)
        if not handler:
            logger.warning(f"Unsupported event type: {event_type}")
            return {"status": "ignored", "reason": f"Unsupported event type: {event_type}"}

        try:
            result = handler(payload)
            self.session.commit()
            return {"status": "success", "result": result}
        except Exception as e:
            self.session.rollback()
            logger.error(
                f"Error handling {event_type}",
                extra={"error": str(e), "event_type": event_type},
                exc_info=True,
            )
            raise

    # =========================================================================
    # User Event Handlers
    # =========================================================================

    def handle_user_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle user.created event.

        Creates a new User record from Clerk data.

        Args:
            payload: Clerk user.created payload

        Returns:
            Dict with user_id
        """
        data = payload.get("data", {})

        clerk_user_id = data.get("id")
        if not clerk_user_id:
            raise ValueError("Missing user id in payload")

        # Extract user data
        email = self._get_primary_email(data)
        first_name = data.get("first_name")
        last_name = data.get("last_name")
        avatar_url = data.get("image_url") or data.get("profile_image_url")
        metadata = data.get("public_metadata") or data.get("private_metadata")

        user = self.sync_service.sync_user(
            clerk_user_id=clerk_user_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            avatar_url=avatar_url,
            metadata=metadata,
        )

        logger.info(
            "Processed user.created",
            extra={"clerk_user_id": clerk_user_id, "user_id": user.id}
        )

        return {"user_id": user.id, "clerk_user_id": clerk_user_id}

    def handle_user_updated(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle user.updated event.

        Updates existing User record from Clerk data.

        Args:
            payload: Clerk user.updated payload

        Returns:
            Dict with user_id
        """
        # Same logic as user.created - sync_user handles updates
        return self.handle_user_created(payload)

    def handle_user_deleted(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle user.deleted event.

        Deactivates the User record (soft delete).

        Args:
            payload: Clerk user.deleted payload

        Returns:
            Dict with deactivated status
        """
        data = payload.get("data", {})
        clerk_user_id = data.get("id")

        if not clerk_user_id:
            raise ValueError("Missing user id in payload")

        success = self.sync_service.deactivate_user(clerk_user_id)

        logger.info(
            "Processed user.deleted",
            extra={"clerk_user_id": clerk_user_id, "deactivated": success}
        )

        return {"clerk_user_id": clerk_user_id, "deactivated": success}

    # =========================================================================
    # Organization Event Handlers
    # =========================================================================

    def handle_organization_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle organization.created event.

        Creates both Organization and Tenant records.
        The Tenant is the entity used for tenant_id across the application.

        Args:
            payload: Clerk organization.created payload

        Returns:
            Dict with organization_id and tenant_id
        """
        data = payload.get("data", {})

        clerk_org_id = data.get("id")
        if not clerk_org_id:
            raise ValueError("Missing organization id in payload")

        name = data.get("name", "Unnamed Organization")
        slug = data.get("slug")
        metadata = data.get("public_metadata")

        # Create Organization
        org = self.sync_service.sync_organization(
            clerk_org_id=clerk_org_id,
            name=name,
            slug=slug,
            settings=metadata,
        )

        # Flush to get org.id
        self.session.flush()

        # Create corresponding Tenant
        tenant = self.sync_service.sync_tenant_from_org(
            clerk_org_id=clerk_org_id,
            name=name,
            slug=slug,
            billing_tier="free",
            organization_id=org.id,
            settings=metadata,
        )

        logger.info(
            "Processed organization.created",
            extra={
                "clerk_org_id": clerk_org_id,
                "organization_id": org.id,
                "tenant_id": tenant.id,
            }
        )

        return {
            "organization_id": org.id,
            "tenant_id": tenant.id,
            "clerk_org_id": clerk_org_id,
        }

    def handle_organization_updated(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle organization.updated event.

        Updates both Organization and Tenant records.

        Args:
            payload: Clerk organization.updated payload

        Returns:
            Dict with organization_id and tenant_id
        """
        # Same logic as organization.created - sync methods handle updates
        return self.handle_organization_created(payload)

    def handle_organization_deleted(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle organization.deleted event.

        Deactivates both Organization and Tenant records.

        Args:
            payload: Clerk organization.deleted payload

        Returns:
            Dict with deactivated status
        """
        data = payload.get("data", {})
        clerk_org_id = data.get("id")

        if not clerk_org_id:
            raise ValueError("Missing organization id in payload")

        org_deactivated = self.sync_service.deactivate_organization(clerk_org_id)
        tenant_deactivated = self.sync_service.deactivate_tenant(clerk_org_id)

        logger.info(
            "Processed organization.deleted",
            extra={
                "clerk_org_id": clerk_org_id,
                "org_deactivated": org_deactivated,
                "tenant_deactivated": tenant_deactivated,
            }
        )

        return {
            "clerk_org_id": clerk_org_id,
            "organization_deactivated": org_deactivated,
            "tenant_deactivated": tenant_deactivated,
        }

    # =========================================================================
    # Membership Event Handlers
    # =========================================================================

    def handle_membership_created(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle organizationMembership.created event.

        Creates a UserTenantRole linking the user to the tenant.

        Args:
            payload: Clerk organizationMembership.created payload

        Returns:
            Dict with role assignment details
        """
        data = payload.get("data", {})

        # Extract membership data
        clerk_org_id = data.get("organization", {}).get("id")
        clerk_user_id = data.get("public_user_data", {}).get("user_id")
        role = data.get("role", "org:member")

        if not clerk_org_id or not clerk_user_id:
            raise ValueError("Missing organization or user id in payload")

        # Ensure user exists (might not if user.created wasn't processed yet)
        user_data = data.get("public_user_data", {})
        self.sync_service.get_or_create_user(
            clerk_user_id=clerk_user_id,
            email=user_data.get("identifier"),
            first_name=user_data.get("first_name"),
            last_name=user_data.get("last_name"),
        )

        # Ensure tenant exists
        org_data = data.get("organization", {})
        self.sync_service.sync_tenant_from_org(
            clerk_org_id=clerk_org_id,
            name=org_data.get("name", "Unknown"),
            slug=org_data.get("slug"),
        )

        # Flush to ensure entities exist
        self.session.flush()

        # Create membership
        user_role = self.sync_service.sync_membership(
            clerk_user_id=clerk_user_id,
            clerk_org_id=clerk_org_id,
            role=role,
        )

        result = {
            "clerk_user_id": clerk_user_id,
            "clerk_org_id": clerk_org_id,
            "role": role,
        }

        if user_role:
            result["user_tenant_role_id"] = user_role.id

        logger.info("Processed organizationMembership.created", extra=result)

        return result

    def handle_membership_updated(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle organizationMembership.updated event.

        Updates the user's role in the tenant.

        Args:
            payload: Clerk organizationMembership.updated payload

        Returns:
            Dict with role update details
        """
        data = payload.get("data", {})

        clerk_org_id = data.get("organization", {}).get("id")
        clerk_user_id = data.get("public_user_data", {}).get("user_id")
        new_role = data.get("role", "org:member")

        if not clerk_org_id or not clerk_user_id:
            raise ValueError("Missing organization or user id in payload")

        # For updates, we create a new role assignment
        # The sync_membership method handles reactivation of existing roles
        user_role = self.sync_service.sync_membership(
            clerk_user_id=clerk_user_id,
            clerk_org_id=clerk_org_id,
            role=new_role,
        )

        result = {
            "clerk_user_id": clerk_user_id,
            "clerk_org_id": clerk_org_id,
            "new_role": new_role,
        }

        if user_role:
            result["user_tenant_role_id"] = user_role.id

        logger.info("Processed organizationMembership.updated", extra=result)

        return result

    def handle_membership_deleted(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle organizationMembership.deleted event.

        Removes the user's access to the tenant.

        Args:
            payload: Clerk organizationMembership.deleted payload

        Returns:
            Dict with removal status
        """
        data = payload.get("data", {})

        clerk_org_id = data.get("organization", {}).get("id")
        clerk_user_id = data.get("public_user_data", {}).get("user_id")

        if not clerk_org_id or not clerk_user_id:
            raise ValueError("Missing organization or user id in payload")

        success = self.sync_service.remove_membership(
            clerk_user_id=clerk_user_id,
            clerk_org_id=clerk_org_id,
        )

        result = {
            "clerk_user_id": clerk_user_id,
            "clerk_org_id": clerk_org_id,
            "removed": success,
        }

        logger.info("Processed organizationMembership.deleted", extra=result)

        return result

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _get_primary_email(self, user_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract primary email from Clerk user data.

        Clerk stores emails in email_addresses array with one marked as primary.

        Args:
            user_data: Clerk user data

        Returns:
            Primary email address or None
        """
        email_addresses = user_data.get("email_addresses", [])

        # Find primary email
        for email_obj in email_addresses:
            if email_obj.get("id") == user_data.get("primary_email_address_id"):
                return email_obj.get("email_address")

        # Fallback to first email
        if email_addresses:
            return email_addresses[0].get("email_address")

        return None
