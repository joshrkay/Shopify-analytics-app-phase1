# Billing API Documentation

REST API endpoints for subscription management.

## Base URL

```
Production: https://api.yourdomain.com
Development: http://localhost:8000
```

## Authentication

All endpoints require JWT authentication via Bearer token.

```http
Authorization: Bearer <jwt_token>
```

The JWT must contain:
- `org_id` (tenant_id) - Organization identifier
- `sub` (user_id) - User identifier

---

## Endpoints

### GET /api/billing/subscription

Get current subscription information for the authenticated tenant.

**Response: 200 OK**

```json
{
  "subscription_id": "sub_abc123",
  "plan_id": "plan_growth",
  "plan_name": "Growth",
  "status": "active",
  "is_active": true,
  "current_period_end": "2024-02-15T00:00:00Z",
  "trial_end": null,
  "can_access_features": true,
  "downgraded_reason": null
}
```

**Response: 200 OK (No Subscription)**

```json
{
  "subscription_id": null,
  "plan_id": "plan_free",
  "plan_name": "Free",
  "status": "none",
  "is_active": false,
  "current_period_end": null,
  "trial_end": null,
  "can_access_features": true,
  "downgraded_reason": "No active subscription"
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 401 | `unauthorized` | Missing or invalid JWT |
| 500 | `internal_error` | Server error |

---

### GET /api/billing/plans

List all available billing plans.

**Response: 200 OK**

```json
{
  "plans": [
    {
      "id": "plan_free",
      "name": "free",
      "display_name": "Free",
      "description": "Basic analytics for small stores",
      "price_monthly_cents": 0,
      "price_yearly_cents": 0,
      "features": ["dashboard_basic", "data_export_csv_limited"]
    },
    {
      "id": "plan_growth",
      "name": "growth",
      "display_name": "Growth",
      "description": "For growing businesses",
      "price_monthly_cents": 2900,
      "price_yearly_cents": 29000,
      "features": ["dashboard_basic", "dashboard_advanced", "data_export_csv", "ai_insights_limited"]
    },
    {
      "id": "plan_pro",
      "name": "pro",
      "display_name": "Pro",
      "description": "Advanced features for established stores",
      "price_monthly_cents": 7900,
      "price_yearly_cents": 79000,
      "features": ["all_features"]
    }
  ]
}
```

---

### POST /api/billing/checkout

Create a Shopify Billing checkout URL for a plan.

**Request Body:**

```json
{
  "plan_id": "plan_growth",
  "return_url": "https://yourapp.com/billing/callback",
  "interval": "monthly"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| plan_id | string | Yes | Plan ID to subscribe to |
| return_url | string | No | URL to redirect after checkout |
| interval | string | No | `monthly` or `annual` (default: monthly) |

**Response: 200 OK**

```json
{
  "checkout_url": "https://store.myshopify.com/admin/charges/123/confirm",
  "subscription_id": "sub_abc123",
  "shopify_subscription_id": "gid://shopify/AppSubscription/123"
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `invalid_plan` | Plan ID not found or inactive |
| 400 | `store_not_found` | No active Shopify store for tenant |
| 400 | `already_subscribed` | Already on this plan |
| 500 | `shopify_error` | Shopify API error |

---

### POST /api/billing/upgrade

Upgrade to a higher-tier plan.

**Request Body:**

```json
{
  "plan_id": "plan_pro",
  "timing": "immediate"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| plan_id | string | Yes | Target plan ID |
| timing | string | No | `immediate` or `next_cycle` (default: immediate) |

**Response: 200 OK**

```json
{
  "checkout_url": "https://store.myshopify.com/admin/charges/456/confirm",
  "subscription_id": "sub_abc123",
  "previous_plan_id": "plan_growth",
  "new_plan_id": "plan_pro",
  "effective_at": "immediate"
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `invalid_plan` | Plan not found |
| 400 | `not_an_upgrade` | Target plan is same or lower tier |
| 400 | `no_active_subscription` | No current subscription to upgrade |

---

### POST /api/billing/downgrade

Downgrade to a lower-tier plan.

**Request Body:**

```json
{
  "plan_id": "plan_growth"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| plan_id | string | Yes | Target plan ID |

**Response: 200 OK**

```json
{
  "subscription_id": "sub_abc123",
  "previous_plan_id": "plan_pro",
  "new_plan_id": "plan_growth",
  "effective_at": "2024-02-15T00:00:00Z",
  "message": "Downgrade scheduled for end of billing period"
}
```

**Note:** Downgrades always take effect at the end of the current billing period.

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `invalid_plan` | Plan not found |
| 400 | `not_a_downgrade` | Target plan is same or higher tier |
| 400 | `no_active_subscription` | No current subscription |

---

### POST /api/billing/cancel

Cancel the current subscription.

**Request Body:**

```json
{
  "reason": "no_longer_needed",
  "feedback": "Optional feedback text"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| reason | string | No | Cancellation reason code |
| feedback | string | No | Free-text feedback |

**Response: 200 OK**

```json
{
  "subscription_id": "sub_abc123",
  "status": "cancelled",
  "cancelled_at": "2024-01-15T10:30:00Z",
  "access_until": "2024-02-15T00:00:00Z",
  "message": "Subscription cancelled. Access continues until end of billing period."
}
```

---

### GET /api/billing/entitlements

Get current feature entitlements for the authenticated tenant.

**Response: 200 OK**

```json
{
  "plan_id": "plan_growth",
  "entitlements": {
    "dashboard_basic": true,
    "dashboard_advanced": true,
    "dashboard_custom": false,
    "data_export_csv": true,
    "data_export_api": false,
    "ai_insights": true,
    "ai_actions": false,
    "custom_reports": false,
    "api_access": "limited"
  },
  "limits": {
    "max_dashboards": 10,
    "max_users": 5,
    "api_calls_per_month": 10000,
    "ai_insights_per_month": 50,
    "data_retention_days": 90
  },
  "usage": {
    "dashboards_used": 3,
    "users_count": 2,
    "api_calls_this_month": 1250,
    "ai_insights_this_month": 12
  }
}
```

---

### GET /api/billing/invoices

List billing invoices/history.

**Query Parameters:**

| Param | Type | Description |
|-------|------|-------------|
| limit | int | Max results (default: 10, max: 100) |
| offset | int | Pagination offset |

**Response: 200 OK**

```json
{
  "invoices": [
    {
      "id": "inv_123",
      "date": "2024-01-15T00:00:00Z",
      "amount_cents": 2900,
      "currency": "USD",
      "status": "paid",
      "plan_name": "Growth",
      "period_start": "2024-01-15T00:00:00Z",
      "period_end": "2024-02-15T00:00:00Z"
    }
  ],
  "total": 12,
  "limit": 10,
  "offset": 0
}
```

---

## Webhook Endpoints

### POST /api/webhooks/shopify/subscription-update

Receives Shopify `app_subscriptions/update` webhooks.

**Headers Required:**

| Header | Description |
|--------|-------------|
| X-Shopify-Hmac-Sha256 | HMAC signature |
| X-Shopify-Shop-Domain | Shop domain |
| X-Shopify-Topic | Webhook topic |

**Response: 200 OK**

```json
{
  "received": true,
  "message": "Processed status: ACTIVE"
}
```

---

## Error Response Format

All error responses follow this format:

```json
{
  "error": {
    "code": "error_code",
    "message": "Human-readable error message",
    "details": {
      "field": "Additional context"
    }
  }
}
```

## Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `unauthorized` | 401 | Missing or invalid authentication |
| `forbidden` | 403 | Insufficient permissions |
| `not_found` | 404 | Resource not found |
| `invalid_plan` | 400 | Invalid plan ID |
| `store_not_found` | 400 | No Shopify store linked |
| `no_active_subscription` | 400 | No active subscription |
| `already_subscribed` | 400 | Already on target plan |
| `shopify_error` | 500 | Shopify API error |
| `internal_error` | 500 | Server error |

## Rate Limiting

| Endpoint | Limit |
|----------|-------|
| All endpoints | 100 requests/minute per tenant |
| POST /checkout | 10 requests/minute per tenant |
| Webhooks | Unlimited (Shopify-initiated) |

## Retry Guidance

For 5xx errors:
- Retry with exponential backoff: 1s, 2s, 4s, 8s
- Max 4 retries
- Include `X-Request-ID` header for debugging

For 429 (rate limited):
- Check `Retry-After` header
- Wait specified seconds before retry
