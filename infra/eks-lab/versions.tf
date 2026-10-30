terraform {
  required_version = ">= 1.10, < 2.0"
  backend "s3" {
    key          = "lab/eks/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region              = var.region
  allowed_account_ids = [var.account_id]
  default_tags {
    tags = {
      Project   = "drift-lab"
      ManagedBy = "terraform"
      Lifecycle = "disposable"
      ExpiresAt = var.expires_at
    }
  }
}
