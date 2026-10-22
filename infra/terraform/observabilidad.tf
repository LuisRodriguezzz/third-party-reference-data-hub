# Observabilidad del pipeline: una Lambda que pasa el scorecard de gold a métricas de CloudWatch
# (EMF), un tema de SNS que manda mail y dos alarmas: el pipeline falló, o hay fuentes atrasadas.

locals {
  metricas_name = "refhub-metricas-${var.environment}" # -> refhub-metricas-dev
}

# ---------------------------------------------------------------- 1. La Lambda de métricas

# Logs con retención. Acá caen también las métricas: CloudWatch las saca del JSON (EMF) del log.
resource "aws_cloudwatch_log_group" "metricas_lambda" {
  name              = "/aws/lambda/${local.metricas_name}"
  retention_in_days = 14
}

resource "aws_iam_role" "metricas_lambda" {
  name               = "${local.metricas_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json # solo el servicio Lambda
}

# QUÉ: escribir su log (y con eso, las métricas: EMF no necesita cloudwatch:PutMetricData) y leer
# las dos tablas del scorecard con Athena. Nada más.
data "aws_iam_policy_document" "metricas_lambda" {
  statement {
    sid       = "EscribirSusLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.metricas_lambda.arn}:*"]
  }

  statement {
    sid       = "ConsultarConAthena" # solo en el workgroup del hub
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults"]
    resources = [aws_athena_workgroup.hub.arn]
  }

  statement {
    sid     = "CatalogoScorecard" # ver solo las dos tablas del scorecard
    actions = ["glue:GetDatabase", "glue:GetTable"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.gold.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.gold.name}/scorecard_*",
    ]
  }

  statement {
    sid       = "LeerScorecard" # dbt guarda cada tabla en gold/<tabla>/<id>
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/gold/scorecard_*"]
  }

  statement {
    sid       = "ResultadosDeAthena" # Athena escribe el resultado ahí y la Lambda lo lee
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/athena-results/*"]
  }

  statement {
    sid       = "VerElBucket"
    actions   = ["s3:GetBucketLocation", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}

resource "aws_iam_role_policy" "metricas_lambda" {
  name   = "permisos-minimos"
  role   = aws_iam_role.metricas_lambda.id
  policy = data.aws_iam_policy_document.metricas_lambda.json
}

resource "aws_lambda_function" "metricas" {
  function_name = local.metricas_name
  role          = aws_iam_role.metricas_lambda.arn
  runtime       = "python3.12"
  handler       = "refhub.metricas.handler"
  timeout       = 60  # dos consultas chicas a Athena: unos 5 segundos
  memory_size   = 128 # no procesa nada pesado

  # El mismo zip que la Lambda de ingesta: el paquete refhub entero, publicado por el CI.
  s3_bucket = aws_s3_bucket.data.bucket
  s3_key    = "artifacts/refhub/${var.refhub_version}/refhub-lambda.zip"

  environment {
    variables = {
      GOLD_DB          = aws_glue_catalog_database.gold.name
      ATHENA_WORKGROUP = aws_athena_workgroup.hub.name
      AMBIENTE         = var.environment # la única dimensión de las métricas
    }
  }

  depends_on = [aws_cloudwatch_log_group.metricas_lambda, aws_iam_role_policy.metricas_lambda]
}

# ---------------------------------------------------------------- 2. A dónde van las alertas

# Un tema de SNS: las alarmas publican acá y SNS reparte (hoy, a un mail). Sin cifrado propio:
# las claves KMS propias están prohibidas en el proyecto, y con la clave administrada aws/sns
# CloudWatch no puede publicar. Los mensajes son el nombre de la alarma y un número.
resource "aws_sns_topic" "alertas" {
  name = "refhub-alertas-${var.environment}"
}

# La suscripción por mail queda "pendiente" hasta que el dueño del mail hace clic en el link que
# manda AWS ("AWS Notification - Subscription Confirmation"). Sin ese clic no llega ninguna alerta.
resource "aws_sns_topic_subscription" "alertas_mail" {
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ---------------------------------------------------------------- 3. Las alarmas

# El pipeline falló. ExecutionsFailed la publica Step Functions sola, gratis, por máquina.
resource "aws_cloudwatch_metric_alarm" "pipeline_fallo" {
  alarm_name        = "refhub-pipeline-fallo-${var.environment}"
  alarm_description = "Una ejecución de ${aws_sfn_state_machine.pipeline.name} falló. Mirá en qué paso en la consola de Step Functions."

  namespace   = "AWS/States"
  metric_name = "ExecutionsFailed"
  dimensions = {
    StateMachineArn = aws_sfn_state_machine.pipeline.arn
  }
  statistic           = "Sum"
  period              = 300 # cuenta las fallas de cada 5 minutos
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0 # una sola falla ya avisa
  # Sin ejecuciones no hay dato: eso es "todo bien", no una alarma. Y la alarma vuelve sola a OK
  # en el período siguiente, así cada falla manda un mail.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alertas.arn] # solo al entrar en alarma, no al volver a OK
}

# Hay fuentes atrasadas: la métrica que publica la Lambda de métricas al final de cada corrida.
resource "aws_cloudwatch_metric_alarm" "fuentes_atrasadas" {
  alarm_name        = "refhub-fuentes-atrasadas-${var.environment}"
  alarm_description = "Alguna fuente pasó sus días tolerados sin publicar. El detalle está en ${aws_glue_catalog_database.gold.name}.scorecard_fuentes."

  namespace   = "refhub"
  metric_name = "fuentes_atrasadas"
  dimensions = {
    ambiente = var.environment
  }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  treat_missing_data  = "notBreaching" # la métrica llega una vez por corrida, no todo el tiempo

  alarm_actions = [aws_sns_topic.alertas.arn]
}
