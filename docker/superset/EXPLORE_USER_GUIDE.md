# Flexible Reporting Guide (Explore Mode)

This guide explains what you can and cannot do in the self-service Explore mode.

---

## What You Can Do

### Filter Data

You can filter your data by:

| Filter Type      | Options                              | Limit        |
|------------------|--------------------------------------|--------------|
| Date range       | Any range within last 90 days        | Max 90 days  |
| Channel          | Facebook, Google, TikTok, etc.       | -            |
| Campaign         | Any campaign in your account         | -            |
| Product category | Any category in your catalog         | -            |

**Tip:** Narrower date ranges (7-30 days) produce faster results.

---

### Explore Metrics

Available metrics vary by dataset:

**Orders Dataset:**
- Total Revenue (`SUM(revenue)`)
- Order Count (`COUNT(order_id)`)
- Average Order Value (`AVG(revenue)`)
- Unique Customers (`COUNT(DISTINCT customer_id)`)

**Marketing Spend Dataset:**
- Total Spend (`SUM(spend)`)
- Average Spend (`AVG(spend)`)
- Total Impressions (`SUM(impressions)`)
- Total Clicks (`SUM(clicks)`)

**Campaign Performance Dataset:**
- Total Revenue (`SUM(revenue)`)
- Total Spend (`SUM(spend)`)
- ROAS (Return on Ad Spend)
- Total Conversions (`SUM(conversions)`)
- Average CPA (`AVG(cpa)`)

---

### Visualizations

Choose from these chart types:

| Chart Type  | Best For                          | Available In          |
|-------------|-----------------------------------|-----------------------|
| Line        | Trends over time                  | All datasets          |
| Bar         | Comparisons between categories    | All datasets          |
| Pie         | Composition / share breakdown     | Orders only           |
| Table       | Detailed data view                | All datasets          |
| Number      | Single KPI display                | All datasets          |

---

### Grouping Options

Group your data by up to **2 dimensions**:

- **Date granularity:** Day, Week, or Month
- **Channel:** Facebook, Google, TikTok, etc.
- **Campaign:** Individual campaigns

**Examples:**
- Revenue by Channel (1 dimension)
- Revenue by Channel by Week (2 dimensions)

---

## What You Cannot Do

### Custom SQL

Custom SQL queries are not available in Explore mode.

- No raw table access
- No custom query writing
- No direct database queries

**Why?** Custom SQL could expose sensitive data or impact system performance.

---

### Create New Metrics

All metrics are predefined by administrators.

- Cannot create custom metrics
- Cannot edit metric definitions
- Cannot combine metrics in new ways

**Why?** Predefined metrics ensure consistent, accurate reporting across all users.

---

### Export Row-Level Data

Raw data downloads are not available.

- No CSV exports of individual records
- No raw data access
- Aggregated summaries only

**Why?** Protects individual customer privacy and prevents data leakage.

---

### Join New Datasets

You cannot combine datasets beyond pre-configured joins.

- Cannot join arbitrary tables
- Cannot create new relationships
- Pre-built datasets only

**Why?** Uncontrolled joins could create performance issues or expose cross-dataset information.

---

## Performance Tips

### Keep Reports Fast

- **Use narrower date ranges:** 7-30 days is ideal for quick results
- **Limit grouping:** Max 2 dimensions keeps queries efficient
- **Avoid over-filtering:** Too many filters can slow queries

### Query Timeout

Queries that take longer than **20 seconds** will timeout.

If this happens:
1. Reduce your date range
2. Remove some group-by dimensions
3. Simplify your filters
4. Try again

### Data Limits

| Limit          | Value   | What It Means                        |
|----------------|---------|--------------------------------------|
| Max rows       | 50,000  | Results capped at 50K rows           |
| Max date range | 90 days | Cannot query beyond 90 days          |
| Max group-by   | 2       | Two grouping dimensions maximum      |
| Query timeout  | 20 sec  | Queries must complete in 20 seconds  |
| Cache TTL      | 30 min  | Data refreshes every 30 minutes      |

---

## Understanding Your Datasets

### Orders (fact_orders)

Explore your order data with revenue and customer metrics.

**Available Dimensions:**
- `order_date` - When the order was placed
- `channel` - Marketing channel (Facebook, Google, etc.)
- `campaign_id` - Specific campaign
- `product_category` - Product category

**Not Available:** Customer email, phone, address, payment details (privacy protected)

---

### Marketing Spend (fact_marketing_spend)

Analyze your advertising spend across channels.

**Available Dimensions:**
- `spend_date` - Date of ad spend
- `channel` - Ad platform
- `campaign_id` - Campaign identifier

**Not Available:** API credentials, account IDs (security protected)

---

### Campaign Performance (fact_campaign_performance)

Compare campaign effectiveness with ROAS and conversion metrics.

**Available Dimensions:**
- `campaign_date` - Performance date
- `campaign_id` - Campaign identifier
- `channel` - Marketing channel

**Not Available:** Internal campaign IDs (system protected)

---

## Tooltips Reference

Use these hints when exploring:

| Field         | Tooltip                                                    |
|---------------|------------------------------------------------------------|
| Date Range    | Select a date range up to 90 days                          |
| Group By      | Group by up to 2 dimensions (e.g., date + channel)         |
| Metrics       | Select from predefined metrics - custom metrics unavailable|
| Filters       | Add up to 10 filters to refine your data                   |
| Visualization | Choose from available chart types for this dataset         |
| Timeout       | Queries are limited to 20 seconds                          |
| Row Limit     | Results are capped at 50,000 rows                          |
| Export        | Raw data export is not available - use aggregated views    |
| Custom SQL    | Custom SQL queries are not available in Explore mode       |

---

## Need Help?

If you need assistance with Explore mode or have questions about available data:

- Contact your administrator for access to additional metrics
- Review this guide for allowed operations
- Check the tooltips in the Explore interface

---

## Technical Reference

For developers and administrators, see:

- `explore_guardrails.py` - Python validation and enforcement
- `explore_datasets.yml` - Dataset configuration reference
- `rls_rules.py` - Row-level security rules
- `superset_config.py` - Superset configuration with guardrails
