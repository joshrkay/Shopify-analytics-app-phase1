# Airbyte Setup Guide

This guide covers setting up and configuring Airbyte Cloud for the AI Growth Analytics platform.

## Overview

Airbyte is deployed as infrastructure supporting data ingestion. It handles all data synchronization operations, decoupled from the core application logic. The `ai-growth-worker` service orchestrates syncs via the Airbyte API.

| Setting | Value |
|---------|-------|
| Deployment Model | Airbyte Cloud |
| Environment | Production |
| Base URL | `https://api.airbyte.com/v1` |

## Prerequisites

- Airbyte Cloud account ([sign up](https://cloud.airbyte.com))
- Workspace created in Airbyte Cloud
- Python 3.10+ (for validation script)

## Step-by-Step Setup

### 1. Create Airbyte Cloud Account

1. Go to [cloud.airbyte.com](https://cloud.airbyte.com)
2. Click **Sign Up** (or log in if you have an account)
3. Complete the registration process
4. Verify your email

### 2. Create a Workspace

1. After logging in, you'll be prompted to create an organization
2. Create a new workspace:
   - Click **Create Workspace**
   - Enter a name (e.g., "AI Growth Analytics Production")
   - Select your region (US recommended for lower latency)
3. Copy your **Workspace ID** from the URL:
   ```
   https://cloud.airbyte.com/workspaces/[WORKSPACE_ID]/...
   ```

### 3. Generate API Token

1. In Airbyte Cloud, go to **Settings** (gear icon)
2. Navigate to **API Tokens** or **Developer** section
3. Click **Generate Token**
4. Name the token (e.g., "ai-growth-worker-production")
5. Copy the token immediately - it won't be shown again
6. Store the token securely (see Security section below)

### 4. Configure Environment Variables

Create a `.env` file in the project root (copy from `.env.example`):

```bash
# Copy the example file
cp .env.example .env

# Edit with your values
nano .env  # or your preferred editor
```

Required Airbyte variables:

```bash
# Airbyte Configuration
AIRBYTE_BASE_URL=https://api.airbyte.com/v1
AIRBYTE_WORKSPACE_ID=your-workspace-id-here
AIRBYTE_API_TOKEN=your-api-token-here

# Worker Configuration
WORKER_AIRBYTE_SYNC_TIMEOUT_SECONDS=3600
WORKER_SYNC_CHECK_INTERVAL_SECONDS=30
WORKER_MAX_CONCURRENT_SYNCS=5
```

### 5. Validate Setup

Run the validation script to verify connectivity:

```bash
cd backend
python scripts/validate_airbyte.py
```

Expected output on success:
```
============================================================
 Airbyte Deployment Validation
============================================================

Checking environment variables...
✅ AIRBYTE_API_TOKEN: abc12345...xyz9
✅ AIRBYTE_WORKSPACE_ID: 6a588966-273f-46d6-89b7-846597667768
   AIRBYTE_BASE_URL: Using default

Initializing Airbyte client...
✅ Client initialized for workspace: 6a588966-273f-46d6-89b7-846597667768
✅ Using API base URL: https://api.airbyte.com/v1

--- Health Check ---
✅ Airbyte API is available
✅ Database status: OK

--- Connections ---
✅ Found 2 connection(s)
✅ Active connections: 2

============================================================
 Validation Summary
============================================================

✅ All validation checks passed!
```

### 6. Create Sources

In Airbyte Cloud UI:

1. Go to **Sources** in the left sidebar
2. Click **+ New Source**
3. Select your source type (e.g., **Shopify**)
4. Configure the connection:
   - **Name**: Descriptive name (e.g., "Production Shopify Store")
   - **Shop**: Your Shopify store URL
   - **Credentials**: OAuth or API token
   - **Start Date**: When to start syncing from
5. Click **Set up source**
6. Wait for the connection test to pass

### 7. Create Destinations

1. Go to **Destinations** in the left sidebar
2. Click **+ New Destination**
3. Select your destination type (e.g., PostgreSQL, BigQuery)
4. Configure connection details
5. Click **Set up destination**
6. Wait for the connection test to pass

### 8. Create Connections

1. Go to **Connections** in the left sidebar
2. Click **+ New Connection**
3. Select source and destination
4. Configure sync settings:
   - **Replication frequency**: How often to sync
   - **Destination namespace**: Where data lands
   - **Sync mode**: Full refresh or incremental
5. Select streams to sync
6. Click **Set up connection**
7. Trigger a manual sync to verify

## Security Best Practices

### Token Storage

**Development:**
- Store in `.env` file (gitignored)
- Never commit tokens to version control

**Production:**
- Use a secrets manager (AWS Secrets Manager, HashiCorp Vault)
- Inject at runtime via environment variables
- Rotate tokens periodically

### Access Control

- Generate separate tokens for each environment
- Use minimal permissions (workspace-scoped)
- Audit token usage regularly

### Network Security

- Airbyte Cloud uses HTTPS for all API calls
- No inbound network access required
- Outbound to `api.airbyte.com` port 443

## API Usage

### Python Client

```python
from src.integrations.airbyte import AirbyteClient

# Using environment variables (recommended)
async with AirbyteClient() as client:
    # Check health
    health = await client.check_health()
    print(f"Available: {health.available}")

    # List connections
    connections = await client.list_connections()
    for conn in connections:
        print(f"{conn.name}: {conn.status}")

    # Trigger sync
    job_id = await client.trigger_sync(connection_id="...")

    # Wait for completion
    result = await client.wait_for_sync(job_id)
    print(f"Synced {result.records_synced} records")
```

### Direct API Calls

Health check:
```bash
curl -H "Authorization: Bearer $AIRBYTE_API_TOKEN" \
     https://api.airbyte.com/v1/health
```

List connections:
```bash
curl -H "Authorization: Bearer $AIRBYTE_API_TOKEN" \
     "https://api.airbyte.com/v1/connections?workspaceIds=$AIRBYTE_WORKSPACE_ID"
```

Trigger sync:
```bash
curl -X POST \
     -H "Authorization: Bearer $AIRBYTE_API_TOKEN" \
     -H "Content-Type: application/json" \
     "https://api.airbyte.com/v1/connections/$CONNECTION_ID/sync"
```

## Monitoring

### Metrics to Track

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| Sync Duration | Time from start to completion | > 4 hours |
| Records Processed | Total rows synced | Varies by source |
| Success Rate | % of successful syncs | < 95% |
| Data Freshness | Time since last sync | > 48 hours |
| Error Rate | Failed syncs per time window | > 2 per day |

### Alerting Conditions

Set up alerts for:
- Sync failure after all retries exhausted
- Data freshness exceeding 48 hours
- API rate limit responses (429)
- Authentication failures (401, 403)

## Troubleshooting

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| 401 Unauthorized | Invalid/expired token | Regenerate token in Airbyte Cloud settings |
| 403 Forbidden | Token missing permissions | Verify token has workspace access |
| 429 Too Many Requests | Rate limit exceeded | Implement exponential backoff |
| Connection test fails | Network/auth issue | Test manually in Airbyte UI first |
| Sync stalled | Large data volume | Increase timeout, check logs |

### Debug Steps

1. **Verify environment variables:**
   ```bash
   python scripts/validate_airbyte.py
   ```

2. **Check Airbyte Cloud UI:**
   - Go to the connection
   - Click on **Logs** tab
   - Review recent sync attempts

3. **Test API connectivity:**
   ```bash
   curl -I -H "Authorization: Bearer $AIRBYTE_API_TOKEN" \
        https://api.airbyte.com/v1/health
   ```

4. **Check worker logs:**
   ```bash
   # Render
   render logs shopify-analytics-worker

   # Local
   docker logs ai-growth-worker
   ```

### Getting Help

- [Airbyte Documentation](https://docs.airbyte.com/)
- [API Reference](https://reference.airbyte.com/)
- [Airbyte Status Page](https://status.airbyte.com/)
- [Community Slack](https://slack.airbyte.com/)

## Pre-Deployment Checklist

Before deploying to production, verify:

- [ ] Airbyte Cloud workspace created
- [ ] API token generated and stored securely
- [ ] Environment variables configured
- [ ] Source connection test passed
- [ ] Destination connection test passed
- [ ] At least one connection created
- [ ] Manual sync completed successfully
- [ ] Validation script passes
- [ ] Worker can reach API endpoint
- [ ] Monitoring/alerting configured

## References

- [Airbyte Cloud Documentation](https://docs.airbyte.com/)
- [API Reference](https://reference.airbyte.com/)
- [Connectors Catalog](https://docs.airbyte.com/integrations/)
- [Shopify Connector](https://docs.airbyte.com/integrations/sources/shopify)
