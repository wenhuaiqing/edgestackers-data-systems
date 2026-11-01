# A tripwire, not a cap: Azure budgets only notify. At rest this deployment is
# pennies of vault and logs, so AUD 3 is reached only by something unplanned,
# such as a replica left warm.
resource "azurerm_consumption_budget_resource_group" "main" {
  name              = "budget-${var.prefix}-monthly"
  resource_group_id = azurerm_resource_group.main.id
  amount            = 3
  time_grain        = "Monthly"

  time_period {
    start_date = "2026-10-01T00:00:00Z"
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThan"
    threshold_type = "Actual"
    contact_emails = [var.budget_alert_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThan"
    threshold_type = "Forecasted"
    contact_emails = [var.budget_alert_email]
  }

  lifecycle {
    ignore_changes = [time_period]
  }
}
