-- =============================================================================
-- Connector Credentials Table Migration
-- =============================================================================
-- Version: 1.0.0
-- Date: 2026-02-05
-- Story: Secure Credential Vault - Encrypted connector credential storage
--
-- This migration creates the connector_credentials table for storing
-- encrypted platform credentials (OAuth tokens, API keys) per tenant.
--
-- SECURITY:
-- - encrypted_payload stores Fernet-encrypted JSON (application-managed keys)
-- - metadata column stores ONLY non-sensitive data (account name, source type)
-- - Tokens are NEVER stored in plaintext
-- - Soft delete (5 days restorable) + hard delete (20 days permanent wipe)
-- - tenant_id from JWT only, never from client input
--
-- Dependencies: tenants table must exist (001_create_identity_tables.sql)
-- =============================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create credential status enum (idempotent)
DO $$ BEGIN
    CREATE TYPE connector_credential_status AS ENUM (
        'active',
        'expired',
        'revoked',
        'invalid',
        'missing'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- =============================================================================
-- Connector Credentials Table
-- =============================================================================
-- Stores encrypted connector credentials with tenant isolation.
-- encrypted_payload contains Fernet-encrypted JSON blob of sensitive tokens.
-- metadata contains ONLY non-sensitive data (account name, source type label).

CREATE TABLE IF NOT EXISTS connector_credentials (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (from JWT org_id, NEVER from client input)
    tenant_id VARCHAR(255) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Human-readable label for the credential set
    credential_name VARCHAR(255) NOT NULL,

    -- Connector source type (e.g., shopify, meta, google_ads, postgres)
    source_type VARCHAR(100) NOT NULL,

    -- Fernet-encrypted JSON payload containing sensitive tokens/keys.
    -- CRITICAL: This column is wiped (set to NULL) on hard delete.
    -- NEVER log or expose this value.
    encrypted_payload TEXT NOT NULL,

    -- Non-sensitive metadata (account name, display labels, validation info).
    -- MUST NOT contain tokens, keys, or secrets.
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Credential lifecycle status
    status connector_credential_status NOT NULL DEFAULT 'active',

    -- Audit: who created this credential
    created_by VARCHAR(255) NOT NULL,

    -- Soft delete support
    -- NULL = active record; non-NULL = soft-deleted at this timestamp
    soft_deleted_at TIMESTAMP WITH TIME ZONE,

    -- Hard delete scheduling
    -- When set, a background job permanently wipes encrypted_payload after this time
    hard_delete_after TIMESTAMP WITH TIME ZONE,

    -- Standard timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Indexes
-- =============================================================================

-- Active credentials per tenant (excludes soft-deleted)
CREATE INDEX IF NOT EXISTS ix_connector_credentials_tenant_active
    ON connector_credentials (tenant_id, status)
    WHERE soft_deleted_at IS NULL;

-- Lookup by tenant + source type (common query: "get all Shopify creds for tenant")
CREATE INDEX IF NOT EXISTS ix_connector_credentials_tenant_source
    ON connector_credentials (tenant_id, source_type)
    WHERE soft_deleted_at IS NULL;

-- Hard delete reaper query: find records past their hard_delete_after deadline
CREATE INDEX IF NOT EXISTS ix_connector_credentials_hard_delete
    ON connector_credentials (hard_delete_after)
    WHERE hard_delete_after IS NOT NULL AND soft_deleted_at IS NOT NULL;

-- Tenant isolation index (all queries must filter by tenant_id)
CREATE INDEX IF NOT EXISTS ix_connector_credentials_tenant_id
    ON connector_credentials (tenant_id);

-- =============================================================================
-- Triggers
-- =============================================================================

-- Reuse the shared update_updated_at_column() function
-- (created in 001_create_identity_tables.sql, idempotent recreation here)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS tr_connector_credentials_updated_at ON connector_credentials;
CREATE TRIGGER tr_connector_credentials_updated_at
    BEFORE UPDATE ON connector_credentials
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE connector_credentials IS
    'Encrypted connector credentials per tenant. Fernet-encrypted payload, non-sensitive metadata only. Supports soft + hard delete.';
COMMENT ON COLUMN connector_credentials.id IS
    'Primary key (UUID).';
COMMENT ON COLUMN connector_credentials.tenant_id IS
    'Tenant identifier from JWT org_id. NEVER from client input.';
COMMENT ON COLUMN connector_credentials.credential_name IS
    'Human-readable label for the credential set (e.g., "Production Shopify Store").';
COMMENT ON COLUMN connector_credentials.source_type IS
    'Connector source type (e.g., shopify, meta, google_ads, postgres).';
COMMENT ON COLUMN connector_credentials.encrypted_payload IS
    'Fernet-encrypted JSON blob of sensitive tokens/keys. Wiped to NULL on hard delete. NEVER log this value.';
COMMENT ON COLUMN connector_credentials.metadata IS
    'Non-sensitive metadata: account_name, display labels, last_validated_at. MUST NOT contain secrets.';
COMMENT ON COLUMN connector_credentials.status IS
    'Credential lifecycle: active, expired, revoked, invalid.';
COMMENT ON COLUMN connector_credentials.created_by IS
    'clerk_user_id of the user who stored these credentials.';
COMMENT ON COLUMN connector_credentials.soft_deleted_at IS
    'Timestamp when soft delete was triggered. NULL means active. Restorable within 5 days.';
COMMENT ON COLUMN connector_credentials.hard_delete_after IS
    'Scheduled time for permanent encrypted_payload wipe. Set to soft_deleted_at + 20 days.';

-- =============================================================================
-- Migration Complete
-- =============================================================================
SELECT 'Connector credentials migration completed successfully' AS status;
SELECT
    'Created table: connector_credentials' AS tables_created,
    'Created enum: connector_credential_status' AS enums_created,
    'Created trigger: tr_connector_credentials_updated_at' AS triggers_created;
