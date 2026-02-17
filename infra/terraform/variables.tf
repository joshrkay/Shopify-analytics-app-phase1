variable "render_api_key" {
  description = "Render API key from dashboard"
  type        = string
  sensitive   = true
}

variable "render_owner_id" {
  description = "Render owner/team ID"
  type        = string
}

variable "database_name" {
  description = "Primary PostgreSQL database name"
  type        = string
  default     = "shopify_analytics"
}

variable "database_user" {
  description = "Primary PostgreSQL database user"
  type        = string
  default     = "shopify_analytics_user"
}

variable "region" {
  description = "Render region for API and Postgres"
  type        = string
  default     = "oregon"
}

variable "clerk_frontend_api" {
  description = "Clerk frontend API URL/domain"
  type        = string
  sensitive   = true
}

variable "clerk_secret_key" {
  description = "Clerk secret key"
  type        = string
  sensitive   = true
}

variable "clerk_webhook_secret" {
  description = "Clerk webhook signing secret"
  type        = string
  sensitive   = true
}

variable "vite_clerk_publishable_key" {
  description = "Vite Clerk publishable key"
  type        = string
  sensitive   = true
}

variable "shopify_api_key" {
  description = "Shopify API key"
  type        = string
  sensitive   = true
}

variable "shopify_api_secret" {
  description = "Shopify API secret"
  type        = string
  sensitive   = true
}

variable "shopify_billing_return_url" {
  description = "Shopify billing callback URL"
  type        = string
  default     = "https://shopify-analytics-app-phase1.onrender.com/api/billing/callback"
}

variable "openrouter_api_key" {
  description = "OpenRouter API key"
  type        = string
  sensitive   = true
}

variable "encryption_key" {
  description = "Encryption key for secrets at rest"
  type        = string
  sensitive   = true
}

variable "cors_origins" {
  description = "Comma-separated CORS origins"
  type        = string
  default     = "https://shopify-analytics-app-phase1.onrender.com"
}

variable "do_token" {
  description = "DigitalOcean API token"
  type        = string
  sensitive   = true
}

variable "do_region" {
  description = "Default DigitalOcean region for future resources"
  type        = string
  default     = "nyc3"
}

variable "do_droplet_size" {
  description = "Default DigitalOcean droplet size for future resources"
  type        = string
  default     = "s-2vcpu-4gb"
}
