# Tax, Currency & Localization Decisions

> **HUMAN DECISION REQUIRED**: Tax and currency handling requires explicit business decisions before implementation.

## Tax Handling Strategy

### Source of Truth
- [x] **Shopify-calculated taxes**: App relies entirely on Shopify's tax calculations
- [ ] **Custom tax implementation**: App calculates taxes independently

### Tax Display
- [ ] **Tax-inclusive pricing**: Displayed prices include all applicable taxes
- [ ] **Tax-exclusive pricing**: Taxes added at checkout (Shopify handles this)

### Tax Questions Requiring Human Decision

| Question | Decision |
|----------|----------|
| Does the app display tax amounts in the UI? | [ ] Yes, show breakdown [ ] No, trust Shopify UI |
| Do we need to collect VAT registration numbers? | [ ] Yes [ ] No |
| Are there any tax-exempt scenarios to handle? | [ ] Yes [ ] No |

## Supported Currencies

### Currency Strategy
- [ ] **Single currency (USD)**: All pricing in USD, Shopify handles conversion
- [ ] **Multi-currency via Shopify**: Shopify converts based on merchant's currency
- [ ] **Custom multi-currency**: App maintains separate price lists

### Currency Configuration

| Setting | Value |
|---------|-------|
| Base currency | USD |
| Supported currencies | USD, CAD, GBP, EUR, AUD (via Shopify) |
| Currency conversion source | Shopify Billing API |

### Currency Questions Requiring Human Decision

| Question | Decision |
|----------|----------|
| Can merchants switch billing currency? | [ ] Yes [ ] No |
| Display prices in merchant's local currency? | [ ] Yes [ ] No |
| Store currency preference in database? | [ ] Yes [ ] No |

## Locale Display

### Date/Time Localization
- [ ] Use merchant's Shopify timezone
- [ ] Use UTC for all displays
- [ ] Allow user preference

### Currency Formatting
- [ ] Use browser locale for formatting
- [ ] Use merchant's Shopify locale
- [ ] Use store's configured currency locale

### Number Formatting
| Region | Example |
|--------|---------|
| US | $1,234.56 |
| EU | 1.234,56 € |
| UK | £1,234.56 |

## Implementation Notes

```
# Currency handling in code should:
1. Store all amounts in cents (integers) to avoid floating point issues
2. Use Shopify's currency_code from the store settings
3. Let Shopify handle all actual currency conversion
4. Display amounts using the merchant's locale preference
```

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | | | |
| Finance | | | |
| Legal | | | |
