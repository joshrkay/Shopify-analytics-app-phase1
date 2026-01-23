#!/usr/bin/env python3
"""
Simple test data setup using urllib and subprocess to avoid psycopg2 dependency.
Uses psql if available, otherwise provides instructions.
"""

import os
import subprocess
import sys

def get_connection_string():
    """Get database connection string from environment."""
    db_url = os.getenv("DATABASE_URL")
    if db_url:
        return db_url
    
    # Build from individual components
    host = os.getenv("DB_HOST")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    port = os.getenv("DB_PORT", "5432")
    dbname = os.getenv("DB_NAME")
    
    if all([host, user, password, dbname]):
        return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    
    return None

def setup_with_psql():
    """Set up test data using psql."""
    conn_str = get_connection_string()
    if not conn_str:
        print("❌ Database connection not configured")
        print("   Set DATABASE_URL or DB_* environment variables")
        return False
    
    sql_file = os.path.join(os.path.dirname(__file__), "tests", "test_data_setup.sql")
    if not os.path.exists(sql_file):
        print(f"❌ Test data SQL file not found: {sql_file}")
        return False
    
    print("Setting up test data using psql...")
    print(f"  Connection: {conn_str.split('@')[0]}@...")
    print(f"  SQL file: {sql_file}")
    print("")
    
    try:
        # Use PGPASSWORD for password
        env = os.environ.copy()
        if "DATABASE_URL" in env:
            # Extract password from URL if needed
            pass
        elif "DB_PASSWORD" in env:
            env["PGPASSWORD"] = env["DB_PASSWORD"]
        
        result = subprocess.run(
            ["psql", conn_str, "-f", sql_file],
            capture_output=True,
            text=True,
            env=env
        )
        
        if result.returncode == 0:
            print("✅ Test data setup complete")
            if result.stdout:
                print(result.stdout)
            return True
        else:
            print("❌ Test data setup failed")
            print(result.stderr)
            return False
            
    except FileNotFoundError:
        print("❌ psql not found")
        print("   Install PostgreSQL client tools")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

def main():
    """Main entry point."""
    print("==========================================")
    print("Test Data Setup for Render Database")
    print("==========================================")
    print("")
    
    # Check if psql is available
    if not subprocess.run(["which", "psql"], capture_output=True).returncode == 0:
        psql_path = subprocess.run(["which", "psql"], capture_output=True, text=True)
        if psql_path.returncode != 0:
            print("⚠️  psql not found in PATH")
            print("")
            print("To set up test data manually:")
            print("  1. Install PostgreSQL client tools")
            print("  2. Run: psql $DATABASE_URL -f tests/test_data_setup.sql")
            print("")
            print("Or install psycopg2 and use:")
            print("  python3 tests/validate_with_test_data.py")
            print("")
            return 1
    
    # Try to set up with psql
    if setup_with_psql():
        print("")
        print("✅ Test data is ready!")
        print("")
        print("Next steps:")
        print("  dbt run --select staging --vars '{\"test_schema\": \"test_airbyte\"}'")
        print("  dbt test --select staging --vars '{\"test_schema\": \"test_airbyte\"}'")
        return 0
    else:
        return 1

if __name__ == "__main__":
    sys.exit(main())
