# Render Deployment Checklist

## ⚠️ CRITICAL: Required Environment Variables

**BEFORE your service can start, you MUST set these environment variables in Render Dashboard:**

### Required for Service Startup (MUST SET IMMEDIATELY):
1. `FRONTEGG_CLIENT_ID` - Your Frontegg application Client ID
2. `FRONTEGG_CLIENT_SECRET` - Your Frontegg application Client Secret

**Without these, your service will fail to start with:**
```
ValueError: Missing required environment variables: ['FRONTEGG_CLIENT_ID', 'FRONTEGG_CLIENT_SECRET']
```

### How to Set Environment Variables in Render:

1. **Go to Render Dashboard**: https://dashboard.render.com
2. **Select your service**: `shopify-analytics-api`
3. **Click "Environment" tab** (left sidebar)
4. **Click "Add Environment Variable"**
5. **Add each variable:**
   - Key: `FRONTEGG_CLIENT_ID`
   - Value: Your Frontegg Client ID (from Frontegg Dashboard)
   - Click "Save Changes"
   - Repeat for `FRONTEGG_CLIENT_SECRET`
6. **After adding both variables, click "Manual Deploy" → "Deploy latest commit"**

### Where to Get Frontegg Credentials:

1. Go to [Frontegg Dashboard](https://portal.frontegg.com)
2. Navigate to **Settings** → **Applications**
3. Select your application
4. Copy:
   - **Client ID** → Use as `FRONTEGG_CLIENT_ID`
   - **Client Secret** → Use as `FRONTEGG_CLIENT_SECRET`

See `backend/docs/epic0_setup_guide.md` for detailed Frontegg setup instructions.

---

## Pre-Deployment Verification

### ✅ Repository Configuration
- [x] `render.yaml` exists in root directory
- [x] Dockerfiles in `docker/backend.Dockerfile` and `docker/worker.Dockerfile`
- [x] Branch set to `main` in render.yaml
- [x] Health check path: `/health`

### ✅ Code Ready
- [x] Health endpoint implemented at `/health`
- [x] Database connectivity checks
- [x] Environment variable validation
- [x] Startup logging (no secrets)
- [x] All tests passing

### ✅ Render Service Configuration

**For Blueprint Deployment:**
1. Go to Render Dashboard → New + → Blueprint
2. Connect repository: `joshrkay/Shopify-analytics-app`
3. **IMPORTANT**: Select branch: `main` (not feature branches)
4. Render will auto-detect `render.yaml`
5. Click **Apply** to create all services

**Verify Service Settings:**
- Branch: `main` ✓
- Dockerfile Path: `docker/backend.Dockerfile` ✓
- Docker Context: `.` (root) ✓
- Health Check Path: `/health` ✓

## Required Environment Variables

After services are created, add these in Render Dashboard:

### For `shopify-analytics-api`:
```
FRONTEGG_CLIENT_ID=<your-client-id>
FRONTEGG_CLIENT_SECRET=<your-client-secret>
SHOPIFY_API_KEY=<your-key>
SHOPIFY_API_SECRET=<your-secret>
OPENROUTER_API_KEY=<your-key>
LAUNCHDARKLY_SDK_KEY=<your-key>
```

### Auto-Injected (from render.yaml):
- `DATABASE_URL` - Auto-injected from `shopify-analytics-db`
- `REDIS_URL` - Auto-injected from `shopify-analytics-redis`
- `ENV=production` - Set automatically

## Deployment Steps

1. **Create Blueprint** (if not done)
   - Use branch: `main`
   - Render detects `render.yaml` automatically

2. **Add Environment Variables**
   - Go to each service → Environment tab
   - Add all required secrets
   - **DO NOT** commit secrets to code

3. **Manual Deploy**
   - After adding secrets, click **Manual Deploy**
   - Select **Deploy latest commit**
   - Watch build logs

4. **Verify Health**
   - Wait for deployment to complete
   - Check service URL: `https://your-service.onrender.com/health`
   - Should return 200 OK with health status

## Troubleshooting

### Issue: "don't have access to your repo"
**Fix**: Connect Render to GitHub in Account Settings → Connected Accounts

### Issue: "Dockerfile: no such file or directory"
**Fix**: 
- Check service branch is `main`
- Verify Dockerfile Path: `docker/backend.Dockerfile`
- Verify Docker Context: `.`

### Issue: Health check failing
**Fix**:
- Check `/health` endpoint is accessible
- Verify database connection (check DATABASE_URL)
- Check environment variables are set
- Review service logs

### Issue: Service won't start - "Missing required environment variables"
**Error Message:**
```
ValueError: Missing required environment variables: ['FRONTEGG_CLIENT_ID', 'FRONTEGG_CLIENT_SECRET']
```

**Fix (STEP-BY-STEP):**
1. **Go to Render Dashboard** → Select `shopify-analytics-api` service
2. **Click "Environment" tab** (left sidebar)
3. **Verify variables exist:**
   - Look for `FRONTEGG_CLIENT_ID` in the list
   - Look for `FRONTEGG_CLIENT_SECRET` in the list
4. **If missing, add them:**
   - Click "Add Environment Variable"
   - Key: `FRONTEGG_CLIENT_ID`
   - Value: Your Frontegg Client ID
   - Click "Save Changes"
   - Repeat for `FRONTEGG_CLIENT_SECRET`
5. **After adding, redeploy:**
   - Click "Manual Deploy" → "Deploy latest commit"
   - Wait for deployment to complete
6. **Verify in logs:**
   - Check logs for: "Environment variables validated"
   - Should NOT see: "Missing required environment variables"

**If you don't have Frontegg credentials yet:**
- Follow setup guide: `backend/docs/epic0_setup_guide.md`
- Create Frontegg application first
- Then add credentials to Render

### Issue: Service won't start (other causes)
**Fix**:
- Check all required env vars are set
- Verify DATABASE_URL is auto-injected
- Check startup logs for errors
- Ensure FRONTEGG_CLIENT_ID is set

## Post-Deployment Verification

- [ ] Health endpoint returns 200: `curl https://your-service.onrender.com/health`
- [ ] Database connectivity working (check logs)
- [ ] Environment variables loaded (check logs - no secrets shown)
- [ ] Auto-deploy working (push to main triggers deploy)
- [ ] All services created (API, Worker, DB, Redis, Cron)

## Service URLs

After deployment, you'll have:
- **API**: `https://shopify-analytics-api.onrender.com`
- **Health**: `https://shopify-analytics-api.onrender.com/health`
- **Worker**: Running in background
- **Database**: `shopify-analytics-db` (internal connection)
- **Redis**: `shopify-analytics-redis` (internal connection)

## Next Steps

1. Test health endpoint
2. Test JWT authentication
3. Monitor logs for any issues
4. Set up monitoring/alerts
5. Test auto-deploy (push to main)

## Support

- Render Docs: https://render.com/docs
- Blueprint Spec: https://render.com/docs/blueprint-spec
- Health Checks: https://render.com/docs/health-checks