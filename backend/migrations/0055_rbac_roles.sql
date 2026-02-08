-- Migration: 0055_rbac_roles.sql
-- Version: 1.0.0
-- Date: 2026-02-08
-- Story: 5.5.1 - Data Model: Custom Roles Per Tenant
--
-- Creates data-driven RBAC tables:
--   roles            - tenant-scoped (or global) role definitions
--   role_permissions  - explicit permission strings per role
--   user_role_assignments - links users to roles for specific tenants
--
-- SECURITY:
--   - CASCADE delete on tenant/user/role FKs
--   - Unique constraints prevent duplicate role slugs and assignments
--   - All queries should filter is_active=TRUE

-- Ensure uuid extension is available
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- 1. roles
-- ============================================================================

CREATE TABLE IF NOT EXISTS roles (
    id              VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    tenant_id       VARCHAR(255) REFERENCES tenants(id) ON DELETE CASCADE,
    name            VARCHAR(100) NOT NULL,
    slug            VARCHAR(100) NOT NULL,
    description     TEXT,
    is_system       BOOLEAN NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- tenant_id is nullable: NULL = global role (e.g. super_admin)
COMMENT ON TABLE  roles IS 'Data-driven role definitions. tenant_id=NULL for global roles.';
COMMENT ON COLUMN roles.tenant_id IS 'Owning tenant. NULL for global roles (e.g. super_admin).';
COMMENT ON COLUMN roles.slug IS 'Machine-friendly identifier, unique per tenant.';
COMMENT ON COLUMN roles.is_system IS 'TRUE for seeded template roles; prevents accidental deletion.';

-- Unique: one slug per tenant (NULL tenant handled by partial index below)
ALTER TABLE roles DROP CONSTRAINT IF EXISTS uq_roles_tenant_slug;
ALTER TABLE roles ADD CONSTRAINT uq_roles_tenant_slug UNIQUE (tenant_id, slug);

-- Global roles (tenant_id IS NULL) need a separate unique index
CREATE UNIQUE INDEX IF NOT EXISTS uq_roles_global_slug
    ON roles(slug) WHERE tenant_id IS NULL;

CREATE INDEX IF NOT EXISTS ix_roles_tenant_id ON roles(tenant_id);
CREATE INDEX IF NOT EXISTS ix_roles_is_active ON roles(is_active);
CREATE INDEX IF NOT EXISTS ix_roles_tenant_active ON roles(tenant_id, is_active);

-- Auto-update updated_at (reuse function from 001_create_identity_tables.sql)
CREATE OR REPLACE FUNCTION update_updated_at_column() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS roles_updated_at ON roles;
CREATE TRIGGER roles_updated_at
    BEFORE UPDATE ON roles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 2. role_permissions
-- ============================================================================

CREATE TABLE IF NOT EXISTS role_permissions (
    id              VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    role_id         VARCHAR(255) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    permission      VARCHAR(100) NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  role_permissions IS 'Explicit permission grants for roles. Strings match Permission enum values.';
COMMENT ON COLUMN role_permissions.permission IS 'Permission string, e.g. analytics:view, billing:manage.';

ALTER TABLE role_permissions DROP CONSTRAINT IF EXISTS uq_role_permission;
ALTER TABLE role_permissions ADD CONSTRAINT uq_role_permission UNIQUE (role_id, permission);

CREATE INDEX IF NOT EXISTS ix_role_permissions_role_id ON role_permissions(role_id);
CREATE INDEX IF NOT EXISTS ix_role_permissions_role_active ON role_permissions(role_id, is_active);

DROP TRIGGER IF EXISTS role_permissions_updated_at ON role_permissions;
CREATE TRIGGER role_permissions_updated_at
    BEFORE UPDATE ON role_permissions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- 3. user_role_assignments
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_role_assignments (
    id              VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,
    user_id         VARCHAR(255) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_id         VARCHAR(255) NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    tenant_id       VARCHAR(255) NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    assigned_by     VARCHAR(255),
    assigned_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    source          VARCHAR(50) DEFAULT 'admin_grant',
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  user_role_assignments IS 'Links users to data-driven roles per tenant.';
COMMENT ON COLUMN user_role_assignments.tenant_id IS 'Denormalized from Role for query performance.';
COMMENT ON COLUMN user_role_assignments.assigned_by IS 'clerk_user_id of the user who granted this assignment.';
COMMENT ON COLUMN user_role_assignments.source IS 'Origin: admin_grant, agency_approval, migration.';

ALTER TABLE user_role_assignments DROP CONSTRAINT IF EXISTS uq_user_role_assignment;
ALTER TABLE user_role_assignments ADD CONSTRAINT uq_user_role_assignment UNIQUE (user_id, role_id, tenant_id);

CREATE INDEX IF NOT EXISTS ix_user_role_assignments_user_id ON user_role_assignments(user_id);
CREATE INDEX IF NOT EXISTS ix_user_role_assignments_role_id ON user_role_assignments(role_id);
CREATE INDEX IF NOT EXISTS ix_user_role_assignments_tenant_id ON user_role_assignments(tenant_id);
CREATE INDEX IF NOT EXISTS ix_user_role_assignments_tenant_user ON user_role_assignments(tenant_id, user_id);
CREATE INDEX IF NOT EXISTS ix_user_role_assignments_tenant_active ON user_role_assignments(tenant_id, is_active);

DROP TRIGGER IF EXISTS user_role_assignments_updated_at ON user_role_assignments;
CREATE TRIGGER user_role_assignments_updated_at
    BEFORE UPDATE ON user_role_assignments
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- Done
-- ============================================================================
SELECT 'Migration 0055_rbac_roles completed successfully' AS status;
