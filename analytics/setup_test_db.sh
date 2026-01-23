#!/bin/bash
# Database Connection Setup Script
#
# This script helps configure database connection for testing
# It checks for existing configuration and provides setup instructions

set -e

echo "=========================================="
echo "Database Connection Setup"
echo "=========================================="
echo ""

# Check for existing profiles.yml
if [ -f "analytics/profiles.yml" ]; then
    echo "✅ profiles.yml exists"
    echo "   Using existing configuration"
else
    echo "⚠️  profiles.yml not found"
    echo "   Creating from template..."
    cp analytics/profiles.yml.example analytics/profiles.yml
    echo "✅ Created profiles.yml from template"
    echo "   Edit analytics/profiles.yml with your database credentials"
fi

# Check for DATABASE_URL
if [ -n "$DATABASE_URL" ]; then
    echo ""
    echo "✅ DATABASE_URL is set"
    echo "   Parsing DATABASE_URL into components..."
    
    # Parse DATABASE_URL (postgresql://user:pass@host:port/dbname)
    DB_URL="$DATABASE_URL"
    
    # Handle postgres:// vs postgresql://
    if [[ "$DB_URL" == postgres://* ]]; then
        DB_URL="${DB_URL/postgres:\/\//postgresql:\/\/}"
    fi
    
    # Extract components using Python (more reliable than sed)
    python3 << EOF
import re
import os

db_url = os.environ.get('DATABASE_URL', '')
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

# Parse the URL
pattern = r'postgresql://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)'
match = re.match(pattern, db_url)

if match:
    user, password, host, port, dbname = match.groups()
    print(f"export DB_HOST=\"{host}\"")
    print(f"export DB_USER=\"{user}\"")
    print(f"export DB_PASSWORD=\"{password}\"")
    print(f"export DB_PORT=\"{port}\"")
    print(f"export DB_NAME=\"{dbname}\"")
else:
    print("# Could not parse DATABASE_URL")
    print("# Please set DB_* variables manually")
EOF
    
    echo ""
    echo "   Run the export commands above to set individual DB_* variables"
    echo "   Or use DATABASE_URL directly (dbt will need individual vars)"
    
elif [ -n "$DB_HOST" ] && [ -n "$DB_USER" ] && [ -n "$DB_PASSWORD" ]; then
    echo ""
    echo "✅ DB_* environment variables are set"
    echo "   Host: $DB_HOST"
    echo "   User: $DB_USER"
    echo "   Port: ${DB_PORT:-5432}"
    echo "   Database: ${DB_NAME:-shopify_analytics}"
    
else
    echo ""
    echo "⚠️  No database connection configured"
    echo ""
    echo "Setup Options:"
    echo ""
    echo "Option 1: Set DATABASE_URL"
    echo "  export DATABASE_URL=\"postgresql://user:password@host:port/database\""
    echo ""
    echo "Option 2: Set individual variables"
    echo "  export DB_HOST=\"localhost\""
    echo "  export DB_USER=\"postgres\""
    echo "  export DB_PASSWORD=\"your-password\""
    echo "  export DB_PORT=\"5432\""
    echo "  export DB_NAME=\"shopify_analytics\""
    echo ""
    echo "Option 3: Edit profiles.yml directly"
    echo "  cp analytics/profiles.yml.example analytics/profiles.yml"
    echo "  # Edit analytics/profiles.yml with your credentials"
    echo ""
fi

# Check for PostgreSQL client
if command -v psql &> /dev/null; then
    echo ""
    echo "✅ psql is installed"
    echo "   Ready to run SQL scripts"
else
    echo ""
    echo "⚠️  psql not found"
    echo "   Install PostgreSQL client tools to run SQL scripts directly"
    echo "   Or use Python script: python3 tests/validate_with_test_data.py"
fi

# Check for Python psycopg2
if python3 -c "import psycopg2" 2>/dev/null; then
    echo ""
    echo "✅ psycopg2 is installed"
    echo "   Ready to run Python test scripts"
else
    echo ""
    echo "⚠️  psycopg2 not installed"
    echo "   Install with: pip install psycopg2-binary"
fi

# Test connection if credentials are available
if [ -n "$DATABASE_URL" ] || ([ -n "$DB_HOST" ] && [ -n "$DB_USER" ]); then
    echo ""
    echo "Testing database connection..."
    
    if command -v psql &> /dev/null; then
        if [ -n "$DATABASE_URL" ]; then
            DB_CONN="$DATABASE_URL"
            if [[ "$DB_CONN" == postgres://* ]]; then
                DB_CONN="${DB_CONN/postgres:\/\//postgresql:\/\/}"
            fi
        else
            DB_CONN="postgresql://${DB_USER}@${DB_HOST}:${DB_PORT:-5432}/${DB_NAME:-shopify_analytics}"
        fi
        
        if psql "$DB_CONN" -c "SELECT 1" > /dev/null 2>&1; then
            echo "✅ Database connection successful!"
        else
            echo "❌ Database connection failed"
            echo "   Check your credentials and network access"
        fi
    else
        echo "   (Skipping - psql not available)"
    fi
fi

echo ""
echo "=========================================="
echo "Next Steps:"
echo "=========================================="
echo ""
echo "1. Ensure database connection is configured (see above)"
echo "2. Run test data setup:"
echo "   ./analytics/tests/run_sql_tests.sh"
echo "   OR"
echo "   python3 analytics/tests/validate_with_test_data.py"
echo ""
echo "3. Once test data is loaded, run dbt:"
echo "   cd analytics"
echo "   dbt run --select staging"
echo "   dbt test --select staging"
echo ""
