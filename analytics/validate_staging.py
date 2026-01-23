#!/usr/bin/env python3
"""
Validation script for Story 4.2 - Shopify Staging Models

Validates:
- SQL syntax (basic checks)
- File structure
- dbt-specific syntax
- Tenant isolation logic
"""

import os
import re
import sys
from pathlib import Path

def check_sql_file(filepath):
    """Check SQL file for common issues."""
    issues = []
    
    with open(filepath, 'r') as f:
        content = f.read()
        lines = content.split('\n')
    
    # Check for basic SQL structure
    if 'select' not in content.lower() and 'with' not in content.lower():
        issues.append(f"{filepath}: No SELECT or WITH statement found")
    
    # Check for dbt macros
    if '{{' in content and '}}' in content:
        # Check for proper dbt macro syntax
        macro_pattern = r'\{\{[^}]*\}\}'
        macros = re.findall(macro_pattern, content)
        for macro in macros:
            if macro.count('{') != macro.count('}'):
                issues.append(f"{filepath}: Unbalanced braces in macro: {macro}")
    
    # Check for tenant_id
    if 'tenant_id' not in content.lower():
        issues.append(f"{filepath}: No tenant_id found - tenant isolation may be missing")
    
    # Check for TODO comments
    if 'todo' in content.lower():
        issues.append(f"{filepath}: Contains TODO comment (violates .cursorrules)")
    
    # Check for proper CTE structure (skip for test files)
    if 'with' in content.lower() and 'test' not in filepath.lower():
        # Count CTEs
        cte_count = content.lower().count('as (')
        if cte_count == 0:
            issues.append(f"{filepath}: WITH statement but no CTEs found")
    
    return issues

def check_yaml_file(filepath):
    """Check YAML file for common issues."""
    issues = []
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Check for version
    if 'version:' not in content:
        issues.append(f"{filepath}: No version specified")
    
    # Check for models or sources
    if 'models:' not in content and 'sources:' not in content:
        issues.append(f"{filepath}: No models or sources defined")
    
    # Check for tests (sources.yml doesn't require tests)
    if 'sources:' in content and 'tests:' not in content:
        # Sources can have tests but it's optional
        pass
    elif 'models:' in content and 'tests:' not in content:
        issues.append(f"{filepath}: Models defined but no tests found")
    
    return issues

def main():
    """Run validation."""
    print("=" * 60)
    print("Story 4.2 - Shopify Staging Models Validation")
    print("=" * 60)
    print()
    
    analytics_dir = Path(__file__).parent
    os.chdir(analytics_dir)
    
    all_issues = []
    
    # Check SQL files
    print("Validating SQL Files")
    print("-" * 60)
    sql_files = [
        "models/staging/_tenant_airbyte_connections.sql",
        "models/staging/shopify/stg_shopify_orders.sql",
        "models/staging/shopify/stg_shopify_customers.sql",
        "models/staging/ads/stg_meta_ads.sql",
        "models/staging/ads/stg_google_ads.sql",
        "tests/tenant_isolation.sql",
        "tests/test_tenant_mapping.sql"
    ]
    
    for sql_file in sql_files:
        if os.path.exists(sql_file):
            issues = check_sql_file(sql_file)
            if issues:
                for issue in issues:
                    print(f"⚠️  {issue}")
                    all_issues.append(issue)
            else:
                print(f"✅ {sql_file}")
        else:
            print(f"❌ {sql_file} - File not found")
            all_issues.append(f"{sql_file} not found")
    print()
    
    # Check YAML files
    print("Validating YAML Files")
    print("-" * 60)
    yaml_files = [
        "models/staging/schema.yml"
    ]
    
    for yaml_file in yaml_files:
        if os.path.exists(yaml_file):
            issues = check_yaml_file(yaml_file)
            if issues:
                for issue in issues:
                    print(f"⚠️  {issue}")
                    all_issues.append(issue)
            else:
                print(f"✅ {yaml_file}")
        else:
            print(f"❌ {yaml_file} - File not found")
            all_issues.append(f"{yaml_file} not found")
    print()
    
    # Check file structure
    print("Validating File Structure")
    print("-" * 60)
    required_files = [
        "models/staging/_tenant_airbyte_connections.sql",
        "models/staging/shopify/stg_shopify_orders.sql",
        "models/staging/shopify/stg_shopify_customers.sql",
        "models/staging/ads/stg_meta_ads.sql",
        "models/staging/ads/stg_google_ads.sql",
        "models/staging/schema.yml",
        "tests/tenant_isolation.sql",
        "tests/test_tenant_mapping.sql",
        "macros/get_tenant_id.sql"
    ]
    
    for filepath in required_files:
        if os.path.exists(filepath):
            print(f"✅ {filepath}")
        else:
            print(f"❌ {filepath} - Missing")
            all_issues.append(f"{filepath} missing")
    print()
    
    # Summary
    print("=" * 60)
    print("Validation Summary")
    print("=" * 60)
    
    if all_issues:
        print(f"❌ Found {len(all_issues)} issue(s):")
        for issue in all_issues:
            print(f"   - {issue}")
        print()
        print("Note: Full validation requires dbt to be installed and database connection.")
        print("Run: pip install -r requirements.txt")
        print("Then: dbt compile --select staging")
        return 1
    else:
        print("✅ All basic validation checks passed!")
        print()
        print("Next steps:")
        print("1. Install dbt: pip install -r requirements.txt")
        print("2. Set database environment variables")
        print("3. Run: dbt compile --select staging")
        print("4. Run: dbt run --select staging")
        print("5. Run: dbt test --select staging")
        return 0

if __name__ == "__main__":
    sys.exit(main())
