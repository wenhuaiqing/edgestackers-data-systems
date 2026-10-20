resource "azurerm_resource_group" "main" {
  name     = "rg-${var.prefix}"
  location = var.location
}

resource "random_string" "suffix" {
  length  = 6
  lower   = true
  upper   = false
  special = false
}

# Container Apps logging. PerGB2018 includes 5 GB a month free.
resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${var.prefix}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

data "azurerm_client_config" "current" {}

# ---- identity, registry, vault ---------------------------------------------

resource "azurerm_user_assigned_identity" "app" {
  name                = "id-${var.prefix}-app"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
}

# Basic tier (about AUD 8 a month). The app pulls with its own identity, so no
# registry password exists to leak.
resource "azurerm_container_registry" "main" {
  name                = "acr${var.prefix}${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# The operator pushes from the laptop.
resource "azurerm_role_assignment" "acr_push_self" {
  scope                = azurerm_container_registry.main.id
  role_definition_name = "AcrPush"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_key_vault" "main" {
  name                       = "kv-${var.prefix}-${random_string.suffix.result}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  purge_protection_enabled   = false
}

resource "azurerm_role_assignment" "kv_admin_self" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Administrator"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "kv_app_read" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.app.principal_id
}

# Approvals, promotion and reset need this. The operator opens the site once
# with ?write_token=<value>; the plain link is read-only.
resource "random_password" "write_token" {
  length  = 32
  special = false
}

resource "azurerm_key_vault_secret" "write_token" {
  name         = "demo-write-token"
  value        = random_password.write_token.result
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.kv_admin_self]
}

# Key Vault refuses an empty secret, so an unset key is stored as a single
# space; the app strips it, finds no model, and says so on screen.
resource "azurerm_key_vault_secret" "llm_api_key" {
  name         = "llm-api-key"
  value        = var.gemini_api_key == "" ? " " : var.gemini_api_key
  key_vault_id = azurerm_key_vault.main.id
  depends_on   = [azurerm_role_assignment.kv_admin_self]
}
