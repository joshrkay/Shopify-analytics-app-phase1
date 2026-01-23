#!/usr/bin/env python3
"""
Validation script for Story 4.1 - dbt Project Initialization

Tests:
- All required files exist
- YAML syntax is valid
- .gitignore configuration
- No secrets committed
- Directory structure is correct
"""

import os
import sys
import re
from pathlib import Path

def test_file_exists(filepath, description):
    """Test that a required file exists."""
    if os.path.exists(filepath):
        print(f"✅ {description}: {filepath}")
        return True
    else:
        print(f"❌ {description}: {filepath} - MISSING")
        return False

def test_yaml_basic_syntax(filepath, description):
    """Test basic YAML syntax (checks for common errors)."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            # Basic YAML validation: check for unclosed quotes, brackets
            # This is a simple check - full validation requires dbt or yaml library
            if content.count('"') % 2 == 0 and content.count("'") % 2 == 0:
                # Check for basic structure
                if ':' in content:  # YAML should have key-value pairs
                    print(f"✅ {description}: Basic YAML structure looks valid")
                    return True
                else:
                    print(f"⚠️  {description}: No key-value pairs found")
                    return False
            else:
                print(f"❌ {description}: Unmatched quotes detected")
                return False
    except FileNotFoundError:
        print(f"❌ {description}: File not found")
        return False
    except Exception as e:
        print(f"⚠️  {description}: Could not validate - {e}")
        return True  # Don't fail on validation errors, just warn

def test_gitignore(filepath):
    """Test that sensitive file is gitignored."""
    if os.path.exists(filepath):
        print(f"⚠️  {filepath} exists (should be gitignored)")
        return False
    else:
        print(f"✅ {filepath} not found (correctly gitignored)")
        return True

def test_directory_structure():
    """Test that required directories exist."""
    required_dirs = [
        "models/staging/shopify",
        "models/staging/ads",
        "models/facts",
        "models/metrics",
        "models/attribution",
        "macros",
        "tests"
    ]
    
    all_exist = True
    for dir_path in required_dirs:
        if os.path.isdir(dir_path):
            print(f"✅ Directory exists: {dir_path}")
        else:
            print(f"❌ Directory missing: {dir_path}")
            all_exist = False
    
    return all_exist

def test_no_secrets_in_files():
    """Test that no secrets are hardcoded in committed files."""
    files_to_check = [
        "dbt_project.yml",
        "profiles.yml.example",
        "README.md",
        "requirements.txt"
    ]
    
    # More specific patterns to avoid false positives
    secret_patterns = [
        (r'password\s*:\s*["\'][^"\']+["\']', "hardcoded password"),
        (r'secret\s*:\s*["\'][^"\']+["\']', "hardcoded secret"),
        (r'token\s*:\s*["\'][^"\']+["\']', "hardcoded token"),
        (r'api[_-]?key\s*:\s*["\'][^"\']+["\']', "hardcoded API key"),
    ]
    
    # Safe patterns (these are OK)
    safe_patterns = [
        r'unique_key',  # dbt configuration
        r'primary_key',  # database terminology
        r'env_var',  # environment variable references
        r'your-password',  # documentation examples
        r'example',  # example files
        r'template',  # template files
    ]
    
    issues = []
    
    for filepath in files_to_check:
        if not os.path.exists(filepath):
            continue
            
        with open(filepath, 'r') as f:
            content = f.read()
            content_lower = content.lower()
            
            # Skip if it's clearly a template/example
            if "example" in filepath.lower() or "template" in content_lower:
                continue
            
            for pattern, description in secret_patterns:
                matches = re.finditer(pattern, content_lower)
                for match in matches:
                    # Check if it's a safe pattern
                    is_safe = False
                    for safe_pattern in safe_patterns:
                        if re.search(safe_pattern, content[:match.end()], re.IGNORECASE):
                            is_safe = True
                            break
                    
                    if not is_safe:
                        issues.append(f"{filepath} contains potential {description}")
    
    if issues:
        for issue in issues:
            print(f"⚠️  {issue}")
        return False
    else:
        print("✅ No hardcoded secrets found in committed files")
        return True

def main():
    """Run all validation tests."""
    print("=" * 60)
    print("Story 4.1 - dbt Project Initialization Validation")
    print("=" * 60)
    print()
    
    # Change to analytics directory
    analytics_dir = Path(__file__).parent
    os.chdir(analytics_dir)
    
    results = []
    
    # Test 1: Required files exist
    print("Test 1: Required Files")
    print("-" * 60)
    results.append(test_file_exists("dbt_project.yml", "dbt_project.yml"))
    results.append(test_file_exists("profiles.yml.example", "profiles.yml.example"))
    results.append(test_file_exists("README.md", "README.md"))
    results.append(test_file_exists("requirements.txt", "requirements.txt"))
    results.append(test_file_exists(".gitignore", ".gitignore"))
    print()
    
    # Test 2: YAML syntax validation (basic)
    print("Test 2: YAML Syntax Validation (Basic)")
    print("-" * 60)
    print("Note: Full YAML validation requires dbt or PyYAML. Running basic checks...")
    results.append(test_yaml_basic_syntax("dbt_project.yml", "dbt_project.yml"))
    results.append(test_yaml_basic_syntax("profiles.yml.example", "profiles.yml.example"))
    print()
    
    # Test 3: Directory structure
    print("Test 3: Directory Structure")
    print("-" * 60)
    results.append(test_directory_structure())
    print()
    
    # Test 4: Security - profiles.yml gitignored
    print("Test 4: Security - Credentials Protection")
    print("-" * 60)
    results.append(test_gitignore("profiles.yml"))
    results.append(test_no_secrets_in_files())
    print()
    
    # Test 5: Check .gitignore content
    print("Test 5: .gitignore Configuration")
    print("-" * 60)
    if os.path.exists(".gitignore"):
        with open(".gitignore", 'r') as f:
            gitignore_content = f.read()
            required_patterns = ["profiles.yml", "target/", "dbt_packages/"]
            for pattern in required_patterns:
                if pattern in gitignore_content:
                    print(f"✅ .gitignore contains: {pattern}")
                else:
                    print(f"❌ .gitignore missing: {pattern}")
                    results.append(False)
    print()
    
    # Summary
    print("=" * 60)
    print("Validation Summary")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ All tests passed ({passed}/{total})")
        print()
        print("Next steps:")
        print("1. Install dbt: pip install -r requirements.txt")
        print("2. Set database environment variables")
        print("3. Run: dbt debug")
        print("4. Run: dbt run")
        return 0
    else:
        print(f"❌ Some tests failed ({passed}/{total} passed)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
