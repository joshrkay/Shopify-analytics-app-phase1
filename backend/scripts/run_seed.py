#!/usr/bin/env python3
"""
Run database seed scripts using psycopg2.

Usage:
    python backend/scripts/run_seed.py [seed_file]

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


def run_seed(seed_file: str, database_url: str):
    """Execute a SQL seed file."""
    seed_path = Path(seed_file)
    
    if not seed_path.exists():
        print(f"Error: Seed file not found: {seed_file}")
        sys.exit(1)
    
    # Read seed SQL
    print(f"Reading seed file: {seed_path}")
    with open(seed_path, "r") as f:
        seed_sql = f.read()
    
    if not seed_sql.strip():
        print("Error: Seed file is empty")
        sys.exit(1)
    
    # Connect to database
    print("Connecting to database...")
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cursor = conn.cursor()
    except psycopg2.Error as e:
        print(f"Error connecting to database: {e}")
        sys.exit(1)
    
    # Execute seed
    print(f"Executing seed: {seed_path.name}")
    try:
        cursor.execute(seed_sql)
        print("✓ Seed script executed successfully!")
        
        # Verify plans were seeded
        cursor.execute("SELECT COUNT(*) FROM plans WHERE is_active = true;")
        plan_count = cursor.fetchone()[0]
        print(f"✓ Active plans: {plan_count}")
        
        # Verify plan features were seeded
        cursor.execute("SELECT COUNT(*) FROM plan_features WHERE is_enabled = true;")
        feature_count = cursor.fetchone()[0]
        print(f"✓ Enabled plan features: {feature_count}")
        
        # Show plan summary
        cursor.execute("""
            SELECT p.name, p.display_name, COUNT(pf.feature_key) as feature_count
            FROM plans p
            LEFT JOIN plan_features pf ON p.id = pf.plan_id AND pf.is_enabled = true
            WHERE p.is_active = true
            GROUP BY p.id, p.name, p.display_name
            ORDER BY p.name;
        """)
        plans = cursor.fetchall()
        
        if plans:
            print("\n✓ Plans seeded:")
            for plan_name, display_name, feature_count in plans:
                print(f"  - {display_name} ({plan_name}): {feature_count} features")
        
    except psycopg2.Error as e:
        print(f"\n✗ Seed failed: {e}")
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
    
    # Get seed file (default or from args)
    if len(sys.argv) > 1:
        seed_file = sys.argv[1]
    else:
        # Default to plans seed
        script_dir = Path(__file__).parent
        project_root = script_dir.parent.parent
        seed_file = project_root / "backend" / "seeds" / "seed_plans.sql"
    
    run_seed(str(seed_file), database_url)


if __name__ == "__main__":
    main()
