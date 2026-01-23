# Quick Start: Render Database Setup

## 🚀 Fastest Way to Get Started

### Step 1: Get Your Render Database URL

1. Go to [Render Dashboard](https://dashboard.render.com)
2. Click on your database: **shopify-analytics-db**
3. Find **"External Database URL"** (for local development)
4. Copy the connection string (looks like: `postgresql://user:pass@host:port/database`)

### Step 2: Run Setup Script

```bash
cd analytics

# Paste your connection string here
export DATABASE_URL="postgresql://user:password@host:port/database"

# Run the setup script
./setup_render_db.sh
```

That's it! The script will:
- ✅ Parse your DATABASE_URL
- ✅ Create/update `.env` file
- ✅ Set all required environment variables
- ✅ Test the connection (if possible)

### Step 3: Verify Connection

```bash
# Load environment variables
source load_env.sh

# Test with dbt (if installed)
dbt debug
```

### Step 4: Run Your Models

```bash
# Load variables
source load_env.sh

# Run staging models
dbt run --select staging

# Run tests
dbt test --select staging
```

## 🔧 Troubleshooting

**"DATABASE_URL not found"**
- Make sure you've set the environment variable: `export DATABASE_URL="..."`
- Or add it to `.env` file: `DATABASE_URL=...`

**"Connection refused"**
- If using External URL: Whitelist your IP in Render dashboard
- If using Internal URL: Only works from Render services, not local

**"Authentication failed"**
- Double-check your credentials from Render dashboard
- Make sure password doesn't have unencoded special characters

## 📚 More Help

- Full guide: [RENDER_DB_SETUP.md](RENDER_DB_SETUP.md)
- General setup: [README.md](README.md)
- Configuration status: [DB_CONFIGURATION_STATUS.md](DB_CONFIGURATION_STATUS.md)
