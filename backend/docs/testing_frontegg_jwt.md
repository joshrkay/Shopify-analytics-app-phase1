# Testing Frontegg JWT in Deployed Render Environment

This guide covers how to test and verify Frontegg JWT authentication in your deployed Render environment.

---

## Prerequisites

1. **Render service deployed** and running
2. **Frontegg credentials** configured in Render environment variables
3. **Frontegg application** set up with your frontend/client

---

## Step 1: Get Your Render Service URL

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Select your `ai-growth-api` (or `shopify-analytics-api`) service
3. Copy the service URL (e.g., `https://ai-growth-api.onrender.com`)

---

## Step 2: Get a Frontegg JWT Token

You have several options to get a valid JWT token:

### Option A: From Your Frontend Application

If you have a React/Next.js frontend using Frontegg SDK:

```javascript
// In your frontend code
import { useAuth } from '@frontegg/react';

function MyComponent() {
  const { accessToken } = useAuth();
  
  // Log the token to console (for testing only!)
  console.log('Frontegg JWT:', accessToken);
  
  // Or copy to clipboard
  navigator.clipboard.writeText(accessToken);
}
```

### Option B: From Browser DevTools

1. Open your frontend application in browser
2. Open DevTools (F12) → Application/Storage tab
3. Look for Frontegg token in:
   - Local Storage: `frontegg-accessToken` or similar
   - Session Storage: Check Frontegg keys
   - Cookies: Look for Frontegg-related cookies

### Option C: Direct Frontegg API Call

If you have Frontegg credentials, you can authenticate directly:

```bash
# Replace with your Frontegg credentials
FRONTEGG_CLIENT_ID="your-client-id"
FRONTEGG_CLIENT_SECRET="your-client-secret"

# Get access token
curl -X POST https://api.frontegg.com/auth/vendor \
  -H "Content-Type: application/json" \
  -d "{
    \"clientId\": \"$FRONTEGG_CLIENT_ID\",
    \"secret\": \"$FRONTEGG_CLIENT_SECRET\"
  }"
```

### Option D: Decode Existing Token (Inspection Only)

To inspect a token without verifying it:

```bash
# Install jq for JSON formatting
# On Mac: brew install jq

# Decode JWT (base64 decode the payload)
echo "YOUR_JWT_TOKEN" | cut -d. -f2 | base64 -d | jq .
```

This shows the token payload including `org_id`, `sub`, `roles`, etc.

---

## Step 3: Test API Endpoints

### Test 1: Health Check (No Auth Required)

```bash
# Replace with your Render service URL
SERVICE_URL="https://ai-growth-api.onrender.com"

curl -X GET "$SERVICE_URL/health"
```

**Expected Response:**
```json
{
  "status": "healthy",
  "service": "ai-growth-api"
}
```

### Test 2: Protected Endpoint (With JWT)

```bash
# Replace with your actual token
JWT_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."

curl -X GET "$SERVICE_URL/api/data" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json"
```

**Expected Response:**
```json
{
  "tenant_id": "org-123",
  "user_id": "user-456",
  "data": "Sample data for tenant org-123",
  "message": "This endpoint demonstrates tenant isolation"
}
```

### Test 3: Create Data (Verify tenant_id from Body is Ignored)

```bash
curl -X POST "$SERVICE_URL/api/data" \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "different-tenant-id",
    "name": "Test Data"
  }'
```

**Expected Response:**
```json
{
  "tenant_id": "org-123",  // From JWT, NOT from body!
  "user_id": "user-456",
  "created": true,
  "message": "Data created with tenant_id from JWT context"
}
```

**Security Check:** Notice that `tenant_id` in the response matches the JWT's `org_id`, NOT the `tenant_id` from the request body.

### Test 4: Missing Token (Should Return 403)

```bash
curl -X GET "$SERVICE_URL/api/data"
```

**Expected Response:**
```json
{
  "detail": "Missing or invalid authorization token"
}
```

**Status Code:** `403 Forbidden`

### Test 5: Invalid Token (Should Return 403)

```bash
curl -X GET "$SERVICE_URL/api/data" \
  -H "Authorization: Bearer invalid-token-12345"
```

**Expected Response:**
```json
{
  "detail": "Invalid or expired token: ..."
}
```

**Status Code:** `403 Forbidden`

---

## Step 4: Verify Tenant Isolation

### Test Cross-Tenant Protection

1. **Get Token for Tenant A**
   ```bash
   TENANT_A_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." # Tenant A's token
   ```

2. **Get Token for Tenant B**
   ```bash
   TENANT_B_TOKEN="eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..." # Tenant B's token
   ```

3. **Tenant A Accesses Their Data**
   ```bash
   curl -X GET "$SERVICE_URL/api/data" \
     -H "Authorization: Bearer $TENANT_A_TOKEN"
   ```
   Should return Tenant A's data only.

4. **Tenant A Tries to Access Tenant B's Data**
   ```bash
   # Even if tenant_id is in body, it's ignored
   curl -X POST "$SERVICE_URL/api/data" \
     -H "Authorization: Bearer $TENANT_A_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"tenant_id": "tenant-b-org-id"}'
   ```
   Should STILL return Tenant A's data (tenant_id from JWT, not body).

---

## Step 5: Check Render Logs

### View Real-Time Logs

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Select your `ai-growth-api` service
3. Click **Logs** tab
4. Watch for:
   - JWT verification messages
   - Tenant context extraction
   - Any authentication errors

### Expected Log Messages

**Successful Request:**
```
INFO - Request authenticated
  tenant_id: org-123
  user_id: user-456
  path: /api/data
  method: GET
```

**Failed Request:**
```
WARNING - Request missing authorization token
  path: /api/data
  method: GET
```

**JWKS Fetch:**
```
INFO - Fetched fresh JWKS from Frontegg
  jwks_keys_count: 2
```

---

## Step 6: Debug Common Issues

### Issue: "Missing or invalid authorization token"

**Possible Causes:**
- Token not sent in `Authorization: Bearer` header
- Token is empty or malformed

**Solution:**
```bash
# Verify token format
echo "$JWT_TOKEN" | grep -E "^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"

# Check header format
curl -v "$SERVICE_URL/api/data" \
  -H "Authorization: Bearer $JWT_TOKEN" 2>&1 | grep -i authorization
```

### Issue: "Invalid token: no matching signing key"

**Possible Causes:**
- JWKS fetch failed
- Token signed with different key
- Frontegg environment mismatch (dev vs prod)

**Solution:**
1. Check Render logs for JWKS fetch errors
2. Verify `FRONTEGG_CLIENT_ID` matches token's `aud` claim
3. Ensure token is from correct Frontegg environment

### Issue: "Token missing organization identifier"

**Possible Causes:**
- JWT payload doesn't contain `org_id` or `organizationId`
- User not assigned to organization in Frontegg

**Solution:**
1. Decode token and check payload:
   ```bash
   echo "$JWT_TOKEN" | cut -d. -f2 | base64 -d | jq .
   ```
2. Verify `org_id` or `organizationId` exists in payload
3. Assign user to organization in Frontegg dashboard

### Issue: "Failed to fetch JWKS from Frontegg"

**Possible Causes:**
- Network connectivity issues
- Frontegg API down
- Incorrect `FRONTEGG_CLIENT_ID`

**Solution:**
1. Test JWKS endpoint directly:
   ```bash
   curl https://api.frontegg.com/.well-known/jwks.json
   ```
2. Check Render service can reach external APIs
3. Verify `FRONTEGG_CLIENT_ID` is set correctly in Render

---

## Step 7: Automated Testing Script

Create a test script for continuous testing:

```bash
#!/bin/bash
# test_jwt.sh

SERVICE_URL="${SERVICE_URL:-https://ai-growth-api.onrender.com}"
JWT_TOKEN="${JWT_TOKEN}"

if [ -z "$JWT_TOKEN" ]; then
  echo "Error: JWT_TOKEN environment variable not set"
  echo "Usage: JWT_TOKEN='your-token' ./test_jwt.sh"
  exit 1
fi

echo "Testing JWT authentication on $SERVICE_URL"
echo ""

# Test 1: Health check
echo "Test 1: Health check (no auth)"
curl -s "$SERVICE_URL/health" | jq .
echo ""

# Test 2: Protected endpoint
echo "Test 2: Protected endpoint (with JWT)"
curl -s "$SERVICE_URL/api/data" \
  -H "Authorization: Bearer $JWT_TOKEN" | jq .
echo ""

# Test 3: Missing token
echo "Test 3: Missing token (should fail)"
curl -s -w "\nHTTP Status: %{http_code}\n" \
  "$SERVICE_URL/api/data" | jq . 2>/dev/null || echo "Expected 403"
echo ""

# Test 4: Invalid token
echo "Test 4: Invalid token (should fail)"
curl -s -w "\nHTTP Status: %{http_code}\n" \
  "$SERVICE_URL/api/data" \
  -H "Authorization: Bearer invalid-token" | jq . 2>/dev/null || echo "Expected 403"
echo ""

echo "Testing complete!"
```

**Usage:**
```bash
chmod +x test_jwt.sh
JWT_TOKEN="your-token-here" ./test_jwt.sh
```

---

## Step 8: Verify Tenant Context in Response Headers

The API adds `X-Tenant-ID` header to responses:

```bash
curl -v "$SERVICE_URL/api/data" \
  -H "Authorization: Bearer $JWT_TOKEN" 2>&1 | grep -i "x-tenant-id"
```

**Expected Output:**
```
< X-Tenant-ID: org-123
```

This helps verify tenant context is correctly extracted and attached.

---

## Step 9: Test with Postman/Insomnia

### Postman Collection Setup

1. **Create New Request**
   - Method: `GET`
   - URL: `https://ai-growth-api.onrender.com/api/data`

2. **Add Authorization**
   - Type: `Bearer Token`
   - Token: `{{jwt_token}}` (use variable)

3. **Set Environment Variable**
   - Variable: `jwt_token`
   - Value: Your Frontegg JWT token

4. **Add Tests Tab**
   ```javascript
   pm.test("Status code is 200", function () {
       pm.response.to.have.status(200);
   });

   pm.test("Response contains tenant_id", function () {
       var jsonData = pm.response.json();
       pm.expect(jsonData).to.have.property('tenant_id');
   });

   pm.test("X-Tenant-ID header exists", function () {
       pm.expect(pm.response.headers.get("X-Tenant-ID")).to.exist;
   });
   ```

---

## Quick Reference: curl Commands

```bash
# Set variables
export SERVICE_URL="https://ai-growth-api.onrender.com"
export JWT_TOKEN="your-token-here"

# Health check
curl "$SERVICE_URL/health"

# Get data (authenticated)
curl -H "Authorization: Bearer $JWT_TOKEN" "$SERVICE_URL/api/data"

# Create data
curl -X POST \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "test"}' \
  "$SERVICE_URL/api/data"

# Test missing token (should fail)
curl "$SERVICE_URL/api/data"

# Test invalid token (should fail)
curl -H "Authorization: Bearer invalid" "$SERVICE_URL/api/data"
```

---

## Next Steps

1. ✅ Test health endpoint (no auth)
2. ✅ Test protected endpoints with valid JWT
3. ✅ Verify tenant isolation (cross-tenant protection)
4. ✅ Check Render logs for authentication flow
5. ✅ Set up monitoring/alerts for auth failures
6. ✅ Document your specific API endpoints

---

## Support

If you encounter issues:
1. Check Render service logs
2. Verify environment variables in Render dashboard
3. Test JWKS endpoint: `curl https://api.frontegg.com/.well-known/jwks.json`
4. Decode JWT payload to verify claims structure
5. Review `backend/docs/epic0_setup_guide.md` for setup details