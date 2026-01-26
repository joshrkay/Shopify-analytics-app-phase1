# Source of Truth & Reconciliation Rules

> **HUMAN DECISION REQUIRED**: Reconciliation rules determine how conflicts between Shopify and local state are resolved.

## Source of Truth Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    SHOPIFY BILLING API                       │
│                  (ALWAYS SOURCE OF TRUTH)                    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LOCAL DATABASE                            │
│                  (Derived/Cached State)                      │
└─────────────────────────────────────────────────────────────┘
```

**Principle**: Shopify Billing API is ALWAYS the authoritative source. Our database is a cache/derived state that must be reconcilable.

## Reconciliation Strategy

### Automated Reconciliation Job

| Setting | Value |
|---------|-------|
| Frequency | Every __ hours (recommended: 1-4 hours) |
| Max stores per run | 100 (for rate limiting) |
| Subscription age cutoff | 90 days (don't check very old) |

### Reconciliation Actions

| Local State | Shopify State | Action |
|-------------|---------------|--------|
| ACTIVE | ACTIVE | No action (consistent) |
| ACTIVE | CANCELLED | Update local to CANCELLED, log event |
| ACTIVE | FROZEN | Update local to FROZEN, start grace period |
| PENDING | ACTIVE | Update local to ACTIVE |
| PENDING | DECLINED | Update local to DECLINED |
| FROZEN | ACTIVE | Update local to ACTIVE (payment resolved) |
| FROZEN | CANCELLED | Update local to CANCELLED |
| CANCELLED | ACTIVE | **ALERT**: Unexpected state, investigate |
| Any | Not found | Mark subscription as orphaned, investigate |

### Drift Detection Alerts

| Scenario | Alert Level | Action |
|----------|-------------|--------|
| Status mismatch | INFO | Auto-correct, log |
| Subscription not found in Shopify | WARNING | Investigate within 24h |
| Local says CANCELLED, Shopify says ACTIVE | CRITICAL | Immediate investigation |
| Multiple active subscriptions | CRITICAL | Immediate investigation |

## Manual Override Process

### When Manual Override is Needed
- Customer support escalation
- Billing dispute resolution
- System error correction
- Fraud investigation

### Override Workflow

```
1. Support/Admin identifies issue
2. Create ticket with:
   - Tenant ID
   - Subscription ID
   - Current state (local + Shopify)
   - Desired state
   - Justification
3. Engineering reviews
4. Apply override via admin tool
5. Log override with full audit trail
6. Notify customer if applicable
```

### Override Audit Requirements

| Field | Required |
|-------|----------|
| Admin user ID | Yes |
| Timestamp | Yes |
| Previous state | Yes |
| New state | Yes |
| Justification | Yes |
| Ticket reference | Yes |
| Shopify state at time of override | Yes |

## Conflict Resolution Scenarios

### Scenario 1: Webhook Missed
**Symptom**: Local state is stale (e.g., still PENDING but Shopify shows ACTIVE)

**Resolution**:
1. Reconciliation job detects mismatch
2. Updates local state to match Shopify
3. Logs event with `source: "reconciliation"`
4. No customer notification needed

### Scenario 2: Webhook Delayed
**Symptom**: State changes arrive out of order

**Resolution**:
1. Check Shopify event timestamp vs local last_updated
2. If Shopify event is newer, apply change
3. If Shopify event is older, ignore (already processed newer state)
4. Log for monitoring

### Scenario 3: Shopify Says ACTIVE, App Says CANCELLED
**Symptom**: Customer reports features not working, but payment is active

**Resolution**:
1. CRITICAL alert triggered
2. Immediate investigation
3. Manual correction with customer notification
4. Root cause analysis
5. Post-mortem if systemic issue

### Scenario 4: Double Subscription
**Symptom**: Multiple ACTIVE subscriptions for same tenant

**Resolution**:
1. CRITICAL alert triggered
2. Keep newest subscription, cancel older via Shopify API
3. Update local state
4. Customer notification (if charges duplicated)
5. Potential refund processing

## Reconciliation Job Configuration

```json
{
  "reconciliation": {
    "enabled": true,
    "frequency_hours": 1,
    "max_stores_per_run": 100,
    "max_subscription_age_days": 90,
    "rate_limit_delay_ms": 500,
    "alert_thresholds": {
      "drift_count_warning": 10,
      "drift_count_critical": 50,
      "error_rate_warning": 0.05,
      "error_rate_critical": 0.1
    }
  }
}
```

## Monitoring & Alerts

### Metrics to Track

| Metric | Alert Threshold |
|--------|-----------------|
| Reconciliation job duration | > 30 minutes |
| Subscriptions corrected per run | > 10 (warning), > 50 (critical) |
| API errors during reconciliation | > 5% |
| Orphaned subscriptions found | Any |
| Critical state mismatches | Any |

### Dashboard Queries

```sql
-- Drift detection
SELECT
  COUNT(*) as total_drifts,
  COUNT(CASE WHEN metadata->>'source' = 'reconciliation' THEN 1 END) as auto_corrected
FROM billing_events
WHERE event_type = 'subscription_updated'
  AND created_at > NOW() - INTERVAL '24 hours';

-- Orphaned subscriptions
SELECT * FROM tenant_subscriptions
WHERE status IN ('active', 'pending', 'frozen')
  AND shopify_subscription_id IS NOT NULL
  AND updated_at < NOW() - INTERVAL '7 days';
```

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Engineering Lead | | | |
| Product Owner | | | |
| DevOps | | | |
