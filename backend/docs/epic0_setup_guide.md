# Epic 0: Multi-Tenant Setup Guide

## Frontegg + Render Environment Configuration

This guide covers setting up Frontegg authentication and deploying to Render with proper multi-tenant enforcement.

---

## Prerequisites

1. **Frontegg Account**
   - Sign up at [frontegg.com](https://frontegg.com)
   - Create a new application
   - Note your `Client ID` and `Client Secret`

2. **Render Account**
   - Sign up at [render.com](https://render.com)
   - Connect your GitHub repository

---

## Step 1: Configure Frontegg

### 1.1 Create Frontegg Application

1. Log in to [Frontegg Dashboard](https://portal.frontegg.com)
2. Navigate to **Settings** → **Applications**
3. Click **Create Application**
4. Configure:
   - **Application Name**: `AI Growth Analytics`
   - **Environment**: Production (or Development for testing)
   - **Allowed Redirect URIs**: 
     - `http://localhost:3000` (local dev)
     - `https://your-app.onrender.com` (production)

### 1.2 Get Credentials

1. After creating the application, you'll see:
   - **Client ID**: Copy this value
   - **Client Secret**: Copy this value (keep it secure!)

2. **JWKS Endpoint**: 
   - Frontegg automatically provides JWKS at:
   - `https://api.frontegg.com/.well-known/jwks.json`
   - The application will fetch this automatically

### 1.3 Configure JWT Claims

Frontegg JWT tokens include:
- `org_id` (or `organizationId`): Maps to `tenant_id` in our system
- `sub` (or `userId`): User identifier
- `roles`: Array of user roles
- `aud`: Audience (your Client ID)
- `iss`: Issuer (`https://api.frontegg.com`)

**Important**: Ensure your Frontegg organization structure matches your tenant model.

---

## Step 2: Configure Render Environment Variables

### 2.1 Add Secrets to Render Dashboard

After deploying via `render.yaml`, add these secrets to each service:

#### For `ai-growth-api` Service:

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Select your `ai-growth-api` service
3. Navigate to **Environment** tab
4. Add the following environment variables:

```bash
# Frontegg Authentication (REQUIRED)
FRONTEGG_CLIENT_ID=your-client-id-here
FRONTEGG_CLIENT_SECRET=your-client-secret-here

# Database (auto-injected by Render)
DATABASE_URL=<auto-injected>

# Redis (auto-injected by Render)
REDIS_URL=<auto-injected>

# Other secrets...
SHOPIFY_API_KEY=...
SHOPIFY_API_SECRET=...
OPENROUTER_API_KEY=...
ENCRYPTION_KEY=...
```

#### For `ai-growth-worker` Service:

Add the same environment variables as above.

### 2.2 Verify Environment Variables

After adding secrets:

1. Click **Manual Deploy** → **Deploy latest commit**
2. Wait for deployment to complete
3. Check service logs to verify:
   - No errors about missing `FRONTEGG_CLIENT_ID`
   - JWKS fetching is successful
   - JWT verification is working

---

## Step 3: Local Development Setup

### 3.1 Create `.env` File

Create `backend/.env`:

```bash
# Frontegg
FRONTEGG_CLIENT_ID=your-client-id
FRONTEGG_CLIENT_SECRET=your-client-secret

# Database (local)
DATABASE_URL=postgresql://user:password@localhost:5432/ai_growth_analytics

# Redis (local)
REDIS_URL=redis://localhost:6379

# Environment
ENV=development
```

### 3.2 Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 3.3 Run Application

```bash
uvicorn main:app --reload --port 8000
```

### 3.4 Test Authentication

1. Get a JWT token from your frontend (Frontegg SDK)
2. Make a request:

```bash
curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     http://localhost:8000/api/data
```

Expected response:
```json
{
  "tenant_id": "org-123",
  "user_id": "user-456",
  "data": "data-for-org-123"
}
```

---

## Step 4: Verify Multi-Tenant Enforcement

### 4.1 Test Cross-Tenant Protection

1. **Get Tenant A's JWT token**
2. **Get Tenant B's JWT token**

3. **Test 1: Tenant A accesses their data**
```bash
curl -H "Authorization: Bearer TENANT_A_TOKEN" \
     http://localhost:8000/api/data
```
Should return Tenant A's data.

4. **Test 2: Tenant A tries to access Tenant B's data**
```bash
# Even if tenant_id is in request body, it's ignored
curl -X POST \
     -H "Authorization: Bearer TENANT_A_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"tenant_id": "tenant-b-org"}' \
     http://localhost:8000/api/data
```
Should still return Tenant A's data (tenant_id from JWT, not body).

5. **Test 3: Missing token**
```bash
curl http://localhost:8000/api/data
```
Should return `403 Forbidden`.

### 4.2 Run Automated Tests

```bash
cd backend
pytest src/tests/platform/test_tenant_isolation.py -v
```

All tests should pass, especially:
- `test_tenant_a_cannot_access_tenant_b_data`
- `test_tenant_b_cannot_access_tenant_a_data`
- `test_repository_ignores_tenant_id_from_entity_data`

---

## Step 5: Database Schema Setup

### 5.1 Add tenant_id to All Tables

Every table must have a `tenant_id` column:

```sql
-- Example migration
ALTER TABLE analytics_events 
ADD COLUMN tenant_id VARCHAR(255) NOT NULL;

CREATE INDEX idx_analytics_events_tenant_id 
ON analytics_events(tenant_id);

-- Repeat for all tables
```

### 5.2 Verify Indexes

Ensure all `tenant_id` columns are indexed for performance:

```sql
-- Check existing indexes
SELECT 
    tablename, 
    indexname 
FROM pg_indexes 
WHERE indexname LIKE '%tenant_id%';
```

---

## Step 6: Monitoring & Logging

### 6.1 Structured Logging

All logs include `tenant_id` for audit trails:

```python
logger.info("Request processed", extra={
    "tenant_id": tenant_context.tenant_id,
    "user_id": tenant_context.user_id,
    "path": request.url.path
})
```

### 6.2 Monitor for Violations

Set up alerts for:
- `TenantIsolationError` exceptions
- JWT verification failures
- Missing tenant context errors

---

## Troubleshooting

### Issue: "Missing or invalid authorization token"

**Cause**: JWT token not provided or invalid format.

**Solution**:
1. Verify frontend is sending `Authorization: Bearer <token>` header
2. Check token is not expired
3. Verify token is from correct Frontegg environment

### Issue: "Token missing organization identifier"

**Cause**: JWT payload doesn't contain `org_id` or `organizationId`.

**Solution**:
1. Verify Frontegg organization is properly configured
2. Check JWT payload structure
3. Ensure user is assigned to an organization

### Issue: "No matching signing key found in JWKS"

**Cause**: JWKS fetch failed or key rotation occurred.

**Solution**:
1. Check network connectivity to `https://api.frontegg.com`
2. Verify `FRONTEGG_CLIENT_ID` is correct
3. JWKS cache will refresh automatically (1 hour TTL)

### Issue: Cross-tenant data access

**Cause**: Repository not using `BaseRepository` or tenant_id not enforced.

**Solution**:
1. Ensure all repositories extend `BaseRepository`
2. Verify `_get_tenant_column_name()` returns correct column name
3. Check that all queries use `_enforce_tenant_scope()`

---

## Security Checklist

- [ ] `FRONTEGG_CLIENT_ID` and `FRONTEGG_CLIENT_SECRET` set in Render
- [ ] All environment variables added to both API and Worker services
- [ ] Services redeployed after adding secrets
- [ ] JWT verification working (check logs)
- [ ] Cross-tenant tests passing
- [ ] All database tables have `tenant_id` column
- [ ] All `tenant_id` columns are indexed
- [ ] Repository methods require `tenant_id` parameter
- [ ] No `tenant_id` accepted from request body/query
- [ ] Structured logging includes `tenant_id` on all requests

---

## Next Steps

1. **Implement tenant-specific features** using `get_tenant_context(request)`
2. **Add tenant-scoped queries** using `BaseRepository` subclasses
3. **Set up monitoring** for tenant isolation violations
4. **Document tenant-specific API endpoints** in API docs

---

## References

- [Frontegg Documentation](https://docs.frontegg.com)
- [Render Environment Variables](https://render.com/docs/environment-variables)
- [JWT Best Practices](https://datatracker.ietf.org/doc/html/rfc8725)