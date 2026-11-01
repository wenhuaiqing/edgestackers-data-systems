# Azure deployment for the Edge Stackers data systems demo.
#
# Smaller than it might be, on purpose: the data is built inside the image
# and verified against pinned digests, so there is no database server, no
# blob store and no warehouse to pay for at rest. What remains:
#   - Container Apps, consumption plan, scale to zero (the free grant covers idle)
#   - public images on GitHub Container Registry (free; no registry at rest)
#   - Key Vault for the model key and the write token, read by that identity
#   - Log Analytics and a monthly budget alert
#
# State is local: one operator, one portfolio deployment.

terraform {
  required_version = ">= 1.7"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}
