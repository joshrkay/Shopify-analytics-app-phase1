# Sync Health Monitoring

This document describes the sync health monitoring system for the Shopify Analytics App.

## Overview

The sync health system monitors data freshness and quality across all connected data sources, providing:
- Real-time freshness monitoring with source-specific SLAs
- Anomaly detection for data quality issues
- Severity-based alerting (Slack, PagerDuty)
- Merchant-facing health dashboard
- Self-service backfill capability (up to 90 days)

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │     │   Backend API   │     │   Background    │
│   (React)       │────▶│   (FastAPI)     │◀────│   Jobs          │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                         PostgreSQL                               │
│  ┌──────────┐ ┌───────────┐ ┌────────────┐ ┌─────────────┐     │
│  │dq_checks │ │dq_results │ │dq_incidents│ │backfill_jobs│     │
│  └──────────┘ └───────────┘ └────────────┘ └─────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### Backend

| File | Description |
|------|-------------|
| `api/dq/service.py` | Core DQ service with freshness and anomaly checks |
| `api/dq/routes.py` | REST API endpoints for sync health |
| `api/dq/alerts/slack.py` | Slack webhook integration |
| `api/dq/alerts/pagerduty.py` | PagerDuty Events API integration |
| `api/dq/alerts/router.py` | Alert routing by severity |
| `jobs/dq_runner.py` | Background job for periodic checks |
| `jobs/retention_cleanup.py` | 13-month data retention enforcement |

### Frontend

| File | Description |
|------|-------------|
| `pages/SyncHealth.tsx` | Main sync health dashboard page |
| `components/ConnectorHealthCard.tsx` | Per-connector health display |
| `components/BackfillModal.tsx` | Backfill trigger modal |
| `services/syncHealthApi.ts` | API client for sync health |

### Database

| Table | Description |
|-------|-------------|
| `dq_checks` | Check definitions and thresholds |
| `dq_results` | Per-run check results (13-month retention) |
| `dq_incidents` | Severe failures and dashboard blocks |
| `sync_runs` | Sync execution tracking |
| `backfill_jobs` | Merchant-triggered backfills |

## API Endpoints

### Sync Health

```
GET  /api/sync-health/summary          # Overall health summary
GET  /api/sync-health/connector/{id}   # Per-connector health
GET  /api/sync-health/incidents        # Open incidents
POST /api/sync-health/incidents/{id}/acknowledge  # Acknowledge incident
GET  /api/sync-health/dashboard-block  # Check if dashboards blocked
```

### Backfill

```
GET  /api/sync-health/connectors/{id}/backfill/estimate  # Estimate backfill
POST /api/sync-health/connectors/{id}/backfill           # Trigger backfill
GET  /api/sync-health/connectors/{id}/backfill/status    # Check status
```

## Freshness SLAs

| Source Type | Warning | High | Critical |
|-------------|---------|------|----------|
| Shopify Orders/Refunds | 2 hours | 4 hours | 8 hours |
| Recharge | 2 hours | 4 hours | 8 hours |
| Meta Ads | 24 hours | 48 hours | 96 hours |
| Google Ads | 24 hours | 48 hours | 96 hours |
| TikTok Ads | 24 hours | 48 hours | 96 hours |
| Pinterest Ads | 24 hours | 48 hours | 96 hours |
| Snap Ads | 24 hours | 48 hours | 96 hours |
| Amazon Ads | 24 hours | 48 hours | 96 hours |
| Klaviyo | 24 hours | 48 hours | 96 hours |
| Postscript (SMS) | 24 hours | 48 hours | 96 hours |
| Attentive (SMS) | 24 hours | 48 hours | 96 hours |
| GA4 | 24 hours | 48 hours | 96 hours |

## Severity Levels

| Severity | Threshold | Alert Channel |
|----------|-----------|---------------|
| Warning | 1x-2x threshold | Logged only |
| High | 2x-4x threshold | Slack #alerts |
| Critical | >4x threshold | PagerDuty + Slack |

## Alert Routing

```yaml
critical:
  - PagerDuty (page on-call)
  - Slack #alerts

high:
  - Slack #alerts

warning:
  - Logged (no external notification)
```

## Backfill Limits

| User Type | Max Days |
|-----------|----------|
| Merchant | 90 days |
| Support | Unlimited (via admin API) |

## Blocking Behavior

Dashboards are blocked when:
- Critical fact tables (Shopify orders) are empty
- Prolonged staleness (>4x threshold) on critical sources
- Security risk detected

## Environment Variables

```bash
# Alert Configuration
SLACK_DQ_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_DQ_COOLDOWN_MINUTES=15

PAGERDUTY_DQ_ROUTING_KEY=your-routing-key
PAGERDUTY_DQ_COOLDOWN_MINUTES=15

# Retention
DQ_RETENTION_MONTHS=13

# Job Configuration
DQ_BATCH_SIZE=50
DQ_CLEANUP_BATCH_SIZE=1000
```

## Running Jobs

### DQ Runner (Periodic Checks)

```bash
# Run as cron job (every 15 minutes)
python -m src.jobs.dq_runner
```

### Retention Cleanup

```bash
# Run as daily cron job
python -m src.jobs.retention_cleanup
```

## Merchant Experience

### Sync Health Page

The sync health page shows:
1. Overall health score (0-100)
2. Status counts (healthy, delayed, error)
3. Per-connector cards with:
   - Status badge (Healthy/Delayed/Error)
   - Last sync time
   - Rows synced
   - Recommended actions
   - Backfill button

### Dashboard Blocking

When data issues are critical:
1. Banner shows blocking message
2. Affected dashboards show error state
3. Clear next steps provided
4. Support contact option

### Backfill Flow

1. Click "Run Backfill" on connector card
2. Select date range (max 90 days)
3. Review estimate and warnings
4. Confirm to start backfill
5. Notification on completion

## Monitoring

### Metrics

- `dq.freshness_check.duration_seconds`
- `dq.freshness_check.failures_total`
- `dq.anomaly_check.detections_total`
- `dq.incident.created_total`
- `dq.incident.resolved_total`
- `dq.backfill.requested_total`
- `dq.backfill.completed_total`

### Dashboards

- Sync Health Overview (Grafana)
- Alert History (PagerDuty)
- Slack #alerts channel

## Security

- All endpoints require JWT authentication
- Tenant isolation enforced at service and repository layers
- No cross-tenant data access
- Audit logging for all backfill operations
- Secrets never exposed in responses

## Troubleshooting

### Common Issues

**Connector shows "Never Synced"**
- Verify connector is properly configured
- Check Airbyte connection status
- Trigger manual sync

**High staleness despite recent sync**
- Check for sync failures in job history
- Verify API credentials are valid
- Review rate limit status

**Backfill fails immediately**
- Check for active backfill (only one allowed)
- Verify date range is within 90 days
- Ensure connector exists and is owned by tenant

### Support Escalation

For issues beyond self-service:
1. Support reviews full diagnostics
2. Access to extended backfill (>90 days)
3. Manual incident resolution
4. API credential rotation
