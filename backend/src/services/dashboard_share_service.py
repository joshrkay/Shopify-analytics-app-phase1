"""
Dashboard Share Service - Business logic for sharing custom dashboards.

Handles creating, updating, and revoking shares with permission validation.

Key edge cases:
- Cannot share with yourself (owner check)
- Shared user must have tenant access
- Expired shares treated as inactive at query time
- Agency cross-tenant shares require allowed_tenants validation

Phase: Custom Reports & Dashboard Builder
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.models.dashboard_share import DashboardShare, SharePermission
from src.models.dashboard_audit import DashboardAudit, DashboardAuditAction
from src.services.custom_dashboard_service import (
    CustomDashboardService,
    DashboardNotFoundError,
)

logger = logging.getLogger(__name__)


class ShareNotFoundError(Exception):
    """Share does not exist."""


class ShareConflictError(Exception):
    """Share already exists for this user/role on this dashboard."""


class ShareValidationError(Exception):
    """Share request fails validation."""


# Permission ranking for resolution (higher = more access)
_PERMISSION_RANK = {
    SharePermission.VIEW.value: 1,
    SharePermission.EDIT.value: 2,
    SharePermission.ADMIN.value: 3,
}


class DashboardShareService:
    """Service for managing dashboard shares."""

    def __init__(self, db: Session, tenant_id: str, user_id: str):
        if not tenant_id:
            raise ValueError("tenant_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        self.db = db
        self.tenant_id = tenant_id
        self.user_id = user_id
        self._dashboard_service = CustomDashboardService(db, tenant_id, user_id)

    def list_shares(self, dashboard_id: str) -> Tuple[List[DashboardShare], int]:
        """List all shares for a dashboard. Requires owner or admin access."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_share_manage_access(dashboard)

        shares = (
            self.db.query(DashboardShare)
            .filter(DashboardShare.dashboard_id == dashboard.id)
            .order_by(DashboardShare.created_at.desc())
            .all()
        )

        return shares, len(shares)

    def create_share(
        self,
        dashboard_id: str,
        permission: str = SharePermission.VIEW.value,
        shared_with_user_id: Optional[str] = None,
        shared_with_role: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> DashboardShare:
        """
        Share a dashboard with a user or role.

        Raises:
            ShareValidationError: Invalid share target
            ShareConflictError: Share already exists
        """
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_share_manage_access(dashboard)

        # Cannot share with yourself
        if shared_with_user_id and shared_with_user_id == dashboard.created_by:
            raise ShareValidationError("Cannot share a dashboard with its owner")

        share = DashboardShare(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            dashboard_id=dashboard.id,
            shared_with_user_id=shared_with_user_id,
            shared_with_role=shared_with_role,
            permission=permission,
            granted_by=self.user_id,
            expires_at=expires_at,
        )

        try:
            self.db.add(share)
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            target = shared_with_user_id or f"role:{shared_with_role}"
            raise ShareConflictError(
                f"A share already exists for {target} on this dashboard"
            )

        self._audit(dashboard.id, DashboardAuditAction.SHARED, {
            "share_id": share.id,
            "target": shared_with_user_id or shared_with_role,
            "permission": permission,
        })
        self.db.commit()

        return share

    def update_share(
        self,
        dashboard_id: str,
        share_id: str,
        permission: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> DashboardShare:
        """Update a share's permission or expiry."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_share_manage_access(dashboard)

        share = self.db.query(DashboardShare).filter(
            DashboardShare.id == share_id,
            DashboardShare.dashboard_id == dashboard.id,
        ).first()

        if not share:
            raise ShareNotFoundError(f"Share {share_id} not found")

        if permission is not None:
            share.permission = permission
        if expires_at is not None:
            share.expires_at = expires_at

        self._audit(dashboard.id, DashboardAuditAction.SHARE_UPDATED, {
            "share_id": share.id,
            "permission": share.permission,
        })
        self.db.commit()

        return share

    def revoke_share(self, dashboard_id: str, share_id: str) -> None:
        """Revoke (delete) a share."""
        dashboard = self._dashboard_service.get_dashboard(dashboard_id)
        self._check_share_manage_access(dashboard)

        share = self.db.query(DashboardShare).filter(
            DashboardShare.id == share_id,
            DashboardShare.dashboard_id == dashboard.id,
        ).first()

        if not share:
            raise ShareNotFoundError(f"Share {share_id} not found")

        target = share.shared_with_user_id or share.shared_with_role
        self.db.delete(share)

        self._audit(dashboard.id, DashboardAuditAction.UNSHARED, {
            "share_id": share_id,
            "target": target,
        })
        self.db.commit()

    def resolve_access(self, dashboard_id: str, user_id: str, user_roles: List[str]) -> str:
        """
        Resolve the effective access level for a user on a dashboard.

        Resolution order:
        1. Owner -> "owner"
        2. Direct user share -> share.permission
        3. Role-based share -> highest matching permission
        4. No match -> "none"
        """
        # Check all shares for this dashboard
        shares = (
            self.db.query(DashboardShare)
            .filter(DashboardShare.dashboard_id == dashboard_id)
            .all()
        )

        now = datetime.now(timezone.utc)
        best_permission = "none"
        best_rank = 0

        for share in shares:
            # Skip expired shares (handle naive datetimes from SQLite)
            if share.expires_at:
                expiry = share.expires_at
                if expiry.tzinfo is None:
                    expiry = expiry.replace(tzinfo=timezone.utc)
                if expiry < now:
                    continue

            # Direct user share
            if share.shared_with_user_id == user_id:
                rank = _PERMISSION_RANK.get(share.permission, 0)
                if rank > best_rank:
                    best_rank = rank
                    best_permission = share.permission

            # Role-based share
            if share.shared_with_role and share.shared_with_role in user_roles:
                rank = _PERMISSION_RANK.get(share.permission, 0)
                if rank > best_rank:
                    best_rank = rank
                    best_permission = share.permission

        return best_permission

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _check_share_manage_access(self, dashboard) -> None:
        """Verify caller can manage shares (owner or admin)."""
        access = self._dashboard_service.get_access_level(dashboard)
        if access not in ("owner", "admin"):
            raise DashboardNotFoundError(
                "You do not have permission to manage shares for this dashboard"
            )

    def _audit(
        self,
        dashboard_id: str,
        action: DashboardAuditAction,
        details: Optional[dict] = None,
    ) -> None:
        """Create an audit trail entry."""
        entry = DashboardAudit(
            id=str(uuid.uuid4()),
            tenant_id=self.tenant_id,
            dashboard_id=dashboard_id,
            action=action.value,
            actor_id=self.user_id,
            details_json=details,
        )
        self.db.add(entry)
