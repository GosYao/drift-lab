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

variable "kubernetes_version" {
  type        = string
  description = "Explicitly select a currently standard-supported EKS version in this region."
  validation {
    condition     = can(regex("^1\\.[0-9]+$", var.kubernetes_version))
    error_message = "Supply an explicit EKS version such as 1.xx; verify support first."
  }
}

variable "cluster_admin_principal_arn" {
  type        = string
  description = "Reviewed IAM role ARN for trusted cluster administration; never a PR-execution role."
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:role/", var.cluster_admin_principal_arn))
    error_message = "Set an IAM role ARN, not an STS session ARN."
  }
}

variable "expires_at" {
  type        = string
  description = "RFC3339 expiry tag. Advisory until the cleanup controller is implemented."
  validation {
    condition     = can(formatdate("YYYY-MM-DD", var.expires_at))
    error_message = "Use an RFC3339 timestamp."
  }
}

variable "instance_type" {
  type    = string
  default = "t3.medium"
}
