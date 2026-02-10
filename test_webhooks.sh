#!/bin/bash
# Webhook Testing Script for Markinsight
# Run this on your local machine after installing Shopify CLI

echo "============================================"
echo "  Markinsight Webhook Testing Script"
echo "============================================"
echo ""

# Configuration
APP_URL="https://shopify-analytics-app-pmsl.onrender.com"
WEBHOOK_BASE="${APP_URL}/api/webhooks/shopify"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to test a webhook
test_webhook() {
    local topic=$1
    local endpoint=$2

    echo -e "${YELLOW}Testing: ${topic}${NC}"
    echo "  Endpoint: ${endpoint}"

    # Using Shopify CLI to trigger webhook
    npx @shopify/cli@latest app webhook trigger \
        --topic "${topic}" \
        --address "${endpoint}" \
        2>&1

    if [ $? -eq 0 ]; then
        echo -e "  ${GREEN}✓ Success${NC}"
    else
        echo -e "  ${RED}✗ Failed${NC}"
    fi
    echo ""
}

echo "Step 1: Wake up Render service (may take 50+ seconds on Free tier)..."
echo "  Hitting: ${APP_URL}/health"
curl -s -o /dev/null -w "  Status: %{http_code}\n" --max-time 60 "${APP_URL}/health" || echo "  Timeout - service may still be starting"
echo ""

echo "Step 2: Testing GDPR Mandatory Webhooks..."
echo "----------------------------------------"
test_webhook "customers/redact" "${WEBHOOK_BASE}/customers-redact"
test_webhook "customers/data_request" "${WEBHOOK_BASE}/customers-data-request"

echo -e "${YELLOW}⚠️  WARNING: shop/redact will DELETE ALL STORE DATA${NC}"
read -p "Test shop/redact webhook? (y/N): " confirm
if [[ $confirm == [yY] ]]; then
    test_webhook "shop/redact" "${WEBHOOK_BASE}/shop-redact"
else
    echo "  Skipped shop/redact"
fi
echo ""

echo "Step 3: Testing App Lifecycle Webhooks..."
echo "-----------------------------------------"
test_webhook "app/uninstalled" "${WEBHOOK_BASE}/app-uninstalled"
test_webhook "app_subscriptions/update" "${WEBHOOK_BASE}/subscription-update"

echo ""
echo "============================================"
echo "  Testing Complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Check Render logs for webhook processing entries"
echo "  2. Verify database changes for shop/redact and app/uninstalled"
echo "  3. If any failed, check the error messages above"
