# Troubleshooting Render Database Connection

## Current Issue

**DNS Resolution Error**: Cannot resolve hostname `dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com`

## Possible Solutions

### 1. Check Render Dashboard for Alternative Connection String

Render databases often provide **two connection strings**:

1. **Internal Database URL** - Only works from Render services
2. **External Database URL** - Works from your local machine

**Steps:**
1. Go to Render Dashboard → `shopify-analytics-db`
2. Look for **"Connections"** or **"Connection Info"** section
3. Check if there's an **"External Database URL"** that's different from what we're using
4. The external URL might have a different hostname format

### 2. Verify IP Whitelisting

Your current IP: **72.221.26.33**

**Check:**
1. Go to Render Dashboard → `shopify-analytics-db` → **"Inbound IP Rules"**
2. Verify that `72.221.26.33` is listed
3. If not, add it and wait 2-3 minutes

### 3. Try Using Direct IP Address (if available)

If Render provides the database IP address:
1. Get the IP from Render dashboard
2. Update `.env` file to use IP instead of hostname:
   ```bash
   DB_HOST=<database-ip-address>
   ```

### 4. Check Network/Firewall

**Possible issues:**
- Corporate firewall blocking DNS resolution
- VPN interfering with connection
- Network restrictions

**Try:**
- Disconnect VPN if connected
- Try from a different network
- Check if other Render services are accessible

### 5. Use Render's Internal Connection (if running from Render)

If you're running this from a Render service (not local), use the **Internal Database URL** instead.

## Next Steps

1. **Check Render Dashboard** for External Database URL
2. **Verify IP is whitelisted** (72.221.26.33)
3. **Try alternative connection string** if available
4. **Check network/VPN** settings

## Alternative: Test Connection from Render Service

If you have a Render service running, you can test the connection from there:
- The Internal Database URL should work from Render services
- You can run dbt commands from a Render shell/console

## Current Configuration

- **Host**: `dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com`
- **Port**: `5432`
- **Database**: `shopify_analytics_db_00ga`
- **User**: `shopify_analytics_db_00ga_user`
- **Your IP**: `72.221.26.33`

---

**Action Required**: Check Render Dashboard for External Database URL or alternative connection method.
