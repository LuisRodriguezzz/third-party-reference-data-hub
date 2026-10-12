# Silver: un job de Glue que aplica el contrato a bronze, manda lo que falla a cuarentena y
# deja en silver la última versión de cada LEI.

resource "aws_iam_role" "glue_gleif_silver" {
  name               = "refhub-glue-gleif-silver-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
}

data "aws_iam_policy_document" "glue_gleif_silver" {
  source_policy_documents = [data.aws_iam_policy_document.glue_base.json]

  statement {
    sid       = "LeerBronze" # solo leer: silver nunca modifica bronze
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/bronze/*"]
  }

  statement {
    sid       = "EscribirSilver"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/silver/*"]
  }

  statement {
    sid     = "CatalogoLeerBronze"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.bronze.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.bronze.name}/*",
    ]
  }

  statement {
    sid     = "CatalogoEscribirSilver"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.silver.name}/*",
    ]
  }
}

resource "aws_iam_role_policy" "glue_gleif_silver" {
  name   = "permisos-minimos"
  role   = aws_iam_role.glue_gleif_silver.id
  policy = data.aws_iam_policy_document.glue_gleif_silver.json
}

resource "aws_glue_job" "gleif_silver" {
  name              = "refhub-gleif-silver-${var.environment}"
  role_arn          = aws_iam_role.glue_gleif_silver.arn
  glue_version      = "5.1"
  worker_type       = "G.1X"
  number_of_workers = 2
  timeout           = 60
  max_retries       = 0

  command {
    name            = "glueetl"
    python_version  = "3"
    script_location = "${local.artifacts}/glue/gleif_silver.py" # el que publicó el CI
  }

  default_arguments = merge(local.glue_common_args, {
    "--datalake-formats" = "iceberg"
    "--conf"             = local.iceberg_conf
    "--BRONZE_DB"        = aws_glue_catalog_database.bronze.name
    "--SILVER_DB"        = aws_glue_catalog_database.silver.name
  })

  execution_property {
    max_concurrent_runs = 1
  }

  depends_on = [aws_cloudwatch_log_group.glue_output, aws_cloudwatch_log_group.glue_error]
}
