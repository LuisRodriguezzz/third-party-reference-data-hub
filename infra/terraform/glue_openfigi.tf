# OpenFIGI: un job de Glue que pregunta a la API de OpenFIGI por los ISIN de acciones de EE. UU.
# de silver.gleif_isin_lei y deja la foto en silver.openfigi_tickers (lo crudo, en landing).

locals {
  # La clave de la API. El parámetro se creó a mano en SSM (SecureString): Terraform solo
  # conoce su nombre. Un data "aws_ssm_parameter" guardaría el valor de la clave en el state.
  openfigi_key_param = "/refhub/openfigi_api_key"
}

# Sus permisos: los de glue_base más leer una tabla de silver, escribir otra, guardar lo crudo
# en landing y leer la clave.
data "aws_iam_policy_document" "glue_openfigi" {
  source_policy_documents = [data.aws_iam_policy_document.glue_base.json]

  statement {
    sid       = "EscribirLandingOpenfigi" # las respuestas crudas de cada corrida
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/landing/openfigi/*"]
  }

  statement {
    sid       = "LeerIsinLei" # solo leer: de acá salen los ISIN que se preguntan
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/silver/gleif_isin_lei/*"]
  }

  statement {
    sid       = "EscribirSilver" # los archivos de datos y de metadatos de Iceberg, solo de su tabla
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/silver/openfigi_tickers/*"]
  }

  statement {
    sid     = "CatalogoLeer" # ver la base y las dos tablas
    actions = ["glue:GetDatabase", "glue:GetTable"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.silver.name}/gleif_isin_lei",
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.silver.name}/openfigi_tickers",
    ]
  }

  statement {
    sid     = "CatalogoEscribir" # crear y actualizar solo su tabla
    actions = ["glue:CreateTable", "glue:UpdateTable"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.silver.name}/openfigi_tickers",
    ]
  }

  # Leer la clave, y solo esa. No hace falta kms:Decrypt: el parámetro está cifrado con la clave
  # administrada aws/ssm, cuya política ya deja descifrar a cualquier rol de la cuenta que pida
  # el parámetro a través de SSM (condición kms:ViaService). Con una clave propia sí haría falta.
  statement {
    sid       = "LeerClaveOpenfigi"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${data.aws_region.actual.region}:${local.account_id}:parameter${local.openfigi_key_param}"]
  }
}

module "glue_openfigi" {
  source = "./modules/glue_job"

  nombre          = "openfigi"
  environment     = var.environment
  script_location = "${local.artifacts}/glue/openfigi_silver.py"
  timeout         = 30 # unos 770 pedidos de 100 ISIN; probado: menos de 1 s cada uno
  permisos_json   = data.aws_iam_policy_document.glue_openfigi.json

  # Sin --FULL_REFRESH: cada corrida ya es una foto completa nueva.
  argumentos = merge(local.glue_common_args, {
    "--datalake-formats"   = "iceberg"
    "--conf"               = local.iceberg_conf
    "--DATA_BUCKET"        = aws_s3_bucket.data.bucket
    "--SILVER_DB"          = aws_glue_catalog_database.silver.name
    "--OPENFIGI_KEY_PARAM" = local.openfigi_key_param
  })

  depends_on = [aws_cloudwatch_log_group.glue_output, aws_cloudwatch_log_group.glue_error]
}
