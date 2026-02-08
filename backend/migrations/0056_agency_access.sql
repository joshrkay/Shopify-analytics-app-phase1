-- Migration: 0056_agency_access.sql
-- Version: 1.0.0
-- Date: 2026-02-08
-- Story: 5.5.2 - Agency Access Request + Tenant Approval Workflow
--
-- Creates the agency_access_requests table for tracking agency-to-tenant
-- access approval workflow.
--
-- SECURITY:
--   - Only one pending request per user-tenant pair (partial unique index)
--   - CASCADE delete on user/tenant FKs
--   - All state transitions emit audit events

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- agency_access_requests
-- ============================================================================

CREATE TABLE IF NOT EXISTS agency_access_requests (
    id                    VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    requesting_user_id    VARCHAR(255) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    requesting_org_id     VARCHAR(255) REFERENCES organizations(id) ON DELETE SET NULL,
    tenant_id             VARCHAR(255) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    requested_role_slug   VARCHAR(100) NOT NULL DEFAULT 'agency_viewer',
    message               TEXT NOT NULL DEFAULT '[AppName] is testing for bringing in your reporting data. Please approve or deny.',
    status                VARCHAR(20) NOT NULL DEFAULT 'pending',
    reviewed_by           VARCHAR(255),
    reviewed_at           TIMESTAMP WITH TIME ZONE,
    review_note           TEXT,
    expires_at            TIMESTAMP WITH TIME ZONE,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  agency_access_requests IS 'Agency-to-tenant access approval workflow. Story 5.5.2.';
COMMENT ON COLUMN agency_access_requests.requesting_user_id IS 'Agency user requesting access.';
COMMENT ON COLUMN agency_access_requests.requesting_org_id IS 'Agency organization (optional).';
COMMENT ON COLUMN agency_access_requests.tenant_id IS 'Target tenant being requested.';
COMMENT ON COLUMN agency_access_requests.requested_role_slug IS 'Role template slug to assign on approval (e.g. agency_viewer).';
COMMENT ON COLUMN agency_access_requests.message IS 'Approval message displayed to tenant admin.';
COMMENT ON COLUMN agency_access_requests.status IS 'Lifecycle: pending, approved, denied, expired, cancelled.';
COMMENT ON COLUMN agency_access_requests.reviewed_by IS 'clerk_user_id of the reviewing tenant admin.';
COMMENT ON COLUMN agency_access_requests.expires_at IS 'Auto-expiration timestamp for pending requests.';

-- Only one pending request per user-tenant pair
CREATE UNIQUE INDEX IF NOT EXISTS uq_agency_access_pending
    ON agency_access_requests(requesting_user_id, tenant_id)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS ix_agency_access_requests_tenant_status
    ON agency_access_requests(tenant_id, status);

CREATE INDEX IF NOT EXISTS ix_agency_access_requests_user_status
    ON agency_access_requests(requesting_user_id, status);

CREATE INDEX IF NOT EXISTS ix_agency_access_requests_status
    ON agency_access_requests(status);

CREATE INDEX IF NOT EXISTS ix_agency_access_requests_expires_at
    ON agency_access_requests(expires_at)
    WHERE status = 'pending';

-- Auto-update updated_at (reuse function from 001_create_identity_tables.sql)
DROP TRIGGER IF EXISTS agency_access_requests_updated_at ON agency_access_requests;
CREATE TRIGGER agency_access_requests_updated_at
    BEFORE UPDATE ON agency_access_requests
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Done
-- ============================================================================
SELECT 'Migration 0056_agency_access completed successfully' AS status;
