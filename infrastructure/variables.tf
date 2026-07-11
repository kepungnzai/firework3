variable "location" {
  description = "Azure region for all resources."
  type        = string
  default     = "australiaeast"
}

variable "environment" {
  description = "Deployment environment name (e.g. dev, prod). Used in resource names and tags."
  type        = string
}

variable "project" {
  description = "Short project prefix used to name resources."
  type        = string
  default     = "appt"
}

variable "aks_node_count" {
  description = "Number of nodes in the default AKS node pool."
  type        = number
  default     = 2
}

variable "aks_vm_size" {
  description = "VM size for AKS default node pool."
  type        = string
  default     = "Standard_D2s_v5"
}

variable "postgres_admin_login" {
  description = "Administrator login for the Postgres Flexible Server."
  type        = string
  default     = "apptadmin"
}

variable "postgres_sku_name" {
  description = "SKU name for the Postgres Flexible Server."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "ai_foundry_sku" {
  description = "SKU for the Azure AI Foundry (Cognitive Services) account."
  type        = string
  default     = "S0"
}

variable "tags" {
  description = "Common tags applied to all resources."
  type        = map(string)
  default = {
    application = "appointment-scheduler"
    managed_by  = "terraform"
  }
}