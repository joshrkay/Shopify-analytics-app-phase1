resource "render_postgres" "shopify_analytics_db" {
  name = "shopify-analytics-app-phase1-db"

  plan    = "basic_256mb"
  region  = var.region
  version = "15"

  database_name = var.database_name
  database_user = var.database_user
}

resource "render_web_service" "shopify_analytics_api" {
  name   = "shopify-analytics-app-phase1-api"
  plan   = "starter"
  region = var.region

  health_check_path = "/health"

  runtime_source = {
    docker = {
      repo_url        = "https://github.com/joshrkay/Shopify-analytics-app-phase1"
      branch          = "main"
      auto_deploy     = true
      dockerfile_path = "./docker/backend.Dockerfile"
      context         = "."
    }
  }

  env_vars = {
    ENV = { value = "production" }

    DATABASE_URL = {
      value = render_postgres.shopify_analytics_db.connection_info.internal_connection_string
    }

    CLERK_FRONTEND_API           = { value = var.clerk_frontend_api }
    CLERK_SECRET_KEY             = { value = var.clerk_secret_key }
    CLERK_WEBHOOK_SECRET         = { value = var.clerk_webhook_secret }
    VITE_CLERK_PUBLISHABLE_KEY   = { value = var.vite_clerk_publishable_key }
    CORS_ORIGINS                 = { value = var.cors_origins }
    SHOPIFY_API_KEY              = { value = var.shopify_api_key }
    SHOPIFY_API_SECRET           = { value = var.shopify_api_secret }
    SHOPIFY_BILLING_RETURN_URL   = { value = var.shopify_billing_return_url }
    OPENROUTER_API_KEY           = { value = var.openrouter_api_key }
    ENCRYPTION_KEY               = { value = var.encryption_key }
  }
}
