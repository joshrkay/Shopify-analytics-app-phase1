#!/usr/bin/env python3
"""
Parse DATABASE_URL into individual components for dbt.

This script extracts DB_HOST, DB_USER, DB_PASSWORD, DB_PORT, and DB_NAME
from a DATABASE_URL connection string.

Usage:
    python3 parse_database_url.py
    # Or with explicit URL:
    DATABASE_URL="postgresql://user:pass@host:port/db" python3 parse_database_url.py
"""

import os
import re
import sys
import urllib.parse


def parse_database_url(database_url: str) -> dict:
    """
    Parse PostgreSQL DATABASE_URL into components.
    
    Handles:
    - postgres:// and postgresql:// schemes
    - URLs with or without passwords
    - URLs with special characters in passwords (URL encoded)
    - Internal and external Render database URLs
    
    Returns:
        dict with keys: host, user, password, port, dbname
    """
    if not database_url:
        raise ValueError("DATABASE_URL is empty")
    
    # Normalize postgres:// to postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    
    # Parse the URL
    # Format: postgresql://[user[:password]@][host][:port][/database][?params]
    pattern = r'postgresql://(?:([^:]+)(?::([^@]+))?@)?([^:/]+)(?::(\d+))?/([^?]+)'
    match = re.match(pattern, database_url)
    
    if not match:
        raise ValueError(
            f"Could not parse DATABASE_URL. "
            f"Expected format: postgresql://user:password@host:port/database"
        )
    
    user, password, host, port, dbname = match.groups()
    
    # Defaults
    user = user or "postgres"
    password = password or ""
    host = host or "localhost"
    port = port or "5432"
    dbname = dbname or "shopify_analytics"
    
    # URL decode password if needed (handle % encoding)
    if password:
        password = urllib.parse.unquote(password)
    
    return {
        "host": host,
        "user": user,
        "password": password,
        "port": port,
        "dbname": dbname,
    }


def main():
    """Main entry point."""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set", file=sys.stderr)
        print("", file=sys.stderr)
        print("Usage:", file=sys.stderr)
        print("  export DATABASE_URL=\"postgresql://user:pass@host:port/database\"", file=sys.stderr)
        print("  python3 parse_database_url.py", file=sys.stderr)
        sys.exit(1)
    
    try:
        components = parse_database_url(database_url)
        
        # Output as shell export statements
        print(f"export DB_HOST=\"{components['host']}\"")
        print(f"export DB_USER=\"{components['user']}\"")
        print(f"export DB_PASSWORD=\"{components['password']}\"")
        print(f"export DB_PORT=\"{components['port']}\"")
        print(f"export DB_NAME=\"{components['dbname']}\"")
        
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
