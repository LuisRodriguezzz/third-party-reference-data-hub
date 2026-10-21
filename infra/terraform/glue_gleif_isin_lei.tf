# ISIN↔LEI: un job de Glue que lleva el último archivo de landing a silver.gleif_isin_lei,
# con su contrato y su cuarentena. Es una foto completa: no pasa por bronze.

# Sus permisos: los de glue_base más leer su carpeta de landing y escribir silver.
data "aws_iam_policy_document" "glue_gleif_isin_lei" {
  source_policy_documents = [data.aws_iam_policy_document.glue_base.json]

  statement {
    sid       = "LeerLandingIsinLei" # solo leer: silver nunca modifica landing
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/landing/gleif_isin_lei/*"]
  }

  statement {
    sid       = "EscribirSilver" # los archivos de datos y de metadatos de Iceberg
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/silver/*"]
  }

  statement {
    sid     = "CatalogoSilver" # ver, crear y actualizar tablas, solo en la base silver
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.silver.name}/*",
    ]
  }
}

module "glue_gleif_isin_lei" {
  source = "./modules/glue_job"

  nombre          = "gleif-isin-lei"
  environment     = var.environment
  script_location = "${local.artifacts}/glue/gleif_isin_lei_silver.py"
  timeout         = 30 # 9,3 millones de filas de dos columnas
  permisos_json   = data.aws_iam_policy_document.glue_gleif_isin_lei.json

  argumentos = merge(local.glue_common_args, {
    "--datalake-formats" = "iceberg"
    "--conf"             = local.iceberg_conf
    "--DATA_BUCKET"      = aws_s3_bucket.data.bucket
    "--SILVER_DB"        = aws_glue_catalog_database.silver.name
    "--FULL_REFRESH"     = "false" # a mano, "true" recalcula la tabla entera (ADR 0007)
  })

  depends_on = [aws_cloudwatch_log_group.glue_output, aws_cloudwatch_log_group.glue_error]
}
