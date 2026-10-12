# Bronze: un job de Glue (Spark + Iceberg) que pasa los zips de landing a la tabla bronze.

locals {
  # Configuración de Spark para usar Iceberg con el Glue Data Catalog (documentación de Glue).
  # Va en el parámetro --conf; join arma "a=1 --conf b=2 --conf c=3".
  iceberg_conf = join(" --conf ", [
    "spark.sql.extensions=org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions",
    "spark.sql.catalog.glue_catalog=org.apache.iceberg.spark.SparkCatalog",
    "spark.sql.catalog.glue_catalog.warehouse=s3://${aws_s3_bucket.data.bucket}/",
    "spark.sql.catalog.glue_catalog.catalog-impl=org.apache.iceberg.aws.glue.GlueCatalog",
    "spark.sql.catalog.glue_catalog.io-impl=org.apache.iceberg.aws.s3.S3FileIO",
    "spark.sql.session.timeZone=UTC",
  ])
}

# Sus permisos: los de glue_base más leer landing, escribir bronze y registrar sus tablas.
data "aws_iam_policy_document" "glue_gleif_bronze" {
  source_policy_documents = [data.aws_iam_policy_document.glue_base.json]

  statement {
    sid       = "LeerLandingGleif" # solo leer: bronze nunca modifica landing
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/landing/gleif/*"]
  }

  statement {
    sid       = "EscribirBronze" # los archivos de datos y de metadatos de Iceberg
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/bronze/*"]
  }

  statement {
    sid     = "CatalogoBronze" # ver y registrar tablas, solo en la base bronze
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.bronze.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.bronze.name}/*",
    ]
  }
}

module "glue_gleif_bronze" {
  source = "./modules/glue_job"

  nombre          = "gleif-bronze"
  environment     = var.environment
  script_location = "${local.artifacts}/glue/gleif_bronze.py"
  timeout         = 60 # el archivo completo son ~5 GB de CSV
  permisos_json   = data.aws_iam_policy_document.glue_gleif_bronze.json

  argumentos = merge(local.glue_common_args, {
    "--datalake-formats" = "iceberg" # Glue agrega las librerías de Iceberg
    "--conf"             = local.iceberg_conf
    "--DATA_BUCKET"      = aws_s3_bucket.data.bucket
    "--BRONZE_DB"        = aws_glue_catalog_database.bronze.name
  })

  depends_on = [aws_cloudwatch_log_group.glue_output, aws_cloudwatch_log_group.glue_error]
}

# Mismos recursos, otra dirección (ver glue_gleif_full.tf). Se pueden sacar después del apply.
moved {
  from = aws_iam_role.glue_gleif_bronze
  to   = module.glue_gleif_bronze.aws_iam_role.this
}

moved {
  from = aws_iam_role_policy.glue_gleif_bronze
  to   = module.glue_gleif_bronze.aws_iam_role_policy.this
}

moved {
  from = aws_glue_job.gleif_bronze
  to   = module.glue_gleif_bronze.aws_glue_job.this
}
