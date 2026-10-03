# Ingesta de GLEIF, parte 2: Step Functions que llama a la Lambda y un schedule APAGADO.

# ---------------------------------------------------------------- 1. Step Functions

# Rol de la máquina de estados. QUIÉN: solo el servicio Step Functions (states).
data "aws_iam_policy_document" "sfn_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "gleif_sfn" {
  name               = "${local.gleif_name}-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

# QUÉ: invocar ESTA Lambda y ninguna otra.
data "aws_iam_policy_document" "gleif_sfn" {
  statement {
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.gleif.arn,
      "${aws_lambda_function.gleif.arn}:*", # también sus versiones, si algún día se publican
    ]
  }
}

resource "aws_iam_role_policy" "gleif_sfn" {
  name   = "invocar-lambda-gleif"
  role   = aws_iam_role.gleif_sfn.id
  policy = data.aws_iam_policy_document.gleif_sfn.json
}

resource "aws_sfn_state_machine" "gleif" {
  name     = local.gleif_name
  role_arn = aws_iam_role.gleif_sfn.arn
  type     = "STANDARD" # guarda el historial de cada ejecución, visible en la consola

  # La definición es un JSON (Amazon States Language). jsonencode lo arma desde HCL.
  definition = jsonencode({
    Comment = "Baja el delta diario de GLEIF a landing/"
    StartAt = "BajarDeltaGleif" # el primer (y por ahora único) paso
    States = {
      BajarDeltaGleif = {
        Type     = "Task"                           # un paso que hace un trabajo
        Resource = "arn:aws:states:::lambda:invoke" # el trabajo: invocar una Lambda
        Parameters = {
          FunctionName = aws_lambda_function.gleif.arn
          "Payload.$"  = "$" # le pasa a la Lambda la entrada de la ejecución
        }
        OutputPath     = "$.Payload" # de la respuesta, nos quedamos con lo que devolvió la Lambda
        TimeoutSeconds = 300         # si en 5 minutos no terminó, se da por fallado
        Retry = [
          {
            # Errores pasajeros del propio servicio Lambda (recomendación de AWS).
            ErrorEquals = [
              "Lambda.ServiceException",
              "Lambda.AWSLambdaException",
              "Lambda.SdkClientException",
              "Lambda.TooManyRequestsException",
            ]
            IntervalSeconds = 2 # espera 2 s, después 4, 8...
            MaxAttempts     = 6
            BackoffRate     = 2
          },
          {
            # Cualquier otro error (por ejemplo, GLEIF no respondió): 2 reintentos más,
            # a los 30 s y a los 60 s. Es seguro porque la Lambda es idempotente.
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 30
            MaxAttempts     = 2
            BackoffRate     = 2
          },
        ]
        End = true # después de este paso, la ejecución termina
      }
    }
  })
}

# ---------------------------------------------------------------- 2. Scheduler (APAGADO)

# Rol del scheduler. QUIÉN: el servicio EventBridge Scheduler, y solo desde tu cuenta.
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id] # evita que un schedule de otra cuenta use este rol
    }
  }
}

resource "aws_iam_role" "gleif_scheduler" {
  name               = "${local.gleif_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

# QUÉ: arrancar ESTA máquina de estados y nada más.
data "aws_iam_policy_document" "gleif_scheduler" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.gleif.arn]
  }
}

resource "aws_iam_role_policy" "gleif_scheduler" {
  name   = "arrancar-ingesta-gleif"
  role   = aws_iam_role.gleif_scheduler.id
  policy = data.aws_iam_policy_document.gleif_scheduler.json
}

resource "aws_scheduler_schedule" "gleif_diario" {
  name                = "refhub-gleif-diario-${var.environment}"
  state               = "DISABLED"            # APAGADO: existe, pero no dispara nada
  schedule_expression = "cron(30 18 * * ? *)" # 18:30 UTC: GLEIF deja los archivos a las 18:00 UTC

  flexible_time_window {
    mode = "OFF" # a la hora exacta, sin ventana de tolerancia
  }

  target {
    arn      = aws_sfn_state_machine.gleif.arn  # a quién dispara
    role_arn = aws_iam_role.gleif_scheduler.arn # con qué permiso
    input    = jsonencode({})                   # entrada de la ejecución: un JSON vacío
  }
}