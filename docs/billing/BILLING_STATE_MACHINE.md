# Billing State Machine

This document defines all subscription states, valid transitions, and error recovery paths.

## Subscription States

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SUBSCRIPTION STATE MACHINE                          │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌──────────┐
                              │  START   │
                              └────┬─────┘
                                   │
                                   │ Checkout initiated
                                   ▼
                    ┌────────────────────────────────┐
                    │           PENDING              │
                    │   (Awaiting merchant approval) │
                    └────────────┬───────────────────┘
                                 │
            ┌────────────────────┼────────────────────┐
            │                    │                    │
            ▼                    ▼                    ▼
    ┌───────────┐        ┌───────────┐        ┌───────────┐
    │ DECLINED  │        │  ACTIVE   │        │  EXPIRED  │
    │  (End)    │        │           │        │   (End)   │
    └───────────┘        └─────┬─────┘        └───────────┘
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
            │ Payment          │ Cancel           │ Upgrade/
            │ Failed           │ requested        │ Downgrade
            ▼                  ▼                  ▼
    ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
    │    FROZEN     │  │  CANCELLED    │  │    ACTIVE     │
    │ (Grace period)│  │    (End)      │  │  (New plan)   │
    └───────┬───────┘  └───────────────┘  └───────────────┘
            │
    ┌───────┴───────┐
    │               │
    │ Payment       │ Grace period
    │ resolved      │ expired
    ▼               ▼
┌───────────┐  ┌───────────┐
│  ACTIVE   │  │ CANCELLED │
│           │  │   (End)   │
└───────────┘  └───────────┘
```

## State Definitions

| State | Code | Description | Access Level |
|-------|------|-------------|--------------|
| **PENDING** | `pending` | Checkout created, awaiting merchant approval in Shopify | None (pending) |
| **ACTIVE** | `active` | Subscription is active and in good standing | Full |
| **FROZEN** | `frozen` | Payment failed, subscription in grace period | Full (configurable) |
| **CANCELLED** | `cancelled` | Subscription cancelled by merchant or system | None |
| **DECLINED** | `declined` | Merchant declined the charge in Shopify | None |
| **EXPIRED** | `expired` | Trial expired without conversion | None |

## Valid State Transitions

### From PENDING

| To State | Trigger | Webhook Topic | Notes |
|----------|---------|---------------|-------|
| ACTIVE | Merchant approves | `app_subscriptions/update` (status=ACTIVE) | Begin billing |
| DECLINED | Merchant declines | `app_subscriptions/update` (status=DECLINED) | End state |
| EXPIRED | Approval timeout | System timeout (7 days default) | End state |

### From ACTIVE

| To State | Trigger | Webhook Topic | Notes |
|----------|---------|---------------|-------|
| FROZEN | Payment fails | `app_subscriptions/update` (status=FROZEN) | Start grace period |
| CANCELLED | Merchant cancels | `app_subscriptions/update` (status=CANCELLED) | End state |
| ACTIVE | Plan change | `app_subscriptions/update` | New subscription ID |

### From FROZEN

| To State | Trigger | Webhook Topic | Notes |
|----------|---------|---------------|-------|
| ACTIVE | Payment resolves | `app_subscriptions/update` (status=ACTIVE) | Clear grace period |
| CANCELLED | Grace period expires | System (reconciliation job) | End state |
| CANCELLED | Merchant cancels | `app_subscriptions/update` (status=CANCELLED) | End state |

### Invalid Transitions (Should Never Occur)

| From | To | Action if Detected |
|------|----|--------------------|
| CANCELLED | ACTIVE | CRITICAL alert, investigate |
| DECLINED | ACTIVE | CRITICAL alert, investigate |
| EXPIRED | ACTIVE | CRITICAL alert, investigate |
| Any | PENDING | Invalid, log error |

## Grace Period Behavior

### Timeline

```
Day 0: Payment fails → Status: FROZEN
       └── Grace period starts (configurable: 3-14 days)
       └── Customer notified
       └── Access: [FULL / LIMITED / READ-ONLY] (configurable)

Day X-3: Warning notification sent
         └── "3 days remaining to update payment"

Day X: Grace period expires
       └── Status: CANCELLED
       └── Access: NONE
       └── Downgrade to Free tier entitlements
```

### Access During Grace Period (Configurable)

| Option | Description | Recommendation |
|--------|-------------|----------------|
| FULL | All features available | Best for customer retention |
| LIMITED | Core features only | Balance retention/urgency |
| READ_ONLY | Can view but not modify | Strong urgency |
| NONE | Immediate block | Not recommended |

## Error Recovery Paths

### Scenario: Webhook Never Received

```
1. Reconciliation job runs (hourly)
2. Detects: Local=PENDING, Shopify=ACTIVE
3. Action: Update local to ACTIVE
4. Log: event_type=subscription_updated, source=reconciliation
```

### Scenario: Out-of-Order Webhooks

```
1. Webhook A (older) arrives after Webhook B (newer)
2. Check: Webhook A timestamp vs local updated_at
3. If older: Ignore webhook (state already newer)
4. If newer: Apply webhook (shouldn't happen, but handle gracefully)
5. Log: Warning with both timestamps
```

### Scenario: Duplicate Webhook

```
1. Webhook arrives with same event ID
2. Check: event_id in billing_webhook_events table
3. If exists: Return 200, skip processing
4. If new: Process and store event_id
```

### Scenario: Shopify API Timeout During State Check

```
1. API call times out
2. Retry with exponential backoff (2s, 4s, 8s, max 3 retries)
3. If all retries fail: Skip this subscription, log warning
4. Next reconciliation run will retry
```

## State Transition Logging

Every state transition MUST be logged to `billing_events` table:

```json
{
  "id": "evt_uuid",
  "tenant_id": "org_xxx",
  "event_type": "subscription_updated",
  "subscription_id": "sub_xxx",
  "shopify_subscription_id": "gid://shopify/AppSubscription/123",
  "metadata": {
    "previous_state": "pending",
    "new_state": "active",
    "source": "webhook",
    "shopify_event_id": "evt_shopify_xxx",
    "triggered_by": "merchant_approval"
  },
  "created_at": "2024-01-15T10:30:00Z"
}
```

## Monitoring Checklist

| Check | Frequency | Alert Threshold |
|-------|-----------|-----------------|
| Stuck PENDING subscriptions | Hourly | > 7 days old |
| Invalid state transitions | Real-time | Any occurrence |
| Grace periods expiring today | Daily | List for CS team |
| Reconciliation drift count | Per job | > 10 per run |

## Code Reference

- State enum: `backend/src/models/subscription.py:SubscriptionStatus`
- Transitions: `backend/src/services/billing_service.py`
- Reconciliation: `backend/src/jobs/reconcile_subscriptions.py`
- Webhooks: `backend/src/api/routes/webhooks_shopify.py`
