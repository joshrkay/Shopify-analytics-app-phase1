#!/bin/bash
# Quick Database Setup
# This script helps you quickly configure database connection

echo "=========================================="
echo "Quick Database Configuration"
echo "=========================================="
echo ""

# Check if .env exists
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cat > .env << 'ENVEOF'
# Database Connection
DB_HOST=localhost
DB_USER=postgres
DB_PASSWORD=test
DB_PORT=5432
DB_NAME=shopify_analytics
ENVEOF
    echo "✅ Created .env file"
    echo ""
    echo "⚠️  Please edit .env with your actual database credentials"
    echo ""
fi

# Load .env
if [ -f ".env" ]; then
    source load_env.sh 2>/dev/null || export $(grep -v '^#' .env | xargs)
fi

# Check if variables are set
if [ -z "$DB_PASSWORD" ] || [ "$DB_PASSWORD" = "test" ] || [ "$DB_PASSWORD" = "your-password" ]; then
    echo "⚠️  Database password not configured"
    echo ""
    echo "Please set your database credentials:"
    echo "  1. Edit analytics/.env"
    echo "  2. Or set environment variables:"
    echo "     export DB_HOST=\"localhost\""
    echo "     export DB_USER=\"postgres\""
    echo "     export DB_PASSWORD=\"your-password\""
    echo "     export DB_PORT=\"5432\""
    echo "     export DB_NAME=\"shopify_analytics\""
    echo ""
else
    echo "✅ Database configuration found"
    echo "   Host: ${DB_HOST:-localhost}"
    echo "   User: ${DB_USER:-postgres}"
    echo "   Port: ${DB_PORT:-5432}"
    echo "   Database: ${DB_NAME:-shopify_analytics}"
    echo ""
fi

echo "To test connection:"
echo "  cd analytics"
echo "  dbt debug"
echo ""
