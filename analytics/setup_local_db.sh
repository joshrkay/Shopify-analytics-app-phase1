#!/bin/bash
# Local Database Setup Script
#
# This script sets up a local PostgreSQL database for testing
# Options:
#   1. Use Docker (recommended)
#   2. Use existing local PostgreSQL
#   3. Configure connection to remote database

set -e

echo "=========================================="
echo "Local Database Setup for dbt Testing"
echo "=========================================="
echo ""

# Check if Docker is available
if command -v docker &> /dev/null; then
    echo "✅ Docker is available"
    echo ""
    echo "Option 1: Start PostgreSQL in Docker (Recommended)"
    echo "----------------------------------------"
    
    # Check if container already exists
    if docker ps -a --format '{{.Names}}' | grep -q '^test-pg$'; then
        if docker ps --format '{{.Names}}' | grep -q '^test-pg$'; then
            echo "✅ PostgreSQL container 'test-pg' is already running"
        else
            echo "⚠️  Container 'test-pg' exists but is stopped"
            echo "   Starting container..."
            docker start test-pg
            echo "✅ Container started"
        fi
    else
        echo "Creating new PostgreSQL container..."
        docker run -d \
            --name test-pg \
            -e POSTGRES_PASSWORD=test \
            -e POSTGRES_DB=shopify_analytics \
            -p 5432:5432 \
            postgres:15
        
        echo "⏳ Waiting for PostgreSQL to be ready..."
        sleep 5
        
        # Wait for PostgreSQL to be ready
        for i in {1..30}; do
            if docker exec test-pg pg_isready -U postgres > /dev/null 2>&1; then
                echo "✅ PostgreSQL is ready"
                break
            fi
            sleep 1
        done
    fi
    
    # Set environment variables
    export DB_HOST="localhost"
    export DB_USER="postgres"
    export DB_PASSWORD="test"
    export DB_PORT="5432"
    export DB_NAME="shopify_analytics"
    export DATABASE_URL="postgresql://postgres:test@localhost:5432/shopify_analytics"
    
    echo ""
    echo "✅ Database connection configured:"
    echo "   Host: localhost"
    echo "   Port: 5432"
    echo "   Database: shopify_analytics"
    echo "   User: postgres"
    echo ""
    echo "Environment variables set for this session:"
    echo "   DATABASE_URL=$DATABASE_URL"
    echo ""
    echo "To persist these variables, add to your shell profile:"
    echo "   export DB_HOST=\"localhost\""
    echo "   export DB_USER=\"postgres\""
    echo "   export DB_PASSWORD=\"test\""
    echo "   export DB_PORT=\"5432\""
    echo "   export DB_NAME=\"shopify_analytics\""
    
else
    echo "⚠️  Docker is not available"
    echo ""
    echo "Option 2: Use Existing Local PostgreSQL"
    echo "----------------------------------------"
    echo ""
    echo "If you have PostgreSQL installed locally, set these variables:"
    echo ""
    echo "  export DB_HOST=\"localhost\""
    echo "  export DB_USER=\"postgres\""
    echo "  export DB_PASSWORD=\"your-password\""
    echo "  export DB_PORT=\"5432\""
    echo "  export DB_NAME=\"shopify_analytics\""
    echo ""
    echo "Or set DATABASE_URL:"
    echo "  export DATABASE_URL=\"postgresql://postgres:password@localhost:5432/shopify_analytics\""
    echo ""
fi

echo ""
echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo ""
echo "1. Test the connection:"
echo "   cd analytics"
echo "   dbt debug"
echo ""
echo "2. Set up test data:"
echo "   python3 tests/validate_with_test_data.py"
echo "   OR"
echo "   psql \$DATABASE_URL -f tests/test_data_setup.sql"
echo ""
echo "3. Run staging models:"
echo "   dbt run --select staging"
echo ""
echo "4. Run tests:"
echo "   dbt test --select staging"
echo ""
