# Data Quality Rules

This document describes the data quality rules and checks implemented in the Shopify Analytics App.

## Overview

The data quality system performs two types of checks:
1. **Freshness Checks**: Verify data is up-to-date per source SLAs
2. **Anomaly Detection**: Identify data quality issues

## Freshness Checks

### Source-Specific SLAs

#### Critical Sources (2-Hour SLA)

These sources are critical for core business metrics and have aggressive SLAs:

| Source | Warning | High | Critical | Rationale |
|--------|---------|------|----------|-----------|
| Shopify Orders | 2h | 4h | 8h | Core revenue tracking |
| Shopify Refunds | 2h | 4h | 8h | Revenue adjustments |
| Recharge | 2h | 4h | 8h | Subscription revenue |

#### Standard Sources (24-Hour SLA)

These sources update less frequently and have relaxed SLAs:

| Source | Warning | High | Critical | Rationale |
|--------|---------|------|----------|-----------|
| Meta Ads | 24h | 48h | 96h | Daily reporting cycle |
| Google Ads | 24h | 48h | 96h | Daily reporting cycle |
| TikTok Ads | 24h | 48h | 96h | Daily reporting cycle |
| Pinterest Ads | 24h | 48h | 96h | Daily reporting cycle |
| Snap Ads | 24h | 48h | 96h | Daily reporting cycle |
| Amazon Ads | 24h | 48h | 96h | Daily reporting cycle |
| Klaviyo | 24h | 48h | 96h | Email metrics delay |
| Postscript | 24h | 48h | 96h | SMS metrics delay |
| Attentive | 24h | 48h | 96h | SMS metrics delay |
| GA4 | 24h | 48h | 96h | GA processing delay |

### Severity Calculation

```python
def calculate_severity(minutes_since_sync, source_type):
    thresholds = FRESHNESS_THRESHOLDS[source_type]

    if minutes_since_sync > thresholds["critical"]:  # >4x
        return CRITICAL
    elif minutes_since_sync > thresholds["high"]:    # 2x-4x
        return HIGH
    elif minutes_since_sync > thresholds["warning"]: # 1x-2x
        return WARNING
    else:
        return None  # Fresh
```

### Multiplier Logic

| Multiplier | Severity | Description |
|------------|----------|-------------|
| 1x-2x | Warning | Slightly delayed, logged only |
| 2x-4x | High | Delayed, Slack alert |
| >4x | Critical | Significantly delayed, PagerDuty |

## Anomaly Detection

### Row Count Drop (>=50%)

Detects when daily row counts drop significantly compared to previous day.

```python
check_type: row_count_drop
threshold_percent: 50.0

# Logic
if (previous_count - current_count) / previous_count >= 0.50:
    trigger_anomaly()
```

**Severity:**
- 50-75% drop: WARNING
- >75% drop: HIGH

**Merchant Message:**
> We noticed a significant drop in data volume. This may indicate a sync issue.

**Recommended Actions:**
1. Verify source data
2. Run backfill
3. Contact support

---

### Zero Spend Anomaly

Detects when ad spend becomes zero when previously non-zero.

```python
check_type: zero_spend

# Logic
if current_spend == 0 and previous_spend > 0:
    trigger_anomaly()
```

**Severity:** HIGH

**Merchant Message:**
> Your ad spend is showing as zero. This may indicate a connection issue with your ad platform.

**Recommended Actions:**
1. Check ad account status
2. Reconnect ad platform
3. Verify billing

---

### Zero Orders Anomaly

Detects when orders become zero when previously non-zero.

```python
check_type: zero_orders

# Logic
if current_orders == 0 and previous_orders > 0:
    trigger_anomaly()
```

**Severity:** CRITICAL (orders are business-critical)

**Merchant Message:**
> No orders detected. This may indicate a sync issue with Shopify.

**Recommended Actions:**
1. Check Shopify connection
2. Retry sync
3. Verify store status

---

### Missing Days Detection

Detects gaps in time series data.

```python
check_type: missing_days

# Logic
missing = expected_dates - actual_dates
if len(missing) > 0:
    trigger_anomaly()
```

**Severity:**
- 1-3 missing days: WARNING
- >3 missing days: HIGH

**Merchant Message:**
> Some days are missing from your data. Reports may be incomplete.

**Recommended Actions:**
1. Run backfill for missing dates
2. Verify sync schedule

---

### Negative Values Detection

Detects negative values in fields that should be positive.

```python
check_type: negative_values

# Fields checked:
- revenue
- spend
- order_count
- quantity

# Logic
if any(value < 0 for value in field_values):
    trigger_anomaly()
```

**Severity:** HIGH

**Merchant Message:**
> Unexpected negative values detected in your data.

**Recommended Actions:**
1. Review source data
2. Contact support

---

### Duplicate Primary Key Detection

Detects duplicate records based on primary key.

```python
check_type: duplicate_primary_key

# Logic
if count(distinct pk) < count(*):
    duplicate_count = count(*) - count(distinct pk)
    trigger_anomaly()
```

**Severity:** HIGH

**Merchant Message:**
> Duplicate records detected. This may cause inaccurate reporting.

**Recommended Actions:**
1. Investigate duplicates
2. Run deduplication
3. Contact support

## Event Types

The DQ system emits the following events for alerting:

| Event Type | Description |
|------------|-------------|
| `dq.freshness_failed` | Freshness check failed |
| `dq.anomaly_detected` | Anomaly detected in data |
| `dq.severe_block` | Issue severe enough to block dashboards |
| `dq.resolved` | Previously failing check is now passing |

## Incident Management

### Incident Lifecycle

```
OPEN → ACKNOWLEDGED → RESOLVED/AUTO_RESOLVED
```

### Auto-Resolution

Incidents are automatically resolved when:
- Freshness check passes after previous failure
- Anomaly condition is no longer present

### Blocking Incidents

An incident blocks dashboards when:
1. Severity is CRITICAL AND
2. Source is critical (Shopify, Recharge) OR
3. Issue persists beyond 4x threshold

## Configuration

### Check Definitions (dq_checks table)

```sql
INSERT INTO dq_checks (
    check_name,
    check_type,
    source_type,
    warning_threshold,
    high_threshold,
    critical_threshold,
    description,
    merchant_message,
    recommended_actions
) VALUES (
    'freshness_shopify_orders',
    'freshness',
    'shopify_orders',
    120,   -- 2 hours
    240,   -- 4 hours
    480,   -- 8 hours
    'Checks Shopify orders data freshness',
    'Your Shopify orders data may be delayed.',
    '["Retry sync", "Check Shopify connection"]'
);
```

### Adding New Checks

1. Add check definition to migration
2. Implement check logic in `DQService`
3. Add routing in `AlertRouter`
4. Update documentation

### Modifying Thresholds

Thresholds are configured in:
1. `models/dq_models.py` - `FRESHNESS_THRESHOLDS` constant
2. `migrations/dq_schema.sql` - Seed data

To modify:
```python
FRESHNESS_THRESHOLDS = {
    ConnectorSourceType.SHOPIFY_ORDERS: {
        "warning": 120,   # Modify this value
        "high": 240,
        "critical": 480,
    },
    # ...
}
```

## Testing

### Unit Tests

```bash
# Run threshold tests
pytest tests/test_dq_thresholds.py -v

# Run specific test
pytest tests/test_dq_thresholds.py::TestFreshnessThresholds -v
```

### Test Cases

| Test | Description |
|------|-------------|
| `test_shopify_orders_2_hour_sla` | Verify 2h SLA for Shopify |
| `test_severity_escalation` | Verify warning→high→critical |
| `test_row_count_drop_50_percent` | Verify 50% drop detection |
| `test_zero_spend_anomaly` | Verify zero spend detection |
| `test_tenant_isolation` | Verify no cross-tenant access |

## Operational Runbook

### High Alert Volume

If receiving many freshness alerts:
1. Check Airbyte cluster health
2. Verify API rate limits not exceeded
3. Check source API status pages
4. Consider adjusting cooldown periods

### False Positives

If anomaly checks are triggering incorrectly:
1. Review threshold configuration
2. Check for seasonal patterns
3. Consider adding baseline adjustment
4. Update check logic if needed

### Adding New Source Type

1. Add to `ConnectorSourceType` enum
2. Add thresholds to `FRESHNESS_THRESHOLDS`
3. Add check definition in migration
4. Update source type mapping in service
5. Test with new connector

## Future Enhancements

- [ ] ML-based anomaly detection
- [ ] Custom thresholds per tenant
- [ ] Baseline learning for seasonality
- [ ] Correlation detection across sources
- [ ] Predictive alerting
