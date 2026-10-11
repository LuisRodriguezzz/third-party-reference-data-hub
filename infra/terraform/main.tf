data "aws_caller_identity" "actual" {}

locals {
  account_id = data.aws_caller_identity.actual.account_id
}

# Un solo bucket para todas las capas: landing/, bronze/, silver/, gold/ son prefijos adentro.
resource "aws_s3_bucket" "data" {
  bucket = "refhub-data-${local.account_id}-${var.environment}"

}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  # Una subida que se cortó a la mitad queda invisible pero se cobra. Esto la limpia.
  rule {
    id     = "limpiar-subidas-incompletas"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }

  # Los resultados de Athena son descartables.
  rule {
    id     = "borrar-resultados-athena"
    status = "Enabled"

    filter {
      prefix = "athena-results/"
    }

    expiration {
      days = 7
    }
  }
  # Los temporales (el CSV descomprimido, archivos de trabajo de Glue) se borran solos al día.
  rule {
    id     = "borrar-temporales"
    status = "Enabled"

    filter {
      prefix = "tmp/"
    }

    expiration {
      days = 1
    }
  }

}

resource "aws_budgets_budget" "mensual" {
  name         = "refhub-mensual"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}