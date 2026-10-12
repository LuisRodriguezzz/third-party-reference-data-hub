# Carga inicial: un job de Glue que baja el archivo completo de GLEIF a landing/ (una vez).
# El script lo publica el CI en artifacts/refhub/<versión>/glue/, con el .whl.

# Sus permisos: todo lo de glue_base (logs, artefactos, temporales, listar)...
data "aws_iam_policy_document" "glue_gleif_full" {
  source_policy_documents = [data.aws_iam_policy_document.glue_base.json]

  # ...más escribir en landing/gleif/, igual que la Lambda.
  statement {
    sid       = "EscribirLandingGleif"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/landing/gleif/*"]
  }
}

module "glue_gleif_full" {
  source = "./modules/glue_job" # el rol, la política y el job, armados igual para todos

  nombre          = "gleif-full"
  environment     = var.environment
  script_location = "${local.artifacts}/glue/gleif_full.py" # el que publicó el CI
  timeout         = 30                                      # minutos: baja un zip de 480 MB
  permisos_json   = data.aws_iam_policy_document.glue_gleif_full.json

  # merge junta dos mapas: los parámetros comunes más los de este job.
  argumentos = merge(local.glue_common_args, {
    "--DATA_BUCKET" = aws_s3_bucket.data.bucket
  })

  depends_on = [aws_cloudwatch_log_group.glue_output, aws_cloudwatch_log_group.glue_error]
}

# Los recursos ya existían con otra dirección: "moved" le dice a Terraform que son los mismos
# (sin esto, borraría los viejos y crearía otros). Se pueden sacar después del apply.
moved {
  from = aws_iam_role.glue_gleif_full
  to   = module.glue_gleif_full.aws_iam_role.this
}

moved {
  from = aws_iam_role_policy.glue_gleif_full
  to   = module.glue_gleif_full.aws_iam_role_policy.this
}

moved {
  from = aws_glue_job.gleif_full
  to   = module.glue_gleif_full.aws_glue_job.this
}
