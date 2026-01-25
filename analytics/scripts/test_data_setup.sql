-- Test Data Setup Script
-- 
-- This script creates test data that mimics Airbyte raw table structure
-- Run this in your test database to validate staging models
--
-- Usage:
--   1. Connect to test database
--   2. Run this script to create test tables and data
--   3. Run: dbt run --select staging
--   4. Run: dbt test --select staging
--   5. Verify results

-- Create test schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS test_airbyte;

-- Test data for _airbyte_raw_shopify_orders
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_shopify_orders (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Test data for _airbyte_raw_shopify_customers
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_shopify_customers (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Test data for _airbyte_raw_meta_ads
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_meta_ads (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Test data for _airbyte_raw_google_ads
CREATE TABLE IF NOT EXISTS test_airbyte._airbyte_raw_google_ads (
    _airbyte_ab_id VARCHAR(255) PRIMARY KEY,
    _airbyte_emitted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    _airbyte_data JSONB NOT NULL
);

-- Insert test Shopify orders
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
-- Edge case: Order with null ID (should be filtered out)
('order-3', '2024-01-17 12:00:00+00', '{
    "id": null,
    "name": "#1003",
    "order_number": "1003",
    "email": "customer3@example.com",
    "created_at": "2024-01-17T12:00:00Z",
    "total_price": "50.00",
    "currency": "USD"
}'),
-- Edge case: Order with invalid price (should default to 0.0)
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

-- Insert test Shopify customers
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

-- Insert test Meta Ads data
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
    "objective": "CONVERSIONS",
    "reach": "4500",
    "frequency": "1.11",
    "cpm": "5.10",
    "cpp": "5.10",
    "ctr": "3.00"
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

-- Insert test Google Ads data
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
    "network": "SEARCH",
    "ctr": "3.00",
    "average_cpc": "0.17",
    "cost_per_conversion": "5.10"
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

-- Create test tenant_airbyte_connections data
CREATE TABLE IF NOT EXISTS test_airbyte.tenant_airbyte_connections (
    id VARCHAR(255) PRIMARY KEY,
    tenant_id VARCHAR(255) NOT NULL,
    airbyte_connection_id VARCHAR(255) NOT NULL,
    source_type VARCHAR(100),
    status VARCHAR(50),
    is_enabled BOOLEAN,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO test_airbyte.tenant_airbyte_connections VALUES
('conn-1', 'tenant-test-123', 'airbyte-conn-shopify-1', 'shopify', 'active', true, NOW(), NOW()),
('conn-2', 'tenant-test-123', 'airbyte-conn-meta-1', 'source-facebook-marketing', 'active', true, NOW(), NOW()),
('conn-3', 'tenant-test-123', 'airbyte-conn-google-1', 'source-google-ads', 'active', true, NOW(), NOW());
