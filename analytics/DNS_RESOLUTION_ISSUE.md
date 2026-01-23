# DNS Resolution Issue - Troubleshooting Guide

## Current Problem

The Render database hostname cannot be resolved:
```
dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com
```

Error: `could not translate host name to address: nodename nor servname provided, or not known`

## This is a DNS/Network Issue

The hostname cannot be resolved by your system's DNS. This is **not** a dbt or database configuration issue.

## Possible Causes & Solutions

### 1. VPN or Network Restrictions

**Check:**
- Are you connected to a VPN? Try disconnecting
- Are you on a corporate network? Try a different network (mobile hotspot, home network)
- Is there a firewall blocking DNS queries?

**Solution:** Disconnect VPN or try from a different network

### 2. DNS Server Issues

**Check:**
- Can you resolve other hostnames? Try: `ping google.com`
- Are you using custom DNS servers?

**Solution:** 
- Try using Google DNS (8.8.8.8) or Cloudflare DNS (1.1.1.1)
- On macOS: System Settings → Network → DNS → Add 8.8.8.8

### 3. Hostname is Internal-Only

**Check:**
- In Render Dashboard, is there an "External Database URL" that's different?
- Some Render databases have separate internal/external hostnames

**Solution:** Use the External Database URL from Render dashboard

### 4. IP Address Directly

**Check:**
- Does Render dashboard show the database IP address?
- Can you use IP instead of hostname?

**Solution:** If IP is available, update `.env`:
```bash
DB_HOST=<database-ip-address>
```

## Quick Tests

### Test 1: Check DNS Resolution
```bash
nslookup dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com
```

### Test 2: Try Different DNS Server
```bash
nslookup dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com 8.8.8.8
```

### Test 3: Check Network Connectivity
```bash
ping google.com  # Should work
ping dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com  # Currently fails
```

## Alternative: Use Render Shell/Console

If you can't resolve DNS locally, you can:

1. **Run dbt from Render Service:**
   - Use Render's shell/console feature
   - Connect from within Render's network (no DNS issues)
   - Use Internal Database URL

2. **Use Render's Database Console:**
   - Access database directly from Render dashboard
   - Run SQL queries there
   - Set up test data via console

## Next Steps

1. **Try different network** (disconnect VPN, use mobile hotspot)
2. **Check Render Dashboard** for External Database URL or IP address
3. **Change DNS servers** to 8.8.8.8 or 1.1.1.1
4. **Contact Render Support** if hostname should be publicly resolvable

## Current Configuration

- **Hostname**: `dpg-d5o4ho4oud1c73ccl4mg-a.oregon-postgres.render.com`
- **Port**: `5432`
- **Database**: `shopify_analytics_db_00ga`
- **User**: `shopify_analytics_db_00ga_user`
- **Your IP**: `72.221.26.33` (whitelisted)
- **SSL**: Enabled (`sslmode: require`)

---

**Status**: Configuration is correct, but DNS resolution is failing. This is a network/DNS issue, not a configuration problem.
