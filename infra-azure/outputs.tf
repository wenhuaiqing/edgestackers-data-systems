output "frontend_url" {
  description = "The public URL (managed TLS)."
  value       = "https://${azurerm_container_app.app.ingress[0].fqdn}"
}

output "acr_login_server" {
  description = "docker push target: <this>/edgestackers/{backend,frontend}:<tag>."
  value       = azurerm_container_registry.main.login_server
}

output "demo_write_token" {
  description = "Unlock writes in a browser: <frontend_url>/?write_token=<this>. Never put this link in an application."
  value       = random_password.write_token.result
  sensitive   = true
}
