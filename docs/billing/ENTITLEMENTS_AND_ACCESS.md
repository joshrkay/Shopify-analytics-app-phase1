# Entitlements & Access Control Mapping

> **HUMAN DECISION REQUIRED**: Feature entitlements directly impact product value and revenue.

## Feature-to-Plan Mapping

### Core Features

| Feature Key | Description | Free | Growth | Pro | Enterprise |
|-------------|-------------|------|--------|-----|------------|
| `dashboard_basic` | Basic dashboard access | Yes | Yes | Yes | Yes |
| `dashboard_advanced` | Advanced analytics dashboards | No | Yes | Yes | Yes |
| `dashboard_custom` | Custom dashboard builder | No | No | Yes | Yes |
| `data_export_csv` | Export data to CSV | Limited | Yes | Yes | Yes |
| `data_export_api` | Programmatic data export | No | No | Yes | Yes |
| `ai_insights` | AI-powered insights | No | Limited | Yes | Yes |
| `ai_actions` | AI-recommended actions | No | No | Yes | Yes |
| `custom_reports` | Custom report builder | No | No | Yes | Yes |
| `scheduled_reports` | Automated report delivery | No | Yes | Yes | Yes |
| `multi_store` | Multiple store management | No | No | Yes | Yes |
| `agency_features` | Agency dashboard/management | No | No | No | Yes |
| `api_access` | REST API access | No | Limited | Full | Full |
| `priority_support` | Priority customer support | No | No | Yes | Yes |
| `dedicated_support` | Dedicated account manager | No | No | No | Yes |

### Usage Limits

| Limit Key | Free | Growth | Pro | Enterprise |
|-----------|------|--------|-----|------------|
| `max_dashboards` | 2 | 10 | 50 | Unlimited |
| `max_users` | 1 | 5 | 20 | Unlimited |
| `api_calls_per_month` | 0 | 10,000 | 100,000 | Unlimited |
| `ai_insights_per_month` | 0 | 50 | 500 | Unlimited |
| `data_retention_days` | 30 | 90 | 365 | Unlimited |
| `export_rows_per_request` | 100 | 10,000 | 100,000 | Unlimited |

## Access Control Types

### Hard-Blocked Features
Features that are completely inaccessible without the required plan.

| Feature | Behavior When Blocked |
|---------|----------------------|
| `ai_insights` | Show upgrade prompt, no partial access |
| `custom_reports` | Show upgrade prompt |
| `api_access` | Return 403 with upgrade message |
| `agency_features` | Hidden from navigation |

### Soft-Blocked Features
Features that show limited/preview access to encourage upgrade.

| Feature | Soft-Block Behavior |
|---------|---------------------|
| `dashboard_advanced` | Show blurred preview with upgrade CTA |
| `data_export_csv` | Allow limited rows, prompt for more |
| `scheduled_reports` | Show feature, prompt on schedule creation |

## Entitlement Change Timing

### On Upgrade

| Timing | Behavior |
|--------|----------|
| **Immediate** | New entitlements available instantly after checkout |

### On Downgrade

| Timing | Behavior |
|--------|----------|
| **End of Billing Cycle** | Current entitlements maintained until period ends |

### On Payment Failure (Grace Period)

| Phase | Entitlement Behavior |
|-------|---------------------|
| Grace period active | Full entitlements maintained |
| Grace period expired | Downgrade to Free tier entitlements |

### On Cancellation

| Timing | Behavior |
|--------|----------|
| Immediate | Entitlements revoked, downgrade to Free |
| OR End of period | Entitlements maintained until period ends |

## Data Handling During Entitlement Changes

### Dashboards
| Scenario | Behavior |
|----------|----------|
| Downgrade with excess dashboards | [ ] Archive excess [ ] Delete oldest [ ] Keep all, block new |
| Upgrade | All dashboards restored/accessible |

### Historical Data
| Scenario | Behavior |
|----------|----------|
| Downgrade (data retention reduced) | [ ] Delete old data [ ] Keep but hide [ ] Archive |
| Upgrade | All historical data accessible |

### Exports
| Scenario | Behavior |
|----------|----------|
| In-progress export during downgrade | Complete the export |
| Scheduled exports on downgrade | [ ] Cancel [ ] Convert to manual |

### API Access
| Scenario | Behavior |
|----------|----------|
| Active API keys on downgrade | [ ] Revoke immediately [ ] Disable at period end |
| API calls in flight | Complete the request |

## Implementation Configuration

```json
{
  "entitlement_change_timing": {
    "upgrade": "immediate",
    "downgrade": "end_of_period",
    "cancellation": "immediate",
    "payment_failure_grace": "maintain_until_expiry"
  },
  "soft_blocked_features": [
    "dashboard_advanced",
    "data_export_csv"
  ],
  "hard_blocked_features": [
    "ai_insights",
    "custom_reports",
    "api_access",
    "agency_features"
  ]
}
```

## Role Mapping by Plan

| Plan | Allowed Roles |
|------|---------------|
| Free | `merchant_viewer`, `merchant_admin` |
| Growth | `merchant_viewer`, `merchant_admin` |
| Pro | `merchant_viewer`, `merchant_admin` |
| Enterprise | `merchant_viewer`, `merchant_admin`, `agency_viewer`, `agency_admin` |

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | | | |
| Engineering Lead | | | |
| Customer Success | | | |
