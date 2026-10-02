terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive" # arma el zip con tu código
      version = "~> 2.8"
    }
  }



  backend "s3" {
    # bucket y key van en backend.hcl: dependen de la cuenta y del ambiente
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true # el lock es un archivo en S3; ya no hace falta DynamoDB (Terraform >= 1.10)
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      project    = "reference-data-hub"
      owner      = "luis"
      managed_by = "terraform"
      stack      = "hub-${var.environment}"
    }
  }
}
