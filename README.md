# Shopify Analytics App

Multi-tenant Shopify embedded SaaS application for analytics and insights.

## Tech Stack

- **Backend**: FastAPI (Python)
- **Frontend**: React
- **Database**: PostgreSQL
- **Queue/Cache**: Redis
- **Deployment**: Render (one-click blueprint)
- **CI/CD**: GitHub Actions

## Deployment via Render Blueprint

This application uses Render's Blueprint feature for one-click deployment of the entire stack.

### Prerequisites

1. A [Render](https://render.com) account
2. GitHub repository connected to Render
3. All required secrets (see below)

### One-Click Deployment

1. **Connect Repository to Render**
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Click "New +" → "Blueprint"
   - Connect your GitHub repository
   - Select the repository containing this `render.yaml`

2. **Deploy Blueprint**
   - Render will automatically detect `render.yaml`
   - Click "Apply" to create all services:
     - `shopify-analytics-api` (Web API)
     - `shopify-analytics-worker` (Background workers)
     - `shopify-analytics-reconcile-subscriptions` (Cron job)
     - `shopify-analytics-db` (PostgreSQL database)
     - `shopify-analytics-redis` (Redis instance)

3. **Configure Secrets**
   After the initial deployment, you **must** add secrets via the Render dashboard:
   
   **For `shopify-analytics-api` service:**
   - Go to the service → "Environment" tab
   - Add the following environment variables:
     - `FRONTEGG_CLIENT_ID` - Your Frontegg client ID
     - `FRONTEGG_CLIENT_SECRET` - Your Frontegg client secret
     - `SHOPIFY_API_KEY` - Your Shopify API key
     - `SHOPIFY_API_SECRET` - Your Shopify API secret
     - `OPENROUTER_API_KEY` - Your OpenRouter API key
     - `ENCRYPTION_KEY` - Your encryption key for secrets
   
   **For `shopify-analytics-worker` service:**
   - Add the same environment variables as above
   
   **For `shopify-analytics-reconcile-subscriptions` cron job:**
   - Add the same environment variables as above

4. **Redeploy After Adding Secrets**
   - After adding secrets to each service, click "Manual Deploy" → "Deploy latest commit"
   - This ensures services start with the correct environment variables
   - Services will automatically restart with new secrets

### Service Details

- **Web API**: FastAPI application running on port 8000 (auto-configured by Render)
- **Worker**: Background job processor for async tasks
- **Cron Job**: Runs hourly to reconcile subscriptions
- **Database**: PostgreSQL 15 (standard plan)
- **Redis**: Starter plan for caching and queue management

### Health Checks

The API service includes a health check endpoint at `/health` that Render monitors automatically.

### Branch-Based Deployments

- **Production**: Deploys from `main` branch (auto-deploy enabled)
- **Staging**: To add staging, create a separate service in `render.yaml` with `branch: staging`

### Manual Redeployment

If you need to redeploy after adding secrets or making changes:

1. Go to the service in Render dashboard
2. Click "Manual Deploy" → "Deploy latest commit"
3. Wait for build to complete (typically 2-5 minutes)

### Troubleshooting

- **Build failures**: Check Dockerfile paths and ensure `backend/` directory exists
- **Service won't start**: Verify all secrets are set in Environment tab
- **Database connection errors**: Ensure `DATABASE_URL` is auto-injected (check service dependencies)
- **Redis connection errors**: Ensure `REDIS_URL` is auto-injected from Redis service

### Local Development

See individual service READMEs for local development setup.