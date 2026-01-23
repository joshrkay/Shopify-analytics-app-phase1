#!/bin/bash
# Run SQL Logic Tests
#
# This script runs SQL logic validation tests without requiring dbt

set -e

echo "=========================================="
echo "SQL Logic Validation Tests"
echo "=========================================="
echo ""

# Check if DATABASE_URL is set
if [ -z "$DATABASE_URL" ] && [ -z "$DB_HOST" ]; then
    echo "❌ Database connection not configured"
    echo "   Set DATABASE_URL or DB_* environment variables"
    exit 1
fi

# Determine connection method
if [ -n "$DATABASE_URL" ]; then
    DB_CONN="$DATABASE_URL"
else
    DB_CONN="postgresql://${DB_USER:-postgres}:${DB_PASSWORD}@${DB_HOST:-localhost}:${DB_PORT:-5432}/${DB_NAME:-shopify_analytics}"
fi

echo "Running SQL logic tests..."
echo ""

# Run SQL tests
if command -v psql &> /dev/null; then
    psql "$DB_CONN" -f tests/test_sql_logic.sql
    echo ""
    echo "✅ SQL logic tests completed"
elif command -v python3 &> /dev/null; then
    echo "Note: psql not found. Install PostgreSQL client tools to run SQL tests."
    echo "Or use Python script: python3 tests/validate_with_test_data.py"
else
    echo "❌ Neither psql nor python3 found"
    exit 1
fi
