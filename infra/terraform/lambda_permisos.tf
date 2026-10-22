# La API de permisos (hito 8, ADR 0012): una Lambda que responde "¿esta aplicación puede usar
# este dataset para este propósito?" buscando en la tabla de decisiones que compiló el CI, con
# una Function URL privada (solo se llama con una firma IAM).

locals {
  permisos_name = "refhub-permisos-${var.environment}" # -> refhub-permisos-dev
  # La tabla de la misma versión que el código: el CI publica las dos cosas juntas.
  decisiones_key = "artifacts/refhub/${var.refhub_version}/decisiones.json"
}

# ---------------------------------------------------------------- 1. Logs con retención

# Acá queda el registro de consumo: una línea por decisión (quién pidió qué y qué se respondió).
resource "aws_cloudwatch_log_group" "permisos" {
  name              = "/aws/lambda/${local.permisos_name}"
  retention_in_days = 14
}

# ---------------------------------------------------------------- 2. Permisos de la Lambda

# QUIÉN puede usar el rol: el servicio Lambda (el mismo documento que usa la de ingesta).
resource "aws_iam_role" "permisos" {
  name               = "${local.permisos_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# QUÉ puede hacer: escribir su log y leer un solo archivo. Nada más del bucket.
data "aws_iam_policy_document" "permisos" {
  statement {
    sid       = "EscribirSusLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.permisos.arn}:*"]
  }

  statement {
    # Sin ListBucket: si el archivo faltara, S3 responde 403 en vez de 404. Se acepta, porque
    # la Lambda no tiene que distinguir esos casos: sin tabla no hay API, y el log dice la clave.
    sid       = "LeerLaTablaDeDecisiones"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/${local.decisiones_key}"] # un objeto, no una carpeta
  }
}

resource "aws_iam_role_policy" "permisos" {
  name   = "permisos-minimos"
  role   = aws_iam_role.permisos.id
  policy = data.aws_iam_policy_document.permisos.json
}

# ---------------------------------------------------------------- 3. La Lambda

resource "aws_lambda_function" "permisos" {
  function_name = local.permisos_name
  role          = aws_iam_role.permisos.arn
  runtime       = "python3.12"
  handler       = "refhub.api_permisos.handler" # otro handler del mismo zip
  timeout       = 10                            # buscar una fila tarda milisegundos; 10 s es holgura para el arranque en frío
  memory_size   = 256                           # Lambda da CPU en proporción a la memoria: arranca más rápido que con 128

  # El mismo zip que la Lambda de ingesta. No lleva rdflib: la API no evalúa políticas.
  s3_bucket = aws_s3_bucket.data.bucket
  s3_key    = "artifacts/refhub/${var.refhub_version}/refhub-lambda.zip"

  environment {
    variables = {
      DECISIONES_BUCKET = aws_s3_bucket.data.bucket
      DECISIONES_KEY    = local.decisiones_key
    }
  }

  depends_on = [aws_cloudwatch_log_group.permisos, aws_iam_role_policy.permisos]
}

# ---------------------------------------------------------------- 4. La URL, privada

# Una URL HTTPS propia de la función, sin API Gateway: para una sola ruta no hace falta más.
# AWS_IAM: cada pedido tiene que venir firmado (SigV4) por alguien de la cuenta con permiso
# lambda:InvokeFunctionUrl. Sin firma, 403. No hay acceso público.
resource "aws_lambda_function_url" "permisos" {
  function_name      = aws_lambda_function.permisos.function_name
  authorization_type = "AWS_IAM"
}
