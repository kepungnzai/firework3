# Root infrastructure for the Appointment Scheduling Agent.
#
# Provisions the full AKS stack: container registry, AKS cluster (with workload
# identity), Postgres (system of record), Service Bus (agent queue), Key Vault
# (secrets), and an Azure AI Foundry account for the orchestration agent.
#
# NOTE: The platform team publishes reusable modules at
# git::ssh://git@ssh.dev.azure.com/v3/mmsgau/Common Platforms - Platform Engineering/mmsg.platform.terraform.modules/
# Swap the inline resources below for those modules where an equivalent exists.

locals {
  name_prefix = "${var.project}-${var.environment}"

  tags = merge(var.tags, {
    environment = var.environment
  })
}

resource "random_string" "suffix" {
  length  = 5
  special = false
  upper   = false
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name_prefix}"
  location = var.location
  tags     = local.tags
}

# --- Container registry ---
resource "azurerm_container_registry" "this" {
  name                = "acr${var.project}${var.environment}${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Standard"
  admin_enabled       = false
  tags                = local.tags
}

# --- AKS cluster ---
resource "azurerm_kubernetes_cluster" "this" {
  name                = "aks-${local.name_prefix}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  dns_prefix          = local.name_prefix

  default_node_pool {
    name       = "system"
    node_count = var.aks_node_count
    vm_size    = var.aks_vm_size
  }

  identity {
    type = "SystemAssigned"
  }

  workload_identity_enabled = true
  oidc_issuer_enabled       = true

  tags = local.tags
}

# Allow AKS to pull images from ACR.
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.this.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.this.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}

# --- Postgres (system of record) ---
resource "random_password" "postgres" {
  length  = 24
  special = true
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "psql-${local.name_prefix}-${random_string.suffix.result}"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  version                       = "16"
  administrator_login           = var.postgres_admin_login
  administrator_password        = random_password.postgres.result
  sku_name                      = var.postgres_sku_name
  storage_mb                    = 32768
  public_network_access_enabled = true
  zone                          = "1"
  tags                          = local.tags
}

resource "azurerm_postgresql_flexible_server_database" "appointments" {
  name      = "appointments"
  server_id = azurerm_postgresql_flexible_server.this.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# --- Service Bus (agent request queue) ---
resource "azurerm_servicebus_namespace" "this" {
  name                = "sb-${local.name_prefix}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Standard"
  tags                = local.tags
}

resource "azurerm_servicebus_queue" "appointment_requests" {
  name         = "appointment-requests"
  namespace_id = azurerm_servicebus_namespace.this.id

  dead_lettering_on_message_expiration = true
  max_delivery_count                   = 5
}

# --- Key Vault (secrets) ---
data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "this" {
  name                       = "kv-${var.project}${var.environment}${random_string.suffix.result}"
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = false
  soft_delete_retention_days = 7
  enable_rbac_authorization  = true
  tags                       = local.tags
}

# --- Azure AI Foundry (agent) ---
resource "azurerm_cognitive_account" "ai_foundry" {
  name                = "aif-${local.name_prefix}-${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  kind                = "AIServices"
  sku_name            = var.ai_foundry_sku
  tags                = local.tags
}