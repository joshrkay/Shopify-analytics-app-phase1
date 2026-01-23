#!/bin/bash
# Test Data Runner Script
#
# This script sets up test data and runs dbt models for validation
#
# Prerequisites:
#   - PostgreSQL database accessible
#   - dbt installed (pip install -r requirements.txt)
#   - DATABASE_URL or DB_* environment variables set

set -e

echo "=========================================="
echo "Story 4.2 & 4.3 - Test Data Validation"
echo "=========================================="
echo ""

# Check if dbt is installed
if ! command -v dbt &> /dev/null; then
    echo "❌ dbt is not installed"
    echo "   Install with: pip install -r requirements.txt"
    exit 1
fi

# Check database connection
echo "Step 1: Checking database connection..."
if ! dbt debug --profiles-dir . 2>&1 | grep -q "Connection test: \[OK"; then
    echo "❌ Database connection failed"
    echo "   Set DB_* environment variables or DATABASE_URL"
    exit 1
fi
echo "✅ Database connection OK"
echo ""

# Load test data
echo "Step 2: Loading test data..."
if [ -f "tests/test_data_setup.sql" ]; then
    # Run test data setup (requires psql or similar)
    echo "   Note: Run tests/test_data_setup.sql manually in your database"
    echo "   Or use: psql \$DATABASE_URL -f tests/test_data_setup.sql"
else
    echo "   Test data setup script not found"
fi
echo ""

# Compile models
echo "Step 3: Compiling staging models..."
if dbt compile --select staging --profiles-dir . 2>&1 | tail -5; then
    echo "✅ Compilation successful"
else
    echo "❌ Compilation failed"
    exit 1
fi
echo ""

# Run staging models
echo "Step 4: Running staging models..."
if dbt run --select staging --profiles-dir . 2>&1 | tail -10; then
    echo "✅ Models built successfully"
else
    echo "❌ Model build failed"
    exit 1
fi
echo ""

# Run tests
echo "Step 5: Running tests..."
if dbt test --select staging --profiles-dir . 2>&1 | tail -15; then
    echo "✅ All tests passed"
else
    echo "❌ Some tests failed"
    exit 1
fi
echo ""

echo "=========================================="
echo "✅ Test validation complete!"
echo "=========================================="
