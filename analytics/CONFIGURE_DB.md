# Database Connection Configuration Guide

## Current Status

✅ **profiles.yml created** from template  
⚠️ **Database connection not configured** - needs credentials

## Configuration Options

### Option 1: Local PostgreSQL (Recommended for Testing)

If you have PostgreSQL installed locally:

```bash
# Set environment variables
export DB_HOST="localhost"
export DB_USER="postgres"
export DB_PASSWORD="your-postgres-password"
export DB_PORT="5432"
export DB_NAME="shopify_analytics"

# Or use DATABASE_URL
export DATABASE_URL="postgresql://postgres:your-password@localhost:5432/shopify_analytics"
```

**Create database if it doesn't exist:**
```bash
psql -U postgres -c "CREATE DATABASE shopify_analytics;"
```

### Option 2: Docker PostgreSQL (Easiest)

If you have Docker installed:

```bash
# Start PostgreSQL container
docker run -d \
  --name test-pg \
  -e POSTGRES_PASSWORD=test \
  -e POSTGRES_DB=shopify_analytics \
  -p 5432:5432 \
  postgres:15

# Wait for it to be ready (about 5 seconds)
sleep 5

# Set environment variables
export DB_HOST="localhost"
export DB_USER="postgres"
export DB_PASSWORD="test"
export DB_PORT="5432"
export DB_NAME="shopify_analytics"
```

### Option 3: Use Render Database (Production/Staging)

If you have a Render database:

1. Get connection string from Render dashboard
2. Parse it into components or use directly:

```bash
# From Render dashboard, copy DATABASE_URL
export DATABASE_URL="postgresql://user:pass@host:port/database"

# Parse into components (for dbt)
export DB_HOST=$(echo $DATABASE_URL | sed -n 's/.*@\([^:]*\):.*/\1/p')
export DB_USER=$(echo $DATABASE_URL | sed -n 's/.*:\/\/\([^:]*\):.*/\1/p')
export DB_PASSWORD=$(echo $DATABASE_URL | sed -n 's/.*:\/\/[^:]*:\([^@]*\)@.*/\1/p')
export DB_PORT=$(echo $DATABASE_URL | sed -n 's/.*:\([0-9]*\)\/.*/\1/p')
export DB_NAME=$(echo $DATABASE_URL | sed -n 's/.*\/\([^?]*\).*/\1/p')
```

### Option 4: Edit profiles.yml Directly

```bash
cd analytics
cp profiles.yml.example profiles.yml
# Edit profiles.yml with your credentials
```

## Verify Connection

Once configured, test the connection:

```bash
cd analytics

# If dbt is installed
dbt debug

# Or test with psql
psql $DATABASE_URL -c "SELECT 1"
```

## Quick Setup Script

Run the setup script:

```bash
./analytics/setup_test_db.sh
```

This will:
- Check for existing configuration
- Create profiles.yml if needed
- Test database connection
- Provide setup instructions

## Next Steps After Configuration

1. **Set up test data:**
   ```bash
   python3 analytics/tests/validate_with_test_data.py
   # OR
   psql $DATABASE_URL -f analytics/tests/test_data_setup.sql
   ```

2. **Run staging models:**
   ```bash
   cd analytics
   dbt run --select staging
   ```

3. **Run tests:**
   ```bash
   dbt test --select staging
   ```

## Troubleshooting

**"Connection refused"**
- PostgreSQL not running
- Wrong host/port
- Firewall blocking connection

**"Authentication failed"**
- Wrong username/password
- User doesn't have access to database

**"Database does not exist"**
- Create database: `psql -U postgres -c "CREATE DATABASE shopify_analytics;"`

**"psql: command not found"**
- Install PostgreSQL client tools
- Or use Python script instead
