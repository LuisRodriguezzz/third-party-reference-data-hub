# Ingesta de GLEIF, parte 1: el código empaquetado, sus logs, sus permisos y la Lambda.

# Un "local" es un valor con nombre que se calcula una vez y se reusa en este proyecto.
locals {
  gleif_name = "refhub-gleif-ingest-${var.environment}" # -> refhub-gleif-ingest-dev
}

# ---------------------------------------------------------------- 1. Empaquetar el código

# Un bloque "data" no crea nada en AWS: este arma un zip en tu disco durante el plan.
data "archive_file" "refhub" {
  type             = "zip"
  source_dir       = "${path.module}/../../src"        # la carpeta src/ del repo: adentro está refhub/
  output_path      = "${path.module}/build/refhub.zip" # dónde deja el zip (build/ está en .gitignore)
  excludes         = ["**/__pycache__/**", "**/*.pyc"] # basura de Python que no tiene que viajar
  output_file_mode = "0644"                            # permisos de lectura que Lambda necesita
}

# ---------------------------------------------------------------- 2. Logs con retención

# Si no lo creamos nosotros, Lambda lo crea sola la primera vez que corre, con retención
# infinita. Creándolo antes, con el mismo nombre que usa Lambda, decidimos cuánto dura.
resource "aws_cloudwatch_log_group" "gleif_lambda" {
  name              = "/aws/lambda/${local.gleif_name}" # el nombre que Lambda busca por defecto
  retention_in_days = 14                                # a los 14 días los logs se borran solos
}

# ---------------------------------------------------------------- 3. Permisos de la Lambda

# Un rol tiene dos partes. La primera dice QUIÉN puede usarlo: acá, solo el servicio Lambda.
data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"] # "ponerse" el rol
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "gleif_lambda" {
  name               = "${local.gleif_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

# La segunda parte dice QUÉ puede hacer: escribir sus logs y tocar solo landing/gleif/.
data "aws_iam_policy_document" "gleif_lambda" {
  statement {
    sid       = "EscribirSusLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]      # sin CreateLogGroup: ya lo creamos
    resources = ["${aws_cloudwatch_log_group.gleif_lambda.arn}:*"] # solo en SU log group
  }

  statement {
    sid       = "LeerYEscribirLandingGleif"
    actions   = ["s3:GetObject", "s3:PutObject"]              # HeadObject usa el permiso GetObject
    resources = ["${aws_s3_bucket.data.arn}/landing/gleif/*"] # solo objetos bajo landing/gleif/
  }

  statement {
    # Sin ListBucket, preguntar por un objeto que no existe da 403 en vez de 404,
    # y el código no podría distinguir "no está" de "no tengo permiso".
    sid       = "ListarElBucket"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn] # ListBucket es un permiso sobre el bucket, no sobre objetos
  }
}

# Pega la lista de permisos al rol.
resource "aws_iam_role_policy" "gleif_lambda" {
  name   = "permisos-minimos"
  role   = aws_iam_role.gleif_lambda.id
  policy = data.aws_iam_policy_document.gleif_lambda.json
}

# ---------------------------------------------------------------- 4. La Lambda

resource "aws_lambda_function" "gleif" {
  function_name = local.gleif_name
  role          = aws_iam_role.gleif_lambda.arn        # con qué permisos corre
  runtime       = "python3.12"                         # trae Python 3.12 y boto3 incluidos
  handler       = "refhub.sources.gleif.handler"       # módulo.función que Lambda llama
  filename      = data.archive_file.refhub.output_path # el zip del paso 1
  timeout       = 120                                  # segundos; el delta pesa menos de 1 MB
  memory_size   = 256                                  # MB

  # Huella del zip: si cambia el código, cambia la huella y Terraform sube el zip nuevo.
  source_code_hash = data.archive_file.refhub.output_base64sha256

  # Variables de entorno: el código lee el nombre del bucket de acá (os.environ).
  environment {
    variables = {
      DATA_BUCKET = aws_s3_bucket.data.bucket
    }
  }

  # Sin VPC: la Lambda sale a internet (a GLEIF) sin NAT Gateway, que cobra por hora.
  # Primero el log group y los permisos, después la función.
  depends_on = [aws_cloudwatch_log_group.gleif_lambda, aws_iam_role_policy.gleif_lambda]
}