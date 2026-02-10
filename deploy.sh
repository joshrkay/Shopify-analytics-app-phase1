#!/bin/bash

# Deployment Script for Core Metrics Implementation
# This script commits all metric files and pushes to the repository

set -e  # Exit on error

echo "🚀 Starting deployment process..."
echo ""

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Navigate to project root
cd "$(dirname "$0")/Shopify-analytics-app"

echo -e "${BLUE}📂 Current directory: $(pwd)${NC}"
echo ""

# Check if git repo
if [ ! -d ".git" ]; then
    echo -e "${YELLOW}⚠️  Not a git repository. Initializing...${NC}"
    git init
fi

# Show current status
echo -e "${BLUE}📊 Git Status:${NC}"
git status --short
echo ""

# Stage all new metric files
echo -e "${BLUE}📦 Staging files...${NC}"

# Metrics models
git add analytics/models/metrics/fct_revenue.sql || true
git add analytics/models/metrics/fct_aov.sql || true
git add analytics/models/metrics/fct_roas.sql || true
git add analytics/models/metrics/fct_cac.sql || true
git add analytics/models/metrics/schema.yml || true

# Utility models
git add analytics/models/utils/dim_date_ranges.sql || true

# Marts
git add analytics/models/marts/mart_revenue_metrics.sql || true
git add analytics/models/marts/mart_marketing_metrics.sql || true

# Tests
git add analytics/tests/test_revenue_edge_cases.sql || true
git add analytics/tests/test_aov_edge_cases.sql || true
git add analytics/tests/test_roas_edge_cases.sql || true
git add analytics/tests/test_cac_edge_cases.sql || true

# Seeds
git add analytics/seeds/seed_revenue_test_orders.csv || true

# Documentation
git add ../IMPLEMENTATION_PLAN.md || true
git add ../METRICS_IMPLEMENTATION_SUMMARY.md || true
git add ../FLEXIBLE_DATE_RANGES_GUIDE.md || true
git add ../DEPLOYMENT_CHECKLIST.md || true

echo -e "${GREEN}✅ Files staged${NC}"
echo ""

# Show what will be committed
echo -e "${BLUE}📝 Files to be committed:${NC}"
git status --short
echo ""

# Create commit message
COMMIT_MSG="feat: Add core business metrics (Revenue, AOV, ROAS, CAC)

This commit implements Story 4.5 - Core Business Metrics:

**New Models:**
- fct_revenue: Revenue waterfall (gross/net/refunds/cancellations)
- fct_aov: Average Order Value with outlier detection
- fct_roas: Gross & Net ROAS with platform-specific attribution
- fct_cac: CAC & nCAC with customer quality metrics
- dim_date_ranges: Date dimension for flexible date ranges
- mart_revenue_metrics: Revenue mart with period-over-period comparisons
- mart_marketing_metrics: ROAS + CAC mart with period-over-period comparisons

**Features:**
- 51 edge case tests across all metrics
- Flexible date ranges (daily, weekly, monthly, quarterly, yearly, last_7/30/90_days)
- Period-over-period comparisons (MoM, WoW, QoQ, etc.)
- Multi-currency support
- Tenant isolation enforced
- Complete dbt documentation

**Edge Cases Handled:**
- Zero/null values → Returns 0 (not NULL or infinity)
- Multi-currency → Calculated separately per currency
- Tenant isolation → NEVER leaks data across tenants
- Outlier detection for AOV (3-sigma rule)
- Refund/cancellation handling for revenue
- Customer quality metrics (nCAC vs CAC)

**Documentation:**
- Implementation summary with validation steps
- Flexible date ranges usage guide (15+ examples)
- Deployment checklist
- Complete schema documentation

**Tests:**
- test_revenue_edge_cases.sql (10 tests)
- test_aov_edge_cases.sql (10 tests)
- test_roas_edge_cases.sql (13 tests)
- test_cac_edge_cases.sql (18 tests)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"

# Commit the changes
echo -e "${BLUE}💾 Creating commit...${NC}"
git commit -m "$COMMIT_MSG"

echo -e "${GREEN}✅ Commit created successfully!${NC}"
echo ""

# Show commit details
echo -e "${BLUE}📋 Commit Details:${NC}"
git log -1 --stat
echo ""

# Check if remote exists
if git remote | grep -q 'origin'; then
    echo -e "${BLUE}🔗 Remote 'origin' found${NC}"
    echo ""

    # Ask user if they want to push
    read -p "$(echo -e ${YELLOW}Push to remote? [y/N]: ${NC})" -n 1 -r
    echo ""

    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${BLUE}📤 Pushing to remote...${NC}"

        # Get current branch
        CURRENT_BRANCH=$(git branch --show-current)

        # Push to remote
        git push origin "$CURRENT_BRANCH"

        echo -e "${GREEN}✅ Pushed to origin/$CURRENT_BRANCH${NC}"
    else
        echo -e "${YELLOW}⏭️  Skipping push. You can push later with:${NC}"
        echo -e "   git push origin $(git branch --show-current)"
    fi
else
    echo -e "${YELLOW}⚠️  No remote 'origin' configured${NC}"
    echo -e "${YELLOW}   Add a remote with: git remote add origin <url>${NC}"
    echo -e "${YELLOW}   Then push with: git push -u origin $(git branch --show-current)${NC}"
fi

echo ""
echo -e "${GREEN}✨ Deployment script complete!${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo "1. Run dbt models: cd analytics && dbt run --models metrics marts"
echo "2. Run tests: dbt test --models metrics marts"
echo "3. Validate with real data (see DEPLOYMENT_CHECKLIST.md)"
echo "4. Review documentation: FLEXIBLE_DATE_RANGES_GUIDE.md"
echo ""
