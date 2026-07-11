output "resource_group_name" {
  description = "Name of the resource group containing all resources."
  value       = azurerm_resource_group.this.name
}

output "acr_login_server" {
  description = "Login server hostname of the container registry (used by CI to push images)."
  value       = azurerm_container_registry.this.login_server
}

output "aks_cluster_name" {
  description = "Name of the AKS cluster (used by CI for `az aks get-credentials`)."
  value       = azurerm_kubernetes_cluster.this.name
}

output "aks_oidc_issuer_url" {
  description = "OIDC issuer URL of the AKS cluster, required for workload identity federation."
  value       = azurerm_kubernetes_cluster.this.oidc_issuer_url
}

output "postgres_fqdn" {
  description = "Fully qualified domain name of the Postgres Flexible Server."
  value       = azurerm_postgresql_flexible_server.this.fqdn
}

output "servicebus_namespace" {
  description = "Service Bus namespace hosting the appointment-requests queue."
  value       = azurerm_servicebus_namespace.this.name
}

output "key_vault_uri" {
  description = "URI of the Key Vault holding application secrets."
  value       = azurerm_key_vault.this.vault_uri
}

output "ai_foundry_endpoint" {
  description = "Endpoint of the Azure AI Foundry account for the orchestration agent."
  value       = azurerm_cognitive_account.ai_foundry.endpoint
}