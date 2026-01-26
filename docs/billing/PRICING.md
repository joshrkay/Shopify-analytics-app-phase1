# Pricing, Plan & Billing Strategy

> **HUMAN DECISION REQUIRED**: This document must be filled out by product/business stakeholders before billing integration is complete.

## Plan Hierarchy

| Plan ID | Display Name | Monthly Price | Annual Price | Description |
|---------|--------------|---------------|--------------|-------------|
| `plan_free` | Free | $0 | $0 | Basic analytics for small stores |
| `plan_growth` | Growth | $__ /mo | $__ /yr | For growing businesses |
| `plan_pro` | Pro | $__ /mo | $__ /yr | Advanced features for established stores |
| `plan_enterprise` | Enterprise | Custom | Custom | Custom solutions with dedicated support |

## Billing Intervals

- [ ] Monthly billing available
- [ ] Annual billing available
- [ ] Annual discount: __% off

## Trial Configuration

| Decision | Value |
|----------|-------|
| Trial length (days) | __ |
| Trial available on which plans? | [ ] Growth [ ] Pro |
| Trial behavior on expiration | [ ] Downgrade to Free [ ] Block access |
| Can trial be extended? | [ ] Yes [ ] No |
| Trial for existing users switching plans? | [ ] Yes [ ] No |

## Upgrade Behavior

When a merchant upgrades to a higher plan:

- [ ] **Immediate (Prorated)**: Start new plan immediately, prorate remaining days
- [ ] **Immediate (Non-prorated)**: Start new plan immediately, charge full amount
- [ ] **Next Billing Cycle**: Start new plan at next billing cycle

## Downgrade Behavior

When a merchant downgrades to a lower plan:

- [ ] **End of Billing Period**: Continue current plan until period ends
- [ ] **Immediate**: Switch immediately (no refund by default)

## Refund Policy

| Scenario | Refund Policy |
|----------|---------------|
| Cancellation within __ days | [ ] Full [ ] Prorated [ ] None |
| Cancellation after __ days | [ ] Prorated [ ] None |
| Downgrade | [ ] Prorated credit [ ] None |
| App issues/bugs | [ ] Case-by-case [ ] Automatic |

## Usage Limits by Plan

| Feature | Free | Growth | Pro | Enterprise |
|---------|------|--------|-----|------------|
| Dashboards | __ | __ | __ | Unlimited |
| Data retention (days) | __ | __ | __ | Unlimited |
| API calls/month | __ | __ | __ | Unlimited |
| AI Insights/month | __ | __ | __ | Unlimited |
| Users | __ | __ | __ | Unlimited |

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | | | |
| Finance | | | |
| Engineering Lead | | | |
