#!/usr/bin/env python3
"""
Run database migrations using psycopg2.

Usage:
    python backend/scripts/run_migration.py [migration_file]

Environment:
    DATABASE_URL: PostgreSQL connection string (required)
"""

import os
import sys
from pathlib import Path

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("Error: psycopg2 is required. Install with: pip install psycopg2-binary")
    sys.exit(1)


def run_migration(migration_file: str, database_url: str):
    """Execute a SQL migration file."""
    migration_path = Path(migration_file)
    
    if not migration_path.exists():
        print(f"Error: Migration file not found: {migration_file}")
        sys.exit(1)
    
    # Read migration SQL
    print(f"Reading migration file: {migration_path}")
    with open(migration_path, "r") as f:
        migration_sql = f.read()
    
    if not migration_sql.strip():
        print("Error: Migration file is empty")
        sys.exit(1)
    
    # Connect to database
    print("Connecting to database...")
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = True  # Required for CREATE TABLE statements
        cursor = conn.cursor()
    except psycopg2.Error as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)
    
    # Execute migration
    print(f"Executing migration: {migration_path.name}")
    try:
        cursor.execute(migration_sql)
        print("✓ Migration applied successfully!")
        
        # Verify tables were created
        cursor.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name IN ('plans', 'plan_features', 'tenant_subscriptions', 'usage_meters', 'usage_events')
            ORDER BY table_name;
        """)
        tables = cursor.fetchall()
        
        if tables:
            print(f"\n✓ Verified tables created: {', '.join([t[0] for t in tables])}")
        else:
            print("\n⚠ Warning: Expected tables not found. Migration may have failed.")
        
    except psycopg2.Error as e:
        print(f"\n✗ Migration failed: {e}")
        print(f"Error details: {e.pgcode} - {e.pgerror}")
        sys.exit(1)
    finally:
        cursor.close()
        conn.close()


def main():
    """Main entry point."""
    # Get DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable is required")
        print("Example: export DATABASE_URL='postgresql://user:pass@localhost:5432/dbname'")
        sys.exit(1)
    
    # Get migration file (default or from args)
    if len(sys.argv) > 1:
        migration_file = sys.argv[1]
    else:
        # Default to billing migration
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent
        migration_file = project_root / "backend" / "migrations" / "0001_billing_entitlements.sql"
    
    run_migration(str(migration_file), database_url)


if __name__ == "__main__":
    main()
