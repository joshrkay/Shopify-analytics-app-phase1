#!/bin/bash
# Test JWT authentication in deployed Render environment
# Usage: JWT_TOKEN='your-token' SERVICE_URL='https://your-api.onrender.com' ./test_jwt.sh

set -e

# Default values
SERVICE_URL="${SERVICE_URL:-https://ai-growth-api.onrender.com}"
JWT_TOKEN="${JWT_TOKEN}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if JWT_TOKEN is set
if [ -z "$JWT_TOKEN" ]; then
  echo -e "${RED}Error: JWT_TOKEN environment variable not set${NC}"
  echo "Usage: JWT_TOKEN='your-token' SERVICE_URL='https://your-api.onrender.com' ./test_jwt.sh"
  exit 1
fi

echo -e "${GREEN}Testing JWT authentication on ${SERVICE_URL}${NC}"
echo ""

# Test 1: Health check (no auth required)
echo -e "${YELLOW}Test 1: Health check (no auth required)${NC}"
HEALTH_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" "$SERVICE_URL/health")
HTTP_STATUS=$(echo "$HEALTH_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$HEALTH_RESPONSE" | sed '/HTTP_STATUS/d')

if [ "$HTTP_STATUS" = "200" ]; then
  echo -e "${GREEN}✓ Health check passed${NC}"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
else
  echo -e "${RED}✗ Health check failed (HTTP $HTTP_STATUS)${NC}"
  echo "$BODY"
fi
echo ""

# Test 2: Protected endpoint (with JWT)
echo -e "${YELLOW}Test 2: Protected endpoint (with JWT)${NC}"
AUTH_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  "$SERVICE_URL/api/data")
HTTP_STATUS=$(echo "$AUTH_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$AUTH_RESPONSE" | sed '/HTTP_STATUS/d')

if [ "$HTTP_STATUS" = "200" ]; then
  echo -e "${GREEN}✓ Authentication successful${NC}"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
  
  # Extract tenant_id from response
  TENANT_ID=$(echo "$BODY" | jq -r '.tenant_id' 2>/dev/null)
  if [ -n "$TENANT_ID" ] && [ "$TENANT_ID" != "null" ]; then
    echo -e "${GREEN}  Tenant ID: $TENANT_ID${NC}"
  fi
else
  echo -e "${RED}✗ Authentication failed (HTTP $HTTP_STATUS)${NC}"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
fi
echo ""

# Test 3: Missing token (should fail)
echo -e "${YELLOW}Test 3: Missing token (should return 403)${NC}"
NO_AUTH_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  "$SERVICE_URL/api/data")
HTTP_STATUS=$(echo "$NO_AUTH_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$NO_AUTH_RESPONSE" | sed '/HTTP_STATUS/d')

if [ "$HTTP_STATUS" = "403" ]; then
  echo -e "${GREEN}✓ Correctly rejected request without token${NC}"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
else
  echo -e "${RED}✗ Expected 403, got HTTP $HTTP_STATUS${NC}"
  echo "$BODY"
fi
echo ""

# Test 4: Invalid token (should fail)
echo -e "${YELLOW}Test 4: Invalid token (should return 403)${NC}"
INVALID_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  -H "Authorization: Bearer invalid-token-12345" \
  "$SERVICE_URL/api/data")
HTTP_STATUS=$(echo "$INVALID_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$INVALID_RESPONSE" | sed '/HTTP_STATUS/d')

if [ "$HTTP_STATUS" = "403" ]; then
  echo -e "${GREEN}✓ Correctly rejected invalid token${NC}"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
else
  echo -e "${RED}✗ Expected 403, got HTTP $HTTP_STATUS${NC}"
  echo "$BODY"
fi
echo ""

# Test 5: Verify tenant_id from body is ignored
echo -e "${YELLOW}Test 5: Verify tenant_id from body is ignored${NC}"
POST_RESPONSE=$(curl -s -w "\nHTTP_STATUS:%{http_code}" \
  -X POST \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "different-tenant-id", "name": "test"}' \
  "$SERVICE_URL/api/data")
HTTP_STATUS=$(echo "$POST_RESPONSE" | grep "HTTP_STATUS" | cut -d: -f2)
BODY=$(echo "$POST_RESPONSE" | sed '/HTTP_STATUS/d')

if [ "$HTTP_STATUS" = "200" ]; then
  RESPONSE_TENANT_ID=$(echo "$BODY" | jq -r '.tenant_id' 2>/dev/null)
  if [ "$RESPONSE_TENANT_ID" != "different-tenant-id" ]; then
    echo -e "${GREEN}✓ tenant_id from body correctly ignored${NC}"
    echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
    echo -e "${GREEN}  Response tenant_id ($RESPONSE_TENANT_ID) ≠ body tenant_id (different-tenant-id)${NC}"
  else
    echo -e "${RED}✗ SECURITY ISSUE: tenant_id from body was accepted!${NC}"
    echo "$BODY"
  fi
else
  echo -e "${RED}✗ Request failed (HTTP $HTTP_STATUS)${NC}"
  echo "$BODY"
fi
echo ""

# Test 6: Check X-Tenant-ID header
echo -e "${YELLOW}Test 6: Check X-Tenant-ID response header${NC}"
HEADERS=$(curl -s -I -H "Authorization: Bearer $JWT_TOKEN" "$SERVICE_URL/api/data")
TENANT_HEADER=$(echo "$HEADERS" | grep -i "x-tenant-id" | cut -d: -f2 | xargs)

if [ -n "$TENANT_HEADER" ]; then
  echo -e "${GREEN}✓ X-Tenant-ID header present: $TENANT_HEADER${NC}"
else
  echo -e "${YELLOW}⚠ X-Tenant-ID header not found${NC}"
fi
echo ""

# Summary
echo -e "${GREEN}=== Test Summary ===${NC}"
echo "Service URL: $SERVICE_URL"
echo "Tests completed. Check results above."
echo ""
echo "Next steps:"
echo "1. Verify all tests passed (green checkmarks)"
echo "2. Check Render logs for authentication flow"
echo "3. Test with different tenant tokens to verify isolation"