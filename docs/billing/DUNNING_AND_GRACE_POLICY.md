# Payment Failure, Grace Period & Dunning Policy

> **HUMAN DECISION REQUIRED**: Payment failure handling directly impacts revenue and customer experience.

## Payment Failure Retry Policy

### Shopify's Default Behavior
Shopify Billing API handles payment retries automatically. The app receives webhooks for payment status changes.

### Retry Configuration (Shopify-managed)

| Attempt | Timing | Notes |
|---------|--------|-------|
| 1 | Initial charge | First billing attempt |
| 2-N | Shopify-managed | Shopify retries automatically |

### App-side Notification Policy

| Event | Customer Notification | Internal Alert |
|-------|----------------------|----------------|
| Payment failed (1st) | [ ] Email [ ] In-app | [ ] Slack [ ] Email |
| Payment failed (retry) | [ ] Email [ ] In-app | [ ] Slack [ ] Email |
| Grace period starting | [ ] Email [ ] In-app | [ ] Slack [ ] Email |
| Grace period warning (3 days left) | [ ] Email [ ] In-app | [ ] Slack [ ] Email |
| Grace period expired | [ ] Email [ ] In-app | [ ] Slack [ ] Email |

## Grace Period Configuration

### Duration
| Setting | Value |
|---------|-------|
| Grace period length | __ days (recommended: 7-14 days) |
| Warning notification | __ days before expiration |

### Access During Grace Period

| Option | Description | Selected |
|--------|-------------|----------|
| **Full Access** | All features remain available | [ ] |
| **Read-Only** | Can view data but not modify | [ ] |
| **Limited** | Core features only, premium blocked | [ ] |
| **Banner Only** | Full access with payment warning banner | [ ] |

### Grace Period Behavior

| Question | Decision |
|----------|----------|
| Can merchant initiate new actions during grace? | [ ] Yes [ ] No |
| Are scheduled reports/exports paused? | [ ] Yes [ ] No |
| Are API calls still allowed? | [ ] Yes [ ] Limited [ ] No |
| Is data sync paused? | [ ] Yes [ ] No |

## Suspension & Cancellation

### Suspension Triggers
| Condition | Action |
|-----------|--------|
| Grace period expired | Suspend access |
| Merchant requests cancellation | End of billing period |
| Fraud detected | Immediate suspension |
| Shopify app uninstall | Immediate cancellation |

### Cancellation Timeline
```
Payment Fails → Grace Period (__ days) → Suspension → Auto-Cancel (__ days later)
```

| Stage | Duration | Access Level |
|-------|----------|--------------|
| Active (payment current) | Ongoing | Full |
| Grace Period | __ days | [Full/Limited/Read-only] |
| Suspended | __ days | None |
| Cancelled | Permanent | None (data retained per policy) |

## Cost Allocation

### Who Bears Failed Charge Costs?

| Scenario | Cost Bearer |
|----------|-------------|
| Shopify payment processing fees | Shopify (included in 0% rev share) |
| Failed payment notification costs | App |
| Customer support for payment issues | App |
| Revenue loss during grace period | App |

## Dunning Email Sequence

### Email Templates Required

| Email | Timing | Subject Line |
|-------|--------|--------------|
| Payment Failed | Day 0 | "Action required: Update your payment method" |
| Grace Period Warning | Day __ | "Your access will be suspended in __ days" |
| Final Warning | Day __ | "Last chance: Update payment to avoid suspension" |
| Suspension Notice | Day __ | "Your account has been suspended" |
| Win-back | Day __ | "We miss you! Reactivate your account" |

## Configurable Values (in config)

```json
{
  "grace_period_days": 7,
  "warning_notification_days_before": 3,
  "access_during_grace": "full",
  "auto_cancel_after_suspension_days": 30,
  "dunning_emails_enabled": true
}
```

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | | | |
| Customer Success | | | |
| Finance | | | |
