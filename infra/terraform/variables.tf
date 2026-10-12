variable "alert_email" {
  description = "Mail que recibe las alertas de presupuesto. Va en terraform.tfvars, que NO se sube a git."
  type        = string
  sensitive   = true
}

variable "monthly_budget_usd" {
  description = "Tope mensual de gasto para las alertas."
  type        = number
  default     = 10
}

variable "environment" {
  description = "Ambiente del hub (dev, prod...). Va en el nombre de los recursos y en los tags."
  type        = string
  default     = "dev"
}

variable "refhub_version" {
  description = "Versión de refhub que usan la Lambda y los jobs de Glue. La publica el CI en artifacts/refhub/<versión>/."
  type        = string
  default     = "0.3.0"
}