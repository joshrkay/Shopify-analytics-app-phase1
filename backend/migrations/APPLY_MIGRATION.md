# How to Apply the Billing Migration

## Option 1: Local Development (Install PostgreSQL Client)

If you need to run migrations locally:

```bash
# Install PostgreSQL client (macOS)
brew install postgresql@15

# Add to PATH (add to ~/.zshrc or ~/.bash_profile)
export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"

# Set your local database URL
export DATABASE_URL="postgresql://user:password@localhost:5432/shopify_analytics"

# Run migration
psql "$DATABASE_URL" -f backend/migrations/0001_billing_entitlements.sql
```

## Option 2: Using Render Shell (Recommended for Production)

If your database is on Render:

1. **Get Database Connection String from Render:**
   - Go to Render Dashboard → Your Database Service
   - Copy the "Internal Database URL" or "External Connection String"

2. **Run Migration via Render Shell:**
   ```bash
   # Connect to Render shell (if available)
   # Or use Render's database console
   ```

3. **Or Use Render's Database Console:**
   - Go to Render Dashboard → Your Database → "Connect"
   - Use the "psql" option
   - Copy and paste the migration SQL

## Option 3: Python Script (Alternative)

Create a simple Python script to run migrations:

```python
# backend/scripts/run_migration.py
import os
import psycopg2
from psycopg2 import sql

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

# Read migration file
with open("backend/migrations/0001_billing_entitlements.sql", "r") as f:
    migration_sql = f.read()

# Connect and execute
conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cursor = conn.cursor()

try:
    cursor.execute(migration_sql)
    print("Migration applied successfully!")
except Exception as e:
    print(f"Migration failed: {e}")
    raise
finally:
    cursor.close()
    conn.close()
```

Run with:
```bash
python backend/scripts/run_migration.py
```

## Option 4: Docker (If Using Docker Locally)

If you have a local PostgreSQL in Docker:

```bash
# Copy migration file into container
docker cp backend/migrations/0001_billing_entitlements.sql <container_name>:/tmp/

# Execute in container
docker exec -i <container_name> psql -U postgres -d shopify_analytics -f /tmp/0001_billing_entitlements.sql
```

## Verification

After applying the migration, verify:

```sql
-- Check tables exist
\dt

-- Should see:
-- plans
-- plan_features
-- tenant_subscriptions
-- usage_meters
-- usage_events

-- Check indexes
SELECT tablename, indexname 
FROM pg_indexes 
WHERE schemaname = 'public' 
  AND tablename IN ('plans', 'plan_features', 'tenant_subscriptions', 'usage_meters', 'usage_events');
```

## Next Steps

After migration succeeds, run the seed script:

```bash
psql "$DATABASE_URL" -f backend/seeds/seed_plans.sql
```

Or use the Python script approach above.
