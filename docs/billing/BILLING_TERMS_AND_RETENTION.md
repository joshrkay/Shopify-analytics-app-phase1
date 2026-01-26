# Legal, Compliance & Data Retention

> **HUMAN/LEGAL SIGN-OFF REQUIRED**: This document requires legal review before implementation.

## Data Access After Cancellation

### Merchant Data Access

| Data Type | Access After Cancellation | Retention Period |
|-----------|--------------------------|------------------|
| Dashboard views | [ ] Yes [ ] Read-only [ ] No | __ days |
| Historical analytics | [ ] Yes [ ] Read-only [ ] No | __ days |
| Exported reports | [ ] Yes [ ] No | __ days |
| API access | [ ] Yes [ ] No | Immediate revocation |

### Data Export Rights

| Question | Decision |
|----------|----------|
| Can merchants export data after cancellation? | [ ] Yes (__ days) [ ] No |
| Is data export included in cancellation flow? | [ ] Yes [ ] No |
| Format of data export | [ ] CSV [ ] JSON [ ] Both |

## Data Retention Duration

### Billing Records

| Record Type | Retention Period | Legal Basis |
|-------------|-----------------|-------------|
| Subscription history | __ years | Tax/audit requirements |
| Payment transactions | __ years | Financial regulations |
| Invoices | __ years | Tax compliance |
| Billing audit logs | __ years | Compliance/audit |

### Analytics Data

| Data Type | Active Account | After Cancellation |
|-----------|---------------|-------------------|
| Raw Shopify data | Retained | Deleted after __ days |
| Aggregated metrics | Retained | Anonymized/deleted after __ days |
| Custom reports | Retained | Deleted after __ days |
| AI insights history | Retained | Deleted after __ days |

### User Data

| Data Type | Retention Period |
|-----------|-----------------|
| User profiles | Until account deletion + __ days |
| Activity logs | __ months |
| Support tickets | __ years |

## GDPR/CCPA Compliance

### Right to Deletion

| Data Category | Can Be Deleted | Retention Exception |
|---------------|----------------|---------------------|
| Personal information | [ ] Yes | Legal hold, tax records |
| Billing records | [ ] Partial | 7-year tax requirement |
| Subscription history | [ ] Anonymize | Audit requirements |
| Usage analytics | [ ] Yes | N/A |

### Legal Retention Requirements

| Regulation | Requirement | Our Compliance |
|------------|-------------|----------------|
| GDPR Art. 17 | Right to erasure | Honored within __ days |
| CCPA | Right to delete | Honored within __ days |
| Tax law | 7-year retention | Billing records retained |
| SOX (if applicable) | Audit trails | Logs retained __ years |

### Deletion Process

```
1. Merchant requests deletion
2. Verify identity
3. Check for legal holds
4. Delete/anonymize personal data
5. Retain required billing records (anonymized)
6. Confirm deletion to merchant
7. Log deletion event (audit trail)
```

## Billing Audit Log Retention

### Required Log Fields

| Field | Description | Retention |
|-------|-------------|-----------|
| tenant_id | Tenant identifier | Anonymized after deletion |
| event_type | Type of billing event | 7 years |
| amount_cents | Transaction amount | 7 years |
| timestamp | Event timestamp | 7 years |
| shopify_subscription_id | Shopify reference | 7 years |
| previous_state | State before change | 7 years |
| new_state | State after change | 7 years |
| raw_payload | Webhook/API payload | 1 year (then summarized) |

### Audit Log Access

| Role | Access Level |
|------|--------------|
| Finance | Full read access |
| Support | Limited (tenant-specific) |
| Engineering | Debugging only (time-limited) |
| Legal | Full access on request |
| External auditors | Via secure export |

## Compliance Checklist

### Pre-Launch
- [ ] Privacy policy updated with billing data handling
- [ ] Terms of service include billing terms
- [ ] Data processing agreement (DPA) available
- [ ] Cookie policy includes analytics tracking disclosure
- [ ] Shopify App Store listing compliance

### Ongoing
- [ ] Annual compliance review scheduled
- [ ] Data retention automated per policy
- [ ] Deletion requests tracked and honored
- [ ] Audit log integrity verified

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Legal Counsel | | | |
| Data Protection Officer | | | |
| Engineering Lead | | | |
| Finance | | | |
