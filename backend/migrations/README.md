# Database Migrations

This directory contains SQL migration files for the database schema.

## Usage

### Apply a Migration

```bash
# Using psql
psql $DATABASE_URL -f backend/migrations/0001_billing_entitlements.sql

# Or with explicit connection
psql -h localhost -U postgres -d shopify_analytics -f backend/migrations/0001_billing_entitlements.sql
```

### Apply All Migrations

```bash
# Apply migrations in order
for migration in backend/migrations/*.sql; do
    echo "Applying $migration..."
    psql $DATABASE_URL -f "$migration"
done
```

### Rollback

Migrations are not automatically reversible. To rollback:
1. Create a new migration file with reverse operations
2. Or manually drop tables/indexes if needed

**Note**: Always test migrations on a staging database first.

## Migration Files

- `0001_billing_entitlements.sql`: Creates billing and entitlements schema (plans, subscriptions, usage tracking)

## Seed Data

After applying migrations, run seed scripts from `backend/seeds/`:

```bash
psql $DATABASE_URL -f backend/seeds/seed_plans.sql
```

## Best Practices

1. **Idempotency**: Migrations use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` for safety
2. **Tenant Isolation**: All tenant-scoped tables include `tenant_id` with proper indexes
3. **Naming**: Use descriptive names with version prefix (e.g., `0001_`, `0002_`)
4. **Testing**: Test migrations on a copy of production data before applying

## Verification

After applying migrations, verify schema:

```sql
-- List all tables
\dt

-- Check indexes
SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public';

-- Verify tenant_id columns
SELECT table_name, column_name, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND column_name = 'tenant_id'
ORDER BY table_name;
```
