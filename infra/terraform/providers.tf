terraform {
  required_version = ">= 1.5.0"

  required_providers {
    render = {
      source  = "render-oss/render"
      version = "~> 1.0"
    }

    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }

  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "render" {
  api_key  = var.render_api_key
  owner_id = var.render_owner_id
}

provider "digitalocean" {
  token = var.do_token
}
