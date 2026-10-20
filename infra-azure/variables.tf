variable "subscription_id" {
  description = "Subscription to deploy into. Named explicitly so a CLI logged into another subscription cannot receive this deployment by default."
  type        = string
}

variable "prefix" {
  description = "Short resource-name prefix (lowercase alphanumerics)."
  type        = string
  default     = "edgestackers"
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "australiaeast"
}

variable "image_tag" {
  description = "Tag for both images in the registry (the commit SHA)."
  type        = string
  default     = "latest"
}

variable "min_replicas" {
  description = "0 scales to zero when idle and costs almost nothing, at the price of a cold start of some seconds. 1 keeps a replica warm (roughly AUD 2 a day once the monthly free grant is used)."
  type        = number
  default     = 0
}

variable "budget_alert_email" {
  description = "Where the monthly cost alert goes."
  type        = string
}

variable "gemini_api_key" {
  description = "Google AI Studio key for the triage agent. Empty deploys without a model: the runbook answers and the page says so."
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_chat_model" {
  description = "Gemini model for triage. A Lite model: one triage is three to five sequential calls."
  type        = string
  default     = "gemini-3.5-flash-lite"
}

variable "gemini_fallback_model" {
  description = "Tried once when the primary answers 429 or 5xx. Free-tier quotas are per model."
  type        = string
  default     = "gemini-3.1-flash-lite"
}
