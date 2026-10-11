# Carga inicial: un job de Glue que baja el archivo completo de GLEIF a landing/ (una vez).

# ---------------------------------------------------------------- 1. El script, en S3

# Glue no lee tu disco: el script tiene que estar en S3. Terraform lo sube y, si lo cambiás,
# la huella (source_hash) cambia y el próximo plan muestra un ~ para subir la versión nueva.
resource "aws_s3_object" "glue_gleif_full" {
  bucket      = aws_s3_bucket.data.id
  key         = "artifacts/glue/gleif_full.py"
  source      = "${path.module}/../../glue/gleif_full.py"
  source_hash = filemd5("${path.module}/../../glue/gleif_full.py")
}

# ---------------------------------------------------------------- 2. Permisos del job

resource "aws_iam_role" "glue_gleif_full" {
  name               = "refhub-glue-gleif-full-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
}

data "aws_iam_policy_document" "glue_gleif_full" {
  # Todo lo de glue_base (logs, artefactos, temporales, listar)...
  source_policy_documents = [data.aws_iam_policy_document.glue_base.json]

  # ...más escribir en landing/gleif/, igual que la Lambda.
  statement {
    sid       = "EscribirLandingGleif"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/landing/gleif/*"]
  }
}

resource "aws_iam_role_policy" "glue_gleif_full" {
  name   = "permisos-minimos"
  role   = aws_iam_role.glue_gleif_full.id
  policy = data.aws_iam_policy_document.glue_gleif_full.json
}

# ---------------------------------------------------------------- 3. El job

resource "aws_glue_job" "gleif_full" {
  name              = "refhub-gleif-full-${var.environment}"
  role_arn          = aws_iam_role.glue_gleif_full.arn
  glue_version      = "5.1"  # Python 3.11: el que acepta refhub (>=3.11,<3.13)
  worker_type       = "G.1X" # 1 DPU por worker: 4 vCPU y 16 GB
  number_of_workers = 2      # el mínimo para un job de Spark
  timeout           = 30     # minutos: si se cuelga, Glue lo corta y deja de cobrar
  max_retries       = 0      # si falla, mirás el log antes de gastar otra corrida

  command {
    name            = "glueetl" # job de Spark (aunque este script no use Spark)
    python_version  = "3"
    script_location = "s3://${aws_s3_bucket.data.bucket}/${aws_s3_object.glue_gleif_full.key}"
  }

  # merge junta dos mapas: los parámetros comunes más los de este job.
  default_arguments = merge(local.glue_common_args, {
    "--DATA_BUCKET" = aws_s3_bucket.data.bucket
  })

  execution_property {
    max_concurrent_runs = 1 # nunca dos corridas a la vez
  }

  depends_on = [aws_cloudwatch_log_group.glue_output, aws_cloudwatch_log_group.glue_error]
}