#!/bin/bash
# Run Tests Against Render Database
#
# This script:
# 1. Loads environment variables
# 2. Sets up test data (if needed)
# 3. Runs dbt tests against staging models
#
# Usage:
#   ./run_tests_render.sh

set -e

echo "=========================================="
echo "Running Tests Against Render Database"
echo "=========================================="
echo ""

# Load environment variables
cd "$(dirname "$0")"
if [ -f "load_env.sh" ]; then
    source load_env.sh
    echo "✅ Environment variables loaded"
else
    echo "⚠️  load_env.sh not found, using current environment"
fi

echo ""
echo "Database Configuration:"
echo "  Host: ${DB_HOST:-not set}"
echo "  Database: ${DB_NAME:-not set}"
echo "  User: ${DB_USER:-not set}"
echo ""

# Check if dbt is installed
if ! command -v dbt &> /dev/null && ! python3 -m dbt --version &> /dev/null; then
    echo "❌ dbt is not installed"
    echo ""
    echo "Installing dbt..."
    pip install -r requirements.txt
    echo ""
fi

# Verify dbt installation
if command -v dbt &> /dev/null; then
    DBT_CMD="dbt"
elif python3 -m dbt --version &> /dev/null 2>&1; then
    DBT_CMD="python3 -m dbt"
else
    echo "❌ Failed to install or find dbt"
    exit 1
fi

echo "✅ Using dbt: $DBT_CMD"
echo ""

# Test connection
echo "=========================================="
echo "Step 1: Testing Database Connection"
echo "=========================================="
echo ""

$DBT_CMD debug --profiles-dir . --project-dir . 2>&1 | head -20

if [ $? -ne 0 ]; then
    echo ""
    echo "⚠️  Connection test had issues, but continuing..."
    echo ""
fi

# Set test schema variable for dbt
export DBT_TEST_SCHEMA="test_airbyte"

echo ""
echo "=========================================="
echo "Step 2: Setting Up Test Data"
echo "=========================================="
echo ""

# Check if we can use psql
if command -v psql &> /dev/null; then
    echo "Using psql to set up test data..."
    if [ -n "$DATABASE_URL" ]; then
        psql "$DATABASE_URL" -f tests/test_data_setup.sql
    else
        PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "$DB_USER" -d "$DB_NAME" -f tests/test_data_setup.sql
    fi
    echo "✅ Test data setup complete"
elif python3 -c "import psycopg2" 2>/dev/null; then
    echo "Using Python script to set up test data..."
    python3 tests/validate_with_test_data.py
    echo "✅ Test data setup complete"
else
    echo "⚠️  Cannot set up test data automatically"
    echo "   Install psql or psycopg2 to set up test data"
    echo "   Or run tests/test_data_setup.sql manually"
    echo ""
    read -p "Continue without test data? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "=========================================="
echo "Step 3: Running dbt Models"
echo "=========================================="
echo ""

# Set test schema for staging models
export DBT_TEST_SCHEMA="test_airbyte"

echo "Running staging models..."
$DBT_CMD run --select staging --profiles-dir . --project-dir . --vars '{"test_schema": "test_airbyte"}'

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ dbt run failed"
    exit 1
fi

echo ""
echo "✅ Staging models created successfully"
echo ""

echo "=========================================="
echo "Step 4: Running dbt Tests"
echo "=========================================="
echo ""

$DBT_CMD test --select staging --profiles-dir . --project-dir . --vars '{"test_schema": "test_airbyte"}'

TEST_EXIT_CODE=$?

echo ""
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo "✅ All tests passed!"
else
    echo "⚠️  Some tests failed (exit code: $TEST_EXIT_CODE)"
    echo "   Review the output above for details"
fi

echo ""
echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo ""
echo "Database: ${DB_NAME:-unknown}"
echo "Schema: ${DBT_TEST_SCHEMA:-analytics}"
echo "Tests: $([ $TEST_EXIT_CODE -eq 0 ] && echo 'PASSED' || echo 'FAILED')"
echo ""

exit $TEST_EXIT_CODE
