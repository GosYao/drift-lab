terraform {
  required_version = ">= 1.10, < 2.0"
  backend "s3" {
    key          = "lab/workloads/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.38"
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
    }
  }
}

data "aws_eks_cluster" "lab" {
  name = var.cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.lab.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.lab.certificate_authority[0].data)
  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", var.cluster_name, "--region", var.region]
  }
}
