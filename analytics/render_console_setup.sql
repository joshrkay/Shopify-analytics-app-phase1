-- ============================================================================
-- Render Database Console Setup Script
-- 
-- Copy and paste this entire script into Render's database console/editor
-- This sets up test data for validating dbt staging models
-- ============================================================================

-- Step 1: Create test schema
CREATE SCHEMA IF NOT EXISTS test_airbyte;

-- Step 2: Create test tables matching Airbyte structure

-- Shopify Orders
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_shopify_orders (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Shopify Customers
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_shopify_customers (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Meta Ads
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_meta_ads (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Google Ads
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_google_ads (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Tenant Connections (in test schema for testing)
CREATE TABLE IF NOT EXISTS test_airbyte.tenant_airbyte_connections (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    airbyte_connection_id VARCHAR(255) NOT NULL,
    source_type VARCHAR(100),
    connection_name VARCHAR(255),
    status VARCHAR(50),
    is_enabled BOOLEAN,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Step 3: Insert test data

-- Clear existing test data (if any)
TRUNCATE TABLE test_airbyte._airbyte_raw_shopify_orders CASCADE;
TRUNCATE TABLE test_airbyte._airbyte_raw_shopify_customers CASCADE;
TRUNCATE TABLE test_airbyte._airbyte_raw_meta_ads CASCADE;
TRUNCATE TABLE test_airbyte._airbyte_raw_google_ads CASCADE;
TRUNCATE TABLE test_airbyte.tenant_airbyte_connections CASCADE;

-- Insert Shopify Orders
INSERT INTO test_airbyte._airbyte_raw_shopify_orders VALUES
('order-1', '2024-01-15 10:00:00+00', '{
    "id": "gid://shopify/Order/12345",
    "name": "#1001",
    "order_number": "1001",
    "email": "customer1@example.com",
    "created_at": "2024-01-15T10:00:00Z",
    "updated_at": "2024-01-15T10:05:00Z",
    "cancelled_at": null,
    "closed_at": null,
    "financial_status": "paid",
    "fulfillment_status": "fulfilled",
    "total_price": "99.99",
    "subtotal_price": "89.99",
    "total_tax": "10.00",
    "currency": "USD",
    "customer": {"id": "gid://shopify/Customer/111"},
    "tags": "test,new-customer",
    "note": "Test order"
}'),
('order-2', '2024-01-16 11:00:00+00', '{
    "id": "gid://shopify/Order/12346",
    "name": "#1002",
    "order_number": "1002",
    "email": "customer2@example.com",
    "created_at": "2024-01-16T11:00:00Z",
    "updated_at": "2024-01-16T11:10:00Z",
    "cancelled_at": null,
    "closed_at": "2024-01-16T12:00:00Z",
    "financial_status": "paid",
    "fulfillment_status": "fulfilled",
    "total_price": "149.50",
    "subtotal_price": "135.00",
    "total_tax": "14.50",
    "currency": "USD",
    "customer": {"id": "gid://shopify/Customer/222"},
    "tags": "vip",
    "note": null
}'),
('order-3', '2024-01-17 12:00:00+00', '{
    "id": null,
    "name": "#1003",
    "order_number": "1003",
    "email": "customer3@example.com",
    "created_at": "2024-01-17T12:00:00Z",
    "total_price": "50.00",
    "currency": "USD"
}'),
('order-4', '2024-01-18 13:00:00+00', '{
    "id": "gid://shopify/Order/12348",
    "name": "#1004",
    "order_number": "1004",
    "email": "customer4@example.com",
    "created_at": "2024-01-18T13:00:00Z",
    "total_price": "invalid",
    "currency": "EUR",
    "financial_status": "paid"
}');

-- Insert Shopify Customers
INSERT INTO test_airbyte._airbyte_raw_shopify_customers VALUES
('customer-1', '2024-01-10 09:00:00+00', '{
    "id": "gid://shopify/Customer/111",
    "email": "customer1@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "phone": "+1234567890",
    "created_at": "2024-01-10T09:00:00Z",
    "updated_at": "2024-01-15T10:00:00Z",
    "accepts_marketing": "true",
    "verified_email": "true",
    "orders_count": "5",
    "total_spent": "499.99",
    "currency": "USD",
    "state": "enabled",
    "default_address": {"country": "US", "city": "New York"}
}'),
('customer-2', '2024-01-11 10:00:00+00', '{
    "id": "gid://shopify/Customer/222",
    "email": "customer2@example.com",
    "first_name": "Jane",
    "last_name": "Smith",
    "phone": null,
    "created_at": "2024-01-11T10:00:00Z",
    "updated_at": "2024-01-16T11:00:00Z",
    "accepts_marketing": "false",
    "verified_email": "1",
    "orders_count": "3",
    "total_spent": "299.50",
    "currency": "USD",
    "state": "enabled",
    "default_address": {"country": "CA", "city": "Toronto"}
}');

-- Insert Meta Ads
INSERT INTO test_airbyte._airbyte_raw_meta_ads VALUES
('meta-1', '2024-01-15 08:00:00+00', '{
    "account_id": "act_123456",
    "campaign_id": "120330000000000001",
    "adset_id": "120330000000000002",
    "ad_id": "120330000000000003",
    "date_start": "2024-01-15",
    "date_stop": "2024-01-15",
    "spend": "25.50",
    "impressions": "5000",
    "clicks": "150",
    "conversions": "5.0",
    "currency": "USD",
    "campaign_name": "Test Campaign",
    "adset_name": "Test Adset",
    "ad_name": "Test Ad",
    "objective": "CONVERSIONS"
}'),
('meta-2', '2024-01-16 08:00:00+00', '{
    "account_id": "act_123456",
    "campaign_id": "120330000000000001",
    "adset_id": "120330000000000002",
    "ad_id": "120330000000000004",
    "date_start": "2024-01-16",
    "date_stop": "2024-01-16",
    "spend": "30.75",
    "impressions": "6000",
    "clicks": "180",
    "conversions": "6.0",
    "currency": "USD",
    "campaign_name": "Test Campaign",
    "objective": "CONVERSIONS"
}');

-- Insert Google Ads
INSERT INTO test_airbyte._airbyte_raw_google_ads VALUES
('google-1', '2024-01-15 08:00:00+00', '{
    "customer_id": "1234567890",
    "campaign_id": "987654321",
    "ad_group_id": "111222333",
    "ad_id": "444555666",
    "date": "2024-01-15",
    "cost_micros": "25500000",
    "cost": null,
    "impressions": "5000",
    "clicks": "150",
    "conversions": "5.0",
    "conversion_value": "250.00",
    "currency_code": "USD",
    "campaign_name": "Test Campaign",
    "ad_group_name": "Test Ad Group",
    "ad_type": "SEARCH",
    "device": "DESKTOP",
    "network": "SEARCH"
}'),
('google-2', '2024-01-16 08:00:00+00', '{
    "customer_id": "1234567890",
    "campaign_id": "987654321",
    "ad_group_id": "111222333",
    "ad_id": "444555777",
    "date": "2024-01-16",
    "cost_micros": null,
    "cost": "30.75",
    "impressions": "6000",
    "clicks": "180",
    "conversions": "6.0",
    "conversion_value": "300.00",
    "currency_code": "USD",
    "campaign_name": "Test Campaign",
    "ad_type": "SEARCH"
}');

-- Insert Tenant Connections
INSERT INTO test_airbyte.tenant_airbyte_connections VALUES
('conn-1', 'tenant-test-123', 'airbyte-conn-shopify-1', 'shopify', 'Shopify Test Connection', 'active', true, NOW(), NOW()),
('conn-2', 'tenant-test-123', 'airbyte-conn-meta-1', 'source-facebook-marketing', 'Meta Ads Test Connection', 'active', true, NOW(), NOW()),
('conn-3', 'tenant-test-123', 'airbyte-conn-google-1', 'source-google-ads', 'Google Ads Test Connection', 'active', true, NOW(), NOW());

-- Step 4: Verify test data was created
SELECT 'Shopify Orders' as table_name, COUNT(*) as record_count FROM test_airbyte._airbyte_raw_shopify_orders
UNION ALL
SELECT 'Shopify Customers', COUNT(*) FROM test_airbyte._airbyte_raw_shopify_customers
UNION ALL
SELECT 'Meta Ads', COUNT(*) FROM test_airbyte._airbyte_raw_meta_ads
UNION ALL
SELECT 'Google Ads', COUNT(*) FROM test_airbyte._airbyte_raw_google_ads
UNION ALL
SELECT 'Tenant Connections', COUNT(*) FROM test_airbyte.tenant_airbyte_connections;

-- Expected results:
-- Shopify Orders: 4
-- Shopify Customers: 2
-- Meta Ads: 2
-- Google Ads: 2
-- Tenant Connections: 3

-- ============================================================================
-- Setup Complete!
-- 
-- Next steps:
-- 1. Test data is ready in test_airbyte schema
-- 2. You can now run dbt models when network connectivity is available
-- 3. Or run models from Render service if available
-- ============================================================================
