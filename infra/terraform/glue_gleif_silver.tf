# Silver: un job de Glue que aplica el contrato a bronze, manda lo que falla a cuarentena y
# deja en silver la última versión de cada LEI.

# Sus permisos: los de glue_base más leer bronze y escribir silver (archivos y catálogo).
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

module "glue_gleif_silver" {
  source = "./modules/glue_job"

  nombre          = "gleif-silver"
  environment     = var.environment
  script_location = "${local.artifacts}/glue/gleif_silver.py"
  timeout         = 60
  permisos_json   = data.aws_iam_policy_document.glue_gleif_silver.json

  argumentos = merge(local.glue_common_args, {
    "--datalake-formats" = "iceberg"
    "--conf"             = local.iceberg_conf
    "--BRONZE_DB"        = aws_glue_catalog_database.bronze.name
    "--SILVER_DB"        = aws_glue_catalog_database.silver.name
    "--FULL_REFRESH"     = "false" # a mano, "true" recalcula la tabla entera (ADR 0007)
  })

  depends_on = [aws_cloudwatch_log_group.glue_output, aws_cloudwatch_log_group.glue_error]
}
