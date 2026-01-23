# Shopify Analytics - dbt Project

This dbt project transforms raw Airbyte data into canonical fact tables and metrics for the Shopify Analytics App.

## Overview

The dbt project follows a layered architecture:

```
Raw Data (Airbyte) → Staging Models → Fact Tables → Metrics → Attribution
```

- **Raw**: `_airbyte_raw_*` tables from Airbyte (Shopify, Meta Ads, Google Ads)
- **Staging**: Normalized, typed models with consistent naming
- **Facts**: Canonical business events (orders, ad spend, campaign performance)
- **Metrics**: Centralized metric definitions (revenue, AOV, ROAS, CAC)
- **Attribution**: Last-click attribution model

## Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Access to database with `DATABASE_URL` environment variable
- dbt-core and dbt-postgres installed (see requirements.txt)

## Setup

### 1. Install Dependencies

```bash
cd analytics
pip install -r requirements.txt
```

### 2. Configure Database Connection

#### For Render Database (Recommended)

If you're using the Render database:

1. **Get connection string from Render dashboard:**
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Navigate to `shopify-analytics-db`
   - Copy the **External Database URL** (for local) or **Internal Database URL** (for Render services)

2. **Run automatic setup:**
   ```bash
   cd analytics
   export DATABASE_URL="postgresql://user:password@host:port/database"
   ./setup_render_db.sh
   ```

   This will parse `DATABASE_URL` and configure `.env` automatically.

3. **Or use manual setup:**
   ```bash
   # Set DATABASE_URL
   export DATABASE_URL="postgresql://user:password@host:port/database"
   
   # Parse into components
   eval $(python3 parse_database_url.py)
   
   # Load variables
   source load_env.sh
   ```

   See [RENDER_DB_SETUP.md](RENDER_DB_SETUP.md) for detailed instructions.

#### For Local PostgreSQL

**Option A: Using Individual Environment Variables**

Set connection parameters as environment variables:

```bash
export DB_HOST="localhost"
export DB_USER="postgres"
export DB_PASSWORD="your-password"
export DB_PORT="5432"
export DB_NAME="shopify_analytics"
```

**Option B: Direct profiles.yml Configuration**

1. Copy the example profile:
   ```bash
   cp profiles.yml.example profiles.yml
   ```

2. Edit `profiles.yml` with your database credentials (NEVER commit this file)

3. Set environment variables or edit connection details directly

### 3. Verify Connection

```bash
dbt debug
```

Expected output:
```
Connection test: [OK connection ok]
```

### 4. Run Models

```bash
# Compile SQL (validate syntax)
dbt compile

# Run all models
dbt run

# Run specific models
dbt run --select staging
dbt run --select facts
dbt run --select metrics

# Run tests
dbt test
```

## Project Structure

```
analytics/
├── dbt_project.yml          # Project configuration
├── profiles.yml.example     # Profile template (copy to profiles.yml)
├── requirements.txt         # Python dependencies
├── README.md                # This file
├── models/                  # dbt models (SQL files)
│   ├── staging/            # Staging models (normalized raw data)
│   ├── facts/             # Fact tables (canonical events)
│   ├── metrics/            # Metric definitions
│   └── attribution/       # Attribution models
├── macros/                  # dbt macros (reusable SQL)
├── tests/                   # Custom tests
└── target/                  # Build artifacts (gitignored)
```

## Environment Targets

The project supports multiple environments:

- **local**: Development database (default)
- **staging**: Staging environment database
- **production**: Production database

Switch targets:

```bash
dbt run --target staging
dbt run --target production
```

## Security

**CRITICAL**: Never commit credentials

- `profiles.yml` is gitignored (contains database credentials)
- Only `profiles.yml.example` is committed (template only)
- All credentials must come from environment variables
- Tenant isolation is enforced at the model level (all models filter by `tenant_id`)

## Running Tests

```bash
# Run all tests
dbt test

# Run tests for specific models
dbt test --select staging
dbt test --select facts

# Run specific test
dbt test --select test_name:not_null
```

## Troubleshooting

### Connection Errors

If `dbt debug` fails:

1. Verify `DATABASE_URL` is set correctly
2. Check database is accessible from your network
3. Verify credentials are correct
4. Ensure PostgreSQL is running

### Model Errors

If `dbt run` fails:

1. Check SQL syntax: `dbt compile`
2. Review error messages (dbt provides clear error context)
3. Verify source tables exist in database
4. Check tenant_id filtering is correct

## Development Workflow

1. **Create/Edit Models**: Add SQL files in `models/` directory
2. **Add Tests**: Define tests in `schema.yml` files
3. **Test Locally**: `dbt run --select model_name` and `dbt test --select model_name`
4. **Commit**: Only commit SQL files and schema.yml (never profiles.yml)

## CI/CD

The dbt project is integrated into CI/CD:

- `dbt compile` - Validates SQL syntax
- `dbt run` - Builds all models
- `dbt test` - Runs all data quality tests

All steps must pass before PR merge.

## References

- [dbt Documentation](https://docs.getdbt.com/)
- [dbt Postgres Adapter](https://docs.getdbt.com/reference/warehouse-profiles/postgres-profile)
- [Project .cursorrules](../.cursorrules) - Engineering standards
