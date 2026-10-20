# One container app, two containers in the same replica: nginx (the only
# ingress: SPA, proxy, security headers) and the FastAPI backend on
# 127.0.0.1:8000. No internal ingress and no second Envoy, so a cold start is
# one activation.

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${var.prefix}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id

  lifecycle {
    ignore_changes = [workload_profile]
  }
}

resource "azurerm_container_app" "app" {
  name                         = "app"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  # The first revision pulls straight away; without the grants in place it
  # fails with an error that looks like a missing image.
  depends_on = [azurerm_role_assignment.acr_pull, azurerm_role_assignment.kv_app_read]

  lifecycle {
    ignore_changes = [workload_profile_name]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  ingress {
    external_enabled = true
    target_port      = 80
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  secret {
    name                = "demo-write-token"
    key_vault_secret_id = azurerm_key_vault_secret.write_token.id
    identity            = azurerm_user_assigned_identity.app.id
  }
  secret {
    name                = "llm-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.llm_api_key.id
    identity            = azurerm_user_assigned_identity.app.id
  }

  template {
    min_replicas = var.min_replicas
    # One replica: the demo's state - approvals, the audit log, rate limits -
    # lives in that replica's working copy of the database.
    max_replicas = 1

    container {
      name   = "frontend"
      image  = "${azurerm_container_registry.main.login_server}/edgestackers/frontend:${var.image_tag}"
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name  = "BACKEND_UPSTREAM"
        value = "127.0.0.1:8000"
      }
    }

    container {
      name   = "backend"
      image  = "${azurerm_container_registry.main.login_server}/edgestackers/backend:${var.image_tag}"
      # Approving a contract change re-runs the week in memory.
      cpu    = 1.0
      memory = "2Gi"

      readiness_probe {
        transport               = "HTTP"
        port                    = 8000
        path                    = "/health"
        interval_seconds        = 5
        timeout                 = 3
        failure_count_threshold = 12
        success_count_threshold = 1
      }

      env {
        name  = "LLM_BASE_URL"
        value = "https://generativelanguage.googleapis.com/v1beta/openai/"
      }
      env {
        name        = "LLM_API_KEY"
        secret_name = "llm-api-key"
      }
      env {
        name  = "LLM_CHAT_MODEL"
        value = var.gemini_chat_model
      }
      env {
        name  = "LLM_FALLBACK_MODEL"
        value = var.gemini_fallback_model
      }
      env {
        name        = "DEMO_WRITE_TOKEN"
        secret_name = "demo-write-token"
      }
    }
  }
}
