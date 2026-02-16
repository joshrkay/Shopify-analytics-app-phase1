locals {
  db_internal_connection_string = nonsensitive(render_postgres.shopify_analytics_db.connection_info.internal_connection_string)
  db_host                       = split(":", split("@", local.db_internal_connection_string)[1])[0]
}

output "api_service_url" {
  description = "Public URL of the Shopify Analytics API service"
  value       = render_web_service.shopify_analytics_api.url
}

output "database_host" {
  description = "Database host extracted from the non-sensitive portion of the connection string"
  value       = local.db_host
}

output "region" {
  description = "Render region used for core services"
  value       = var.region
}
