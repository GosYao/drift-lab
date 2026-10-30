variable "region" {
  type    = string
  default = "us-east-1"
}

variable "account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.account_id))
    error_message = "Set the dedicated sandbox AWS account ID."
  }
}

variable "name" {
  type    = string
  default = "drift-lab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,25}$", var.name))
    error_message = "Use a short lowercase project name."
  }
}

variable "github_oidc_subject" {
  type        = string
  description = "Exact subject for the protected control-repository environment; inspect GitHub's actual subject format."
  validation {
    condition     = startswith(var.github_oidc_subject, "repo:") && !strcontains(var.github_oidc_subject, "*") && strcontains(var.github_oidc_subject, ":environment:")
    error_message = "Use an exact repository/environment OIDC subject, not a wildcard."
  }
}

variable "existing_github_oidc_provider_arn" {
  type        = string
  default     = null
  description = "Reuse the account's existing GitHub provider instead of creating a duplicate."
}

variable "monthly_budget_usd" {
  type    = number
  default = 500
}
