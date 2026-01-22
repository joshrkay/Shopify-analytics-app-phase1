#!/bin/bash
# Helper script to set up local database connection
# Usage: source backend/scripts/setup_local_db.sh

echo "Setting up local database connection..."
echo ""
echo "Choose your database source:"
echo "1) Local PostgreSQL (localhost)"
echo "2) Render Database (external connection)"
echo "3) Custom connection string"
echo ""
read -p "Enter choice [1-3]: " choice

case $choice in
    1)
        read -p "Database name [shopify_analytics]: " dbname
        dbname=${dbname:-shopify_analytics}
        read -p "Database user [postgres]: " dbuser
        dbuser=${dbuser:-postgres}
        read -sp "Database password: " dbpass
        echo ""
        read -p "Database host [localhost]: " dbhost
        dbhost=${dbhost:-localhost}
        read -p "Database port [5432]: " dbport
        dbport=${dbport:-5432}
        
        export DATABASE_URL="postgresql://${dbuser}:${dbpass}@${dbhost}:${dbport}/${dbname}"
        echo ""
        echo "✓ DATABASE_URL set (connection string hidden for security)"
        echo "Run: python backend/scripts/run_migration.py"
        ;;
    2)
        echo ""
        echo "Get your Render database connection string:"
        echo "1. Go to Render Dashboard → Your Database Service"
        echo "2. Click 'Connect' → Copy 'External Connection String'"
        echo ""
        read -sp "Paste connection string: " render_url
        echo ""
        export DATABASE_URL="$render_url"
        echo "✓ DATABASE_URL set"
        echo "Run: python backend/scripts/run_migration.py"
        ;;
    3)
        read -sp "Enter full PostgreSQL connection string: " custom_url
        echo ""
        export DATABASE_URL="$custom_url"
        echo "✓ DATABASE_URL set"
        echo "Run: python backend/scripts/run_migration.py"
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac
