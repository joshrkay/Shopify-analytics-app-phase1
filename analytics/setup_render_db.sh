#!/bin/bash
# Render Database Connection Setup Script
#
# This script configures dbt to use the Render database by parsing DATABASE_URL
# into individual components that dbt-postgres requires.
#
# Usage:
#   1. Get DATABASE_URL from Render dashboard (or set it as environment variable)
#   2. Run: ./setup_render_db.sh
#   3. The script will parse DATABASE_URL and set DB_* variables

set -e

echo "=========================================="
echo "Render Database Connection Setup"
echo "=========================================="
echo ""

# Check for DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    echo "⚠️  DATABASE_URL not found in environment"
    echo ""
    echo "To get your Render database connection string:"
    echo "  1. Go to Render dashboard: https://dashboard.render.com"
    echo "  2. Navigate to your database: shopify-analytics-db"
    echo "  3. Copy the 'Internal Database URL' or 'External Database URL'"
    echo "  4. Set it as:"
    echo "     export DATABASE_URL=\"postgresql://user:pass@host:port/database\""
    echo ""
    echo "Or add it to your .env file:"
    echo "  1. Edit analytics/.env"
    echo "  2. Add: DATABASE_URL=\"your-connection-string\""
    echo ""
    exit 1
fi

echo "✅ DATABASE_URL found"
echo ""

# Normalize postgres:// to postgresql:// (Render uses postgres://)
DB_URL="$DATABASE_URL"
if [[ "$DB_URL" == postgres://* ]]; then
    DB_URL="${DB_URL/postgres:\/\//postgresql:\/\/}"
    echo "   Converted postgres:// to postgresql://"
fi

# Parse DATABASE_URL using Python (more reliable than sed for complex URLs)
echo "   Parsing DATABASE_URL into components..."
eval $(python3 << 'PYEOF'
import re
import os
import sys

db_url = os.environ.get('DATABASE_URL', '')
if not db_url:
    sys.exit(1)

# Handle postgres:// vs postgresql://
if db_url.startswith('postgres://'):
    db_url = db_url.replace('postgres://', 'postgresql://', 1)

# Parse the URL: postgresql://[user[:password]@][host][:port][/database][?params]
# Handle various formats including URLs with special characters in password
pattern = r'postgresql://(?:([^:]+)(?::([^@]+))?@)?([^:/]+)(?::(\d+))?/([^?]+)'
match = re.match(pattern, db_url)

if match:
    user, password, host, port, dbname = match.groups()
    
    # Defaults
    user = user or 'postgres'
    password = password or ''
    host = host or 'localhost'
    port = port or '5432'
    dbname = dbname or 'shopify_analytics'
    
    # URL decode password if needed (handle % encoding)
    import urllib.parse
    if password:
        password = urllib.parse.unquote(password)
    
    print(f'export DB_HOST="{host}"')
    print(f'export DB_USER="{user}"')
    print(f'export DB_PASSWORD="{password}"')
    print(f'export DB_PORT="{port}"')
    print(f'export DB_NAME="{dbname}"')
else:
    print("# ERROR: Could not parse DATABASE_URL", file=sys.stderr)
    print("# URL format: postgresql://user:password@host:port/database", file=sys.stderr)
    sys.exit(1)
PYEOF
)

if [ $? -ne 0 ]; then
    echo "❌ Failed to parse DATABASE_URL"
    echo ""
    echo "Expected format: postgresql://user:password@host:port/database"
    echo "Or: postgres://user:password@host:port/database"
    exit 1
fi

echo ""
echo "✅ Parsed database connection:"
echo "   Host: $DB_HOST"
echo "   User: $DB_USER"
echo "   Port: $DB_PORT"
echo "   Database: $DB_NAME"
echo "   Password: [hidden]"
echo ""

# Update .env file
if [ -f ".env" ]; then
    echo "Updating .env file..."
    
    # Remove old DB_* entries
    sed -i.bak '/^DB_HOST=/d; /^DB_USER=/d; /^DB_PASSWORD=/d; /^DB_PORT=/d; /^DB_NAME=/d' .env 2>/dev/null || \
    sed -i '' '/^DB_HOST=/d; /^DB_USER=/d; /^DB_PASSWORD=/d; /^DB_PORT=/d; /^DB_NAME=/d' .env
    
    # Add new entries
    echo "" >> .env
    echo "# Database connection (parsed from DATABASE_URL)" >> .env
    echo "DB_HOST=$DB_HOST" >> .env
    echo "DB_USER=$DB_USER" >> .env
    echo "DB_PASSWORD=$DB_PASSWORD" >> .env
    echo "DB_PORT=$DB_PORT" >> .env
    echo "DB_NAME=$DB_NAME" >> .env
    
    # Also keep DATABASE_URL if not already present
    if ! grep -q "^DATABASE_URL=" .env; then
        echo "DATABASE_URL=$DATABASE_URL" >> .env
    fi
    
    echo "✅ Updated .env file"
else
    echo "Creating .env file..."
    cat > .env << EOF
# Database connection from Render
DATABASE_URL=$DATABASE_URL

# Parsed components (for dbt)
DB_HOST=$DB_HOST
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_PORT=$DB_PORT
DB_NAME=$DB_NAME
EOF
    echo "✅ Created .env file"
fi

echo ""
echo "=========================================="
echo "Connection Test"
echo "=========================================="
echo ""

# Test connection if psql is available
if command -v psql &> /dev/null; then
    echo "Testing database connection..."
    if PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT 1" > /dev/null 2>&1; then
        echo "✅ Database connection successful!"
    else
        echo "⚠️  Connection test failed (this might be expected if using external URL)"
        echo "   You may need to whitelist your IP in Render dashboard"
        echo "   Or use the Internal Database URL if running from Render services"
    fi
else
    echo "   (Skipping - psql not available)"
fi

echo ""
echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo ""
echo "1. Load environment variables:"
echo "   cd analytics"
echo "   source load_env.sh"
echo ""
echo "2. Test dbt connection:"
echo "   dbt debug"
echo ""
echo "3. Set up test data (if needed):"
echo "   python3 tests/validate_with_test_data.py"
echo ""
echo "4. Run staging models:"
echo "   dbt run --select staging"
echo ""
echo "5. Run tests:"
echo "   dbt test --select staging"
echo ""
echo "=========================================="
echo "Environment Variables (for this session)"
echo "=========================================="
echo ""
echo "These variables are set for your current shell session."
echo "To persist them, add to your shell profile or use .env file:"
echo ""
echo "   export DB_HOST=\"$DB_HOST\""
echo "   export DB_USER=\"$DB_USER\""
echo "   export DB_PASSWORD=\"$DB_PASSWORD\""
echo "   export DB_PORT=\"$DB_PORT\""
echo "   export DB_NAME=\"$DB_NAME\""
echo ""
