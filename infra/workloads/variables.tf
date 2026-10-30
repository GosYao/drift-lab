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

variable "cluster_name" {
  type    = string
  default = "drift-lab"
}

variable "application_image" {
  type        = string
  description = "Published preview image by immutable digest. No image is built or published automatically."
  validation {
    condition     = can(regex("@sha256:[a-f0-9]{64}$", var.application_image))
    error_message = "Use an image reference ending in @sha256:<64 lowercase hex characters>."
  }
}
