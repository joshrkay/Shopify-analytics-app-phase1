-- Notification Framework Schema
-- Version: 1.0.0
-- Date: 2026-01-28
-- Story: 9.1 - Notification Framework (Events → Channels)
--
-- Creates tables for:
--   - notifications: Core notification records
--   - notification_preferences: User preferences (Story 9.2)
--
-- SECURITY:
--   - tenant_id column on all tables for tenant isolation
--   - user_id for per-user notifications
--   - No PII stored - only references to entities

-- Ensure uuid-ossp extension is available
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- ENUM TYPES
-- =============================================================================

-- Notification event types
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_event_type') THEN
        CREATE TYPE notification_event_type AS ENUM (
            'connector_failed',
            'action_requires_approval',
            'action_executed',
            'action_failed',
            'incident_declared',
            'incident_resolved',
            'sync_completed',
            'insight_generated',
            'recommendation_created'
        );
    END IF;
END
$$;

-- Notification importance level
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_importance') THEN
        CREATE TYPE notification_importance AS ENUM (
            'important',
            'routine'
        );
    END IF;
END
$$;

-- Notification delivery status
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_status') THEN
        CREATE TYPE notification_status AS ENUM (
            'pending',
            'delivered',
            'read',
            'failed'
        );
    END IF;
END
$$;

-- =============================================================================
-- NOTIFICATIONS TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS notifications (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation (CRITICAL: never from client input, only from JWT)
    tenant_id VARCHAR(255) NOT NULL,

    -- Target user (optional - some notifications are tenant-wide)
    user_id VARCHAR(255),

    -- Event information
    event_type notification_event_type NOT NULL,
    importance notification_importance NOT NULL,

    -- Content
    title VARCHAR(500) NOT NULL,
    message TEXT NOT NULL,
    action_url VARCHAR(1000),

    -- Related entity (for grouping and deduplication)
    entity_type VARCHAR(100),
    entity_id VARCHAR(255),

    -- Idempotency (prevents duplicate notifications)
    idempotency_key VARCHAR(255) NOT NULL,

    -- Delivery tracking
    status notification_status NOT NULL DEFAULT 'pending',

    -- Channel delivery tracking
    in_app_delivered_at TIMESTAMP WITH TIME ZONE,
    email_queued_at TIMESTAMP WITH TIME ZONE,
    email_sent_at TIMESTAMP WITH TIME ZONE,
    email_failed_at TIMESTAMP WITH TIME ZONE,
    email_error VARCHAR(500),

    -- Read tracking
    read_at TIMESTAMP WITH TIME ZONE,

    -- Event metadata for extensibility
    event_metadata JSONB DEFAULT '{}'::JSONB,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- NOTIFICATION PREFERENCES TABLE (Story 9.2 preparation)
-- =============================================================================

CREATE TABLE IF NOT EXISTS notification_preferences (
    -- Primary key
    id VARCHAR(255) PRIMARY KEY DEFAULT uuid_generate_v4()::TEXT,

    -- Tenant isolation
    tenant_id VARCHAR(255) NOT NULL,

    -- User (if NULL, applies as tenant default)
    user_id VARCHAR(255),

    -- Event type this preference applies to
    event_type notification_event_type NOT NULL,

    -- Channel-specific settings
    in_app_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    email_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    -- Unique constraint: one preference per user per event type
    CONSTRAINT uq_notification_pref_user_event
        UNIQUE (tenant_id, user_id, event_type)
);

-- =============================================================================
-- INDEXES FOR notifications
-- =============================================================================

CREATE INDEX IF NOT EXISTS ix_notifications_tenant_id
    ON notifications(tenant_id);

CREATE INDEX IF NOT EXISTS ix_notifications_user_id
    ON notifications(user_id);

CREATE INDEX IF NOT EXISTS ix_notifications_event_type
    ON notifications(event_type);

CREATE INDEX IF NOT EXISTS ix_notifications_status
    ON notifications(status);

CREATE INDEX IF NOT EXISTS ix_notifications_created_at
    ON notifications(created_at);

-- Composite indexes for common queries
CREATE INDEX IF NOT EXISTS ix_notifications_tenant_user_status
    ON notifications(tenant_id, user_id, status);

CREATE INDEX IF NOT EXISTS ix_notifications_tenant_created
    ON notifications(tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_notifications_entity
    ON notifications(tenant_id, entity_type, entity_id);

-- Idempotency key (unique)
CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_idempotency_key
    ON notifications(idempotency_key);

-- Pending email delivery (for worker queue)
CREATE INDEX IF NOT EXISTS ix_notifications_pending_email
    ON notifications(email_queued_at, email_sent_at)
    WHERE importance = 'important'
      AND email_queued_at IS NOT NULL
      AND email_sent_at IS NULL
      AND email_failed_at IS NULL;

-- =============================================================================
-- INDEXES FOR notification_preferences
-- =============================================================================

CREATE INDEX IF NOT EXISTS ix_notification_prefs_tenant_id
    ON notification_preferences(tenant_id);

CREATE INDEX IF NOT EXISTS ix_notification_prefs_tenant_user
    ON notification_preferences(tenant_id, user_id);

-- =============================================================================
-- TRIGGERS
-- =============================================================================

DROP TRIGGER IF EXISTS tr_notifications_updated_at ON notifications;
CREATE TRIGGER tr_notifications_updated_at
    BEFORE UPDATE ON notifications
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS tr_notification_prefs_updated_at ON notification_preferences;
CREATE TRIGGER tr_notification_prefs_updated_at
    BEFORE UPDATE ON notification_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE notifications IS 'Core notification records for event-driven notifications. Story 9.1.';
COMMENT ON TABLE notification_preferences IS 'User notification preferences per event type and channel. Story 9.2.';

COMMENT ON COLUMN notifications.tenant_id IS 'Tenant isolation key - ONLY from JWT, never client input';
COMMENT ON COLUMN notifications.user_id IS 'Target user ID (optional - NULL for tenant-wide notifications)';
COMMENT ON COLUMN notifications.importance IS 'Determines routing: important = email+in_app, routine = in_app only';
COMMENT ON COLUMN notifications.idempotency_key IS 'Unique key for deduplication';
COMMENT ON COLUMN notifications.entity_type IS 'Type of related entity (connector, action, incident)';
COMMENT ON COLUMN notifications.entity_id IS 'ID of the related entity';
COMMENT ON COLUMN notifications.action_url IS 'Deep link URL for user to navigate to relevant page';
