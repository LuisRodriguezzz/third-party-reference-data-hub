terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      project    = "reference-data-hub"
      owner      = "luis"
      managed_by = "terraform"
      stack      = "bootstrap"
    }
  }
}

data "aws_caller_identity" "actual" {}

# El bucket donde va a vivir el state del proyecto. Se crea UNA vez y no se borra.
resource "aws_s3_bucket" "state" {
  bucket = "refhub-tfstate-${data.aws_caller_identity.actual.account_id}"

  lifecycle {
    prevent_destroy = true # si alguien corre destroy acá, Terraform se niega
  }
}

# Versionado: si un state se rompe, se puede volver a la versión anterior.
resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # cifrado de S3, gratis (no KMS, que cobra por clave)
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Las versiones viejas del state se borran solas a los 30 días.
resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "borrar-versiones-viejas"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}