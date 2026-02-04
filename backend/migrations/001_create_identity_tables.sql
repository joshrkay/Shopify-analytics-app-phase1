-- =============================================================================
-- Identity Tables Migration
-- =============================================================================
-- Version: 1.0.0
-- Date: 2026-02-04
-- Epic: 1.1 - Organization, Tenant, and User Models (Clerk-Backed)
--
-- This migration creates the core identity tables for multi-tenant SaaS:
-- - organizations: Parent entities (agencies)
-- - tenants: Customer boundaries (Shopify stores)
-- - users: Local user records synced from Clerk (NO PASSWORDS)
-- - user_tenant_roles: Junction table for user-tenant role assignments
--
-- Order of creation matters due to FK dependencies:
-- 1. organizations (no dependencies)
-- 2. tenants (depends on organizations)
-- 3. users (no dependencies)
-- 4. user_tenant_roles (depends on users, tenants)
--
-- SECURITY:
-- - NO passwords or auth secrets stored - Clerk is source of truth
-- - CASCADE deletes ensure referential integrity
-- - All tenant-scoped queries use tenant_id from JWT, never client input
-- =============================================================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- Organizations Table
-- =============================================================================
-- Parent entity for grouping multiple tenants (e.g., agencies)

CREATE TABLE IF NOT EXISTS organizations (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Clerk Organization ID (external reference for SSO)
    clerk_org_id VARCHAR(255) UNIQUE,

    -- Organization details
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Metadata
    settings JSONB,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for organizations
CREATE INDEX IF NOT EXISTS ix_organizations_clerk_org_id ON organizations(clerk_org_id);
CREATE INDEX IF NOT EXISTS ix_organizations_name ON organizations(name);
CREATE INDEX IF NOT EXISTS ix_organizations_slug ON organizations(slug);
CREATE INDEX IF NOT EXISTS ix_organizations_active ON organizations(is_active) WHERE is_active = TRUE;

-- Comments
COMMENT ON TABLE organizations IS 'Parent entity for grouping tenants (e.g., agencies managing multiple stores)';
COMMENT ON COLUMN organizations.clerk_org_id IS 'Clerk Organization ID for SSO/identity linking';
COMMENT ON COLUMN organizations.slug IS 'URL-friendly identifier (e.g., acme-agency)';


-- =============================================================================
-- Tenants Table
-- =============================================================================
-- Represents a Shopify store or logical customer boundary
-- tenant.id IS the tenant_id used across all tenant-scoped models

-- Create tenant status enum type
DO $$ BEGIN
    CREATE TYPE tenant_status AS ENUM ('active', 'suspended', 'deactivated');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS tenants (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Organization relationship (optional - for agencies)
    organization_id VARCHAR(255) REFERENCES organizations(id) ON DELETE SET NULL,

    -- Clerk Organization ID (for direct Clerk org mapping)
    clerk_org_id VARCHAR(255) UNIQUE,

    -- Tenant details
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE,

    -- Billing
    billing_tier VARCHAR(50) NOT NULL DEFAULT 'free',

    -- Status
    status tenant_status NOT NULL DEFAULT 'active',

    -- Metadata
    settings JSONB,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for tenants
CREATE INDEX IF NOT EXISTS ix_tenants_organization_id ON tenants(organization_id);
CREATE INDEX IF NOT EXISTS ix_tenants_clerk_org_id ON tenants(clerk_org_id);
CREATE INDEX IF NOT EXISTS ix_tenants_slug ON tenants(slug);
CREATE INDEX IF NOT EXISTS ix_tenants_org_status ON tenants(organization_id, status);
CREATE INDEX IF NOT EXISTS ix_tenants_billing_tier ON tenants(billing_tier);
CREATE INDEX IF NOT EXISTS ix_tenants_status ON tenants(status);

-- Comments
COMMENT ON TABLE tenants IS 'Tenant represents a Shopify store or logical customer boundary. tenant.id IS the tenant_id used everywhere.';
COMMENT ON COLUMN tenants.id IS 'Primary key - THIS IS the tenant_id used across all tenant-scoped models';
COMMENT ON COLUMN tenants.organization_id IS 'Parent organization (nullable for standalone merchants)';
COMMENT ON COLUMN tenants.clerk_org_id IS 'Clerk Organization ID for identity linking';
COMMENT ON COLUMN tenants.billing_tier IS 'Billing tier: free, growth, enterprise';


-- =============================================================================
-- Users Table
-- =============================================================================
-- Local user records synced from Clerk
-- CRITICAL: NO PASSWORDS - Clerk is source of truth for authentication

CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Clerk User ID - SOURCE OF TRUTH
    clerk_user_id VARCHAR(255) NOT NULL UNIQUE,

    -- Profile information (synced from Clerk)
    email VARCHAR(255),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    avatar_url VARCHAR(500),

    -- Sync tracking
    last_synced_at TIMESTAMP WITH TIME ZONE,

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Metadata
    metadata JSONB,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Indexes for users
CREATE INDEX IF NOT EXISTS ix_users_clerk_user_id ON users(clerk_user_id);
CREATE INDEX IF NOT EXISTS ix_users_email ON users(email);
CREATE INDEX IF NOT EXISTS ix_users_active ON users(is_active) WHERE is_active = TRUE;

-- Comments
COMMENT ON TABLE users IS 'Local user records synced from Clerk. NO PASSWORDS stored - Clerk is auth source of truth.';
COMMENT ON COLUMN users.clerk_user_id IS 'Clerk user ID - unique identifier from Clerk (source of truth)';
COMMENT ON COLUMN users.last_synced_at IS 'When user data was last synced from Clerk webhooks';


-- =============================================================================
-- User Tenant Roles Table
-- =============================================================================
-- Junction table linking users to tenants with role-based access
-- Enables: users in multiple tenants, different roles per tenant, audit trail

CREATE TABLE IF NOT EXISTS user_tenant_roles (
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Foreign keys with CASCADE delete
    user_id VARCHAR(255) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tenant_id VARCHAR(255) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,

    -- Role assignment (from constants/permissions.py Role enum)
    role VARCHAR(50) NOT NULL,

    -- Assignment tracking (audit trail)
    assigned_by VARCHAR(255),  -- clerk_user_id of granting user
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Source tracking
    source VARCHAR(50) DEFAULT 'clerk_webhook',  -- clerk_webhook, agency_grant, admin_grant

    -- Status
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Unique constraint: one role per user-tenant combination
    CONSTRAINT uq_user_tenant_role UNIQUE (user_id, tenant_id, role)
);

-- Indexes for user_tenant_roles
CREATE INDEX IF NOT EXISTS ix_user_tenant_roles_user_id ON user_tenant_roles(user_id);
CREATE INDEX IF NOT EXISTS ix_user_tenant_roles_tenant_id ON user_tenant_roles(tenant_id);
CREATE INDEX IF NOT EXISTS ix_user_tenant_roles_tenant_user ON user_tenant_roles(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS ix_user_tenant_roles_role ON user_tenant_roles(role);
CREATE INDEX IF NOT EXISTS ix_user_tenant_roles_tenant_active ON user_tenant_roles(tenant_id, is_active);
CREATE INDEX IF NOT EXISTS ix_user_tenant_roles_user_active ON user_tenant_roles(user_id, is_active);

-- Comments
COMMENT ON TABLE user_tenant_roles IS 'Junction table: user-to-tenant role assignments. Two sources: Clerk webhooks and agency grants.';
COMMENT ON COLUMN user_tenant_roles.role IS 'Role name from constants/permissions.py Role enum (e.g., MERCHANT_ADMIN, AGENCY_VIEWER)';
COMMENT ON COLUMN user_tenant_roles.assigned_by IS 'clerk_user_id of user who granted this access (null for Clerk webhook source)';
COMMENT ON COLUMN user_tenant_roles.source IS 'How role was created: clerk_webhook, agency_grant, admin_grant';


-- =============================================================================
-- Triggers for updated_at
-- =============================================================================
-- Reuse existing update_updated_at_column() function from billing_schema.sql
-- Create it if it doesn't exist (idempotent)

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Organizations trigger
DROP TRIGGER IF EXISTS tr_organizations_updated_at ON organizations;
CREATE TRIGGER tr_organizations_updated_at
    BEFORE UPDATE ON organizations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Tenants trigger
DROP TRIGGER IF EXISTS tr_tenants_updated_at ON tenants;
CREATE TRIGGER tr_tenants_updated_at
    BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Users trigger
DROP TRIGGER IF EXISTS tr_users_updated_at ON users;
CREATE TRIGGER tr_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- User tenant roles trigger
DROP TRIGGER IF EXISTS tr_user_tenant_roles_updated_at ON user_tenant_roles;
CREATE TRIGGER tr_user_tenant_roles_updated_at
    BEFORE UPDATE ON user_tenant_roles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- =============================================================================
-- Migration Complete
-- =============================================================================
SELECT 'Identity tables migration completed successfully' AS status;
SELECT
    'Created tables: organizations, tenants, users, user_tenant_roles' AS tables_created,
    'Created enum: tenant_status' AS enums_created,
    'Created triggers: updated_at for all tables' AS triggers_created;
