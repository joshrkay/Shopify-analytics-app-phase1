# Render Database Setup Guide

## Overview

This guide helps you configure dbt to use your Render PostgreSQL database.

## Prerequisites

1. **Render Database**: You should have a Render database named `shopify-analytics-db`
2. **Connection String**: Get the connection string from Render dashboard

## Step 1: Get Database Connection String

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Navigate to your database: **shopify-analytics-db**
3. Find the connection string:
   - **Internal Database URL**: Use this if running from Render services
   - **External Database URL**: Use this if running from your local machine
4. Copy the connection string (format: `postgresql://user:password@host:port/database`)

## Step 2: Configure Connection

### Option A: Automatic Setup (Recommended)

Run the setup script with your DATABASE_URL:

```bash
cd analytics

# Set DATABASE_URL (from Render dashboard)
export DATABASE_URL="postgresql://user:password@host:port/database"

# Run setup script
./setup_render_db.sh
```

The script will:
- Parse DATABASE_URL into individual components
- Update `.env` file with parsed values
- Test the connection (if psql is available)

### Option B: Manual Setup

1. **Set DATABASE_URL**:
   ```bash
   export DATABASE_URL="postgresql://user:password@host:port/database"
   ```

2. **Parse into components**:
   ```bash
   # Using Python script
   eval $(python3 parse_database_url.py)
   
   # Or manually set:
   export DB_HOST="your-host"
   export DB_USER="your-user"
   export DB_PASSWORD="your-password"
   export DB_PORT="5432"
   export DB_NAME="shopify_analytics"
   ```

3. **Update .env file**:
   ```bash
   cd analytics
   cat >> .env << EOF
   DATABASE_URL=your-connection-string
   DB_HOST=your-host
   DB_USER=your-user
   DB_PASSWORD=your-password
   DB_PORT=5432
   DB_NAME=shopify_analytics
   EOF
   ```

### Option C: Use .env File Directly

1. Edit `analytics/.env`:
   ```bash
   cd analytics
   nano .env  # or your preferred editor
   ```

2. Add your connection details:
   ```bash
   # Option 1: Use DATABASE_URL
   DATABASE_URL=postgresql://user:password@host:port/database
   
   # Option 2: Use individual components
   DB_HOST=your-host
   DB_USER=your-user
   DB_PASSWORD=your-password
   DB_PORT=5432
   DB_NAME=shopify_analytics
   ```

3. Load environment variables:
   ```bash
   source load_env.sh
   ```

## Step 3: Verify Connection

Test the connection:

```bash
cd analytics

# Load environment variables
source load_env.sh

# Test with dbt (if installed)
dbt debug

# Or test with psql
psql $DATABASE_URL -c "SELECT 1"
```

## Step 4: Set Up Test Data (Optional)

If you want to test with sample data:

```bash
cd analytics

# Using Python script
python3 tests/validate_with_test_data.py

# Or using SQL directly
psql $DATABASE_URL -f tests/test_data_setup.sql
```

## Step 5: Run dbt Models

Once connected, run your staging models:

```bash
cd analytics

# Load environment variables
source load_env.sh

# Run staging models
dbt run --select staging

# Run tests
dbt test --select staging
```

## Troubleshooting

### Connection Refused

**Problem**: Cannot connect to database

**Solutions**:
- If using **External Database URL**: Make sure your IP is whitelisted in Render dashboard
- If using **Internal Database URL**: Only works from Render services, not local machine
- Check firewall settings
- Verify host and port are correct

### Authentication Failed

**Problem**: Wrong username/password

**Solutions**:
- Verify credentials from Render dashboard
- Check if password contains special characters (may need URL encoding)
- Ensure you're using the correct database user

### Database Does Not Exist

**Problem**: Database name not found

**Solutions**:
- Verify database name in Render dashboard (should be `shopify_analytics`)
- Check if you have access to the database
- Ensure database is active in Render

### Special Characters in Password

**Problem**: Password contains special characters that break URL parsing

**Solutions**:
- Use URL encoding for special characters (e.g., `@` becomes `%40`)
- Or use individual DB_* variables instead of DATABASE_URL
- The `parse_database_url.py` script handles URL decoding automatically

## Security Notes

⚠️ **Never commit credentials to git**

- `.env` file is gitignored
- `profiles.yml` is gitignored
- Always use environment variables or `.env` file (never hardcode)

## Render Database Details

From `render.yaml`:
- **Database Name**: `shopify_analytics`
- **Database User**: `shopify_analytics_user`
- **PostgreSQL Version**: 15
- **Region**: Oregon

## Quick Reference

```bash
# Get connection string from Render dashboard
export DATABASE_URL="postgresql://user:pass@host:port/database"

# Setup
cd analytics
./setup_render_db.sh

# Load variables
source load_env.sh

# Test
dbt debug

# Run
dbt run --select staging
dbt test --select staging
```
