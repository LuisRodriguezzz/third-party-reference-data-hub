# Lo que comparten todos los jobs de Glue del hub: el paquete refhub, los logs y los permisos base.

locals {
  # El .whl de refhub en S3. Glue lo instala con pip antes de correr el script.
  refhub_whl = "s3://${aws_s3_bucket.data.bucket}/artifacts/refhub/${var.refhub_version}/refhub-${var.refhub_version}-py3-none-any.whl"

  # Con este prefijo, Glue escribe en <prefijo>/output (los print) y <prefijo>/error (Spark).
  glue_log_prefix = "/aws-glue/refhub-${var.environment}"

  # Parámetros que reciben todos los jobs del hub (cada job suma los suyos con merge).
  glue_common_args = {
    "--additional-python-modules" = local.refhub_whl                              # pip install del .whl
    "--custom-logGroup-prefix"    = local.glue_log_prefix                         # logs a NUESTROS grupos
    "--TempDir"                   = "s3://${aws_s3_bucket.data.bucket}/tmp/glue/" # temporales de Glue
    "--job-language"              = "python"
  }
}

# ---------------------------------------------------------------- 1. Logs con retención

# Los dos grupos que usa Glue 5.x cuando le das un prefijo propio. Creándolos antes, con
# retención, los logs no se guardan para siempre.
resource "aws_cloudwatch_log_group" "glue_output" {
  name              = "${local.glue_log_prefix}/output" # lo que imprimís con print()
  retention_in_days = 14
}

resource "aws_cloudwatch_log_group" "glue_error" {
  name              = "${local.glue_log_prefix}/error" # los logs de Spark y los errores
  retention_in_days = 14
}

# ---------------------------------------------------------------- 2. Permisos base

# QUIÉN puede usar los roles de los jobs: solo el servicio Glue.
data "aws_iam_policy_document" "glue_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

# QUÉ necesita cualquier job del hub. Cada job "hereda" esto y le suma lo suyo.
data "aws_iam_policy_document" "glue_base" {
  statement {
    sid     = "EscribirSusLogs"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      aws_cloudwatch_log_group.glue_output.arn, "${aws_cloudwatch_log_group.glue_output.arn}:*",
      aws_cloudwatch_log_group.glue_error.arn, "${aws_cloudwatch_log_group.glue_error.arn}:*",
    ]
  }

  statement {
    sid       = "LeerArtefactos" # el script y el .whl
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/artifacts/*"]
  }

  statement {
    sid       = "UsarTemporales" # tmp/glue/ (de Glue) y tmp/gleif/ (el CSV descomprimido)
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/tmp/*"]
  }

  statement {
    sid       = "ListarElBucket" # para recibir 404 (no existe) en vez de 403, como en el hito 3
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}