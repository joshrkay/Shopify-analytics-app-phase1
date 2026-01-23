# PR: Story 4.1 - dbt Project Initialization

## Commit Message

```
feat(epic-4): Initialize dbt project for analytics platform (Story 4.1)

- Created dbt project structure with dbt_project.yml configuration
- Added profiles.yml.example template for local/staging/production environments
- Configured profiles to use environment variables for database credentials
- Added comprehensive README.md with setup and usage instructions
- Created requirements.txt with pinned dbt-core and dbt-postgres versions
- Updated .gitignore to exclude profiles.yml and dbt build artifacts
- Created directory structure for staging, facts, metrics, and attribution models

This initializes the dbt analytics layer that will transform raw Airbyte data
into canonical fact tables and metrics. All credentials are secured via
environment variables, and profiles.yml is gitignored to prevent secret leakage.
The project follows .cursorrules standards with no TODOs, complete documentation,
and proper security practices.
```

## PR Description

### Why

**Story 4.1** - As a data platform owner, I want a properly configured dbt project so that transformations are versioned, testable, and reproducible.

This PR initializes the dbt analytics platform foundation. Without a properly configured dbt project, we cannot:
- Transform raw Airbyte data into canonical models
- Ensure data transformations are versioned and testable
- Maintain reproducible analytics across environments
- Enforce tenant isolation at the data transformation layer

### What Changed

- **Created `analytics/dbt_project.yml`**: Project configuration with model paths, materialization strategies, and schema definitions
- **Created `analytics/profiles.yml.example`**: Profile template supporting local, staging, and production targets with environment variable-based credentials
- **Created `analytics/README.md`**: Comprehensive documentation covering setup, usage, troubleshooting, and security guidelines
- **Created `analytics/requirements.txt`**: Pinned dependencies (dbt-core>=1.7.0,<2.0.0, dbt-postgres>=1.7.0,<2.0.0)
- **Created `analytics/.gitignore`**: dbt-specific ignores (profiles.yml, target/, dbt_packages/, logs/)
- **Updated root `.gitignore`**: Added dbt-specific ignores to prevent credential and artifact commits
- **Created directory structure**: All required directories for staging, facts, metrics, attribution, macros, and tests

### Security

- ✅ **No secrets committed**: `profiles.yml` is gitignored, only `.example` template is committed
- ✅ **Credentials via env vars**: All database credentials come from environment variables (never hardcoded)
- ✅ **Clear security warnings**: README and profiles.yml.example include explicit security guidance

### Testing

- ✅ **Local verification**: `dbt debug` and `dbt run` succeed with empty project
- ✅ **No breaking changes**: New project, no existing code affected
- ✅ **Documentation complete**: README includes troubleshooting and setup instructions

### Compliance with .cursorrules

- ✅ **YAGNI**: Only implements Story 4.1 requirements (no extras)
- ✅ **No TODOs**: All code is complete, no placeholder comments
- ✅ **Documentation**: README.md provides complete setup and usage guidance
- ✅ **Security**: Credentials secured, profiles.yml gitignored
- ✅ **No dead code**: Only necessary files created
- ✅ **Clear naming**: Consistent directory structure and file naming

### Acceptance Criteria

- [x] dbt project initialized with proper structure
- [x] Profiles configured for local, staging, production
- [x] Credentials secured via env vars (never in code)
- [x] Documentation complete (README.md)
- [x] `.gitignore` updated to exclude credentials and artifacts

### How to Test Locally

```bash
cd analytics
pip install -r requirements.txt

# Set database connection environment variables
export DB_HOST="localhost"
export DB_USER="postgres"
export DB_PASSWORD="your-password"
export DB_PORT="5432"
export DB_NAME="shopify_analytics"

# Verify connection
dbt debug

# Run empty project (should succeed)
dbt run
```

### Next Steps

After this PR is merged:
- Story 4.2: Create Shopify staging models (stg_shopify_orders, stg_shopify_customers)
- Story 4.3: Create ad platform staging models (stg_meta_ads, stg_google_ads)
- Story 4.4: Create canonical fact tables

### Files Changed

```
analytics/
├── dbt_project.yml (new)
├── profiles.yml.example (new)
├── .gitignore (new)
├── README.md (new)
├── requirements.txt (new)
└── [directory structure created]

.gitignore (updated)
```

---

**Story**: 4.1 - dbt Project Initialization  
**Epic**: 4 - Analytics Platform  
**Points**: 3
