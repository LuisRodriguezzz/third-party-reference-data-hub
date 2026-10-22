# El pipeline entero en una máquina de Step Functions: las cuatro fuentes en paralelo hasta silver
# (OpenFIGI detrás de ISIN↔LEI), después dbt build (gold), las métricas del scorecard y el
# mantenimiento de Iceberg en silver. Y un schedule APAGADO.

locals {
  pipeline_name = "refhub-pipeline-${var.environment}" # -> refhub-pipeline-dev

  # Lo que repiten los cuatro pasos que invocan la Lambda de ingesta. Cada uno le suma su fuente
  # (Parameters) y a dónde sigue (Next) con merge.
  paso_lambda = {
    Type           = "Task"
    Resource       = "arn:aws:states:::lambda:invoke" # invocar una Lambda y esperar su respuesta
    OutputPath     = "$.Payload"                      # de la respuesta, lo que devolvió la Lambda
    TimeoutSeconds = 300                              # si en 5 minutos no terminó, se da por fallado
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
        # Cualquier otro error (por ejemplo, la fuente no respondió): 2 reintentos más, a los
        # 30 s y a los 60 s. Es seguro porque la Lambda es idempotente (ADR 0004).
        ErrorEquals     = ["States.TaskFailed"]
        IntervalSeconds = 30
        MaxAttempts     = 2
        BackoffRate     = 2
      },
    ]
  }

  # Lo que repiten los seis pasos que corren un job de Glue. Sin Retry: reintentar un job de Glue
  # cuesta. Si falla, mirás el log y lo corrés a mano.
  paso_glue = {
    Type     = "Task"
    Resource = "arn:aws:states:::glue:startJobRun.sync" # .sync: espera a que el job termine
    ResultSelector = {
      "estado.$"   = "$.JobRunState"   # de la respuesta de Glue, solo el estado...
      "segundos.$" = "$.ExecutionTime" # ...y cuánto tardó
    }
    TimeoutSeconds = 3600
  }

  # Los jobs que arranca la máquina (para los permisos).
  jobs_del_pipeline = [
    module.glue_gleif_bronze.job_arn,
    module.glue_gleif_silver.job_arn,
    module.glue_gleif_isin_lei.job_arn,
    module.glue_openfigi.job_arn,
    module.glue_sec.job_arn,
    module.glue_gleif_relaciones.job_arn,
  ]

  # Mantenimiento de Iceberg: cada MERGE o reemplazo de silver es copy-on-write, o sea que
  # reescribe archivos enteros, y los viejos quedan en S3 mientras algún snapshot los use.
  # VACUUM borra los snapshots de más de 7 días y los archivos que solo usaban ellos. 7 días deja
  # volver atrás (time travel) a cualquier corrida de la última semana; lo de antes se recupera
  # reprocesando desde landing (ADR 0007). El default de Athena son 5 días.
  retencion_snapshots_segundos = 7 * 24 * 3600 # 604800

  tablas_silver = [
    "gleif_lei", "gleif_lei_cuarentena", "gleif_archivos_procesados",
    "gleif_isin_lei", "gleif_isin_lei_cuarentena",
    "sec_empresas", "sec_empresas_cuarentena",
    "gleif_relaciones", "gleif_relaciones_cuarentena",
    "openfigi_tickers",
  ]

  # Las dos consultas de cada tabla, armadas acá y no en Step Functions: así se leen enteras.
  # La primera fija la retención (es una propiedad de la tabla Iceberg que lee VACUUM; las tablas
  # las crea Spark, que no la pone) y la segunda limpia.
  mantenimiento_silver = [
    for tabla in local.tablas_silver : {
      tabla     = tabla
      retencion = "ALTER TABLE ${aws_glue_catalog_database.silver.name}.${tabla} SET TBLPROPERTIES ('vacuum_max_snapshot_age_seconds' = '${local.retencion_snapshots_segundos}')"
      vacuum    = "VACUUM ${aws_glue_catalog_database.silver.name}.${tabla}"
    }
  ]
}

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

# Antes se llamaba refhub-gleif-ingest-dev-sfn, cuando la máquina solo corría GLEIF. El nombre
# nuevo hace que Terraform lo reemplace (borra el viejo y crea este): un rol no guarda datos.
resource "aws_iam_role" "pipeline_sfn" {
  name               = "${local.pipeline_name}-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

moved {
  from = aws_iam_role.gleif_sfn
  to   = aws_iam_role.pipeline_sfn
}

# QUÉ: invocar las Lambdas de ingesta y de métricas, correr los jobs de silver y el build de dbt,
# y el mantenimiento de silver en Athena. Nada más.
data "aws_iam_policy_document" "pipeline_sfn" {
  statement {
    sid     = "InvocarLaLambda"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.gleif.arn,
      "${aws_lambda_function.gleif.arn}:*", # también sus versiones, si algún día se publican
      aws_lambda_function.metricas.arn,
      "${aws_lambda_function.metricas.arn}:*",
    ]
  }

  statement {
    # Arrancar el job, preguntar cómo va (para esperar a que termine) y frenarlo si se cancela.
    sid       = "CorrerLosJobs"
    actions   = ["glue:StartJobRun", "glue:GetJobRun", "glue:GetJobRuns", "glue:BatchStopJobRun"]
    resources = local.jobs_del_pipeline
  }

  statement {
    # Lo mismo con el build de dbt: arrancarlo, ver cómo va y frenarlo si la ejecución se cancela.
    sid       = "CorrerDbt"
    actions   = ["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds", "codebuild:BatchGetReports"]
    resources = [aws_codebuild_project.dbt.arn]
  }

  statement {
    # Para esperar a CodeBuild (.sync), Step Functions no pregunta cada tanto como con Glue: crea
    # una regla de EventBridge con este nombre fijo y espera el evento de "build terminado".
    sid       = "EsperarACodeBuild"
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:${data.aws_region.actual.region}:${local.account_id}:rule/StepFunctionsGetEventForCodeBuildStartBuildRule"]
  }

  # El mantenimiento de silver lo corre Athena con los permisos de este rol: la consulta, el
  # catálogo (cada ALTER y cada VACUUM es un commit nuevo de la tabla) y los archivos.
  statement {
    sid       = "MantenimientoConAthena"
    actions   = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:StopQueryExecution", "athena:GetWorkGroup"]
    resources = [aws_athena_workgroup.hub.arn]
  }

  statement {
    sid     = "MantenimientoCatalogoSilver"
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:UpdateTable"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.silver.name}/*",
    ]
  }

  statement {
    # Sin DeleteObject, VACUUM "termina bien" pero no borra nada (lo dice la documentación).
    sid       = "MantenimientoArchivosSilver"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.data.arn}/silver/*"]
  }

  statement {
    sid       = "MantenimientoResultados"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/athena-results/*"]
  }

  statement {
    sid       = "MantenimientoVerElBucket" # VACUUM lista la carpeta para encontrar huérfanos
    actions   = ["s3:GetBucketLocation", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }
}

resource "aws_iam_role_policy" "pipeline_sfn" {
  name   = "orquestar-el-pipeline"
  role   = aws_iam_role.pipeline_sfn.id
  policy = data.aws_iam_policy_document.pipeline_sfn.json
}

moved {
  from = aws_iam_role_policy.gleif_sfn
  to   = aws_iam_role_policy.pipeline_sfn
}

# Antes se llamaba refhub-gleif-ingest-dev. Cambiar el nombre reemplaza la máquina: se pierde el
# historial de las ejecuciones viejas (son pruebas a mano) y no se pierde ningún dato.
resource "aws_sfn_state_machine" "pipeline" {
  name     = local.pipeline_name
  role_arn = aws_iam_role.pipeline_sfn.arn
  type     = "STANDARD" # guarda el historial de cada ejecución, visible en la consola

  # La definición es un JSON (Amazon States Language). jsonencode lo arma desde HCL.
  definition = jsonencode({
    Comment = "Las fuentes hasta silver en paralelo, gold con dbt, métricas y mantenimiento de silver"
    StartAt = "Fuentes"
    States = {
      # Parallel corre las cuatro ramas a la vez y espera a que terminen todas. Si una falla,
      # Step Functions frena las otras y la ejecución falla: gold no se arma con datos a medias.
      # (Frenar un job a la mitad no deja una tabla rota: cada escritura de Iceberg es un commit
      # atómico.)
      Fuentes = {
        Type       = "Parallel"
        ResultPath = "$.fuentes" # lo que devolvió cada rama, en una lista, para ver la ejecución
        Next       = "ArmarGold"
        Branches = [
          {
            # GLEIF nivel 1: el delta del día → bronze → silver (el MERGE por LEI).
            StartAt = "BajarDeltaGleif"
            States = {
              BajarDeltaGleif = merge(local.paso_lambda, {
                Parameters = { FunctionName = aws_lambda_function.gleif.arn, Payload = { fuente = "gleif" } }
                Next       = "CargarBronzeGleif"
              })
              CargarBronzeGleif = merge(local.paso_glue, {
                Parameters = { JobName = module.glue_gleif_bronze.job_name }
                ResultPath = "$.bronze" # se agrega a lo que devolvió la Lambda, sin pisarlo
                Next       = "CargarSilverGleif"
              })
              CargarSilverGleif = merge(local.paso_glue, {
                Parameters = { JobName = module.glue_gleif_silver.job_name }
                ResultPath = "$.silver"
                End        = true
              })
            }
          },
          {
            # ISIN↔LEI → silver, y detrás OpenFIGI, que pregunta por los ISIN de esa tabla. Va en
            # la misma rama porque depende solo de ella: así corre mientras las otras terminan.
            StartAt = "BajarIsinLei"
            States = {
              BajarIsinLei = merge(local.paso_lambda, {
                Parameters = { FunctionName = aws_lambda_function.gleif.arn, Payload = { fuente = "gleif_isin_lei" } }
                Next       = "CargarSilverIsinLei"
              })
              CargarSilverIsinLei = merge(local.paso_glue, {
                Parameters = { JobName = module.glue_gleif_isin_lei.job_name }
                ResultPath = "$.silver"
                Next       = "ConsultarOpenfigi"
              })
              ConsultarOpenfigi = merge(local.paso_glue, {
                Parameters = { JobName = module.glue_openfigi.job_name }
                ResultPath = "$.openfigi"
                End        = true
              })
            }
          },
          {
            # Las empresas de la SEC → silver.
            StartAt = "BajarSec"
            States = {
              BajarSec = merge(local.paso_lambda, {
                Parameters = { FunctionName = aws_lambda_function.gleif.arn, Payload = { fuente = "sec" } }
                Next       = "CargarSilverSec"
              })
              CargarSilverSec = merge(local.paso_glue, {
                Parameters = { JobName = module.glue_sec.job_name }
                ResultPath = "$.silver"
                End        = true
              })
            }
          },
          {
            # Las relaciones de GLEIF (nivel 2) → silver. Gold todavía no las usa, pero se cargan
            # igual: así silver queda siempre de la misma fecha para todas las fuentes.
            StartAt = "BajarRelaciones"
            States = {
              BajarRelaciones = merge(local.paso_lambda, {
                Parameters = { FunctionName = aws_lambda_function.gleif.arn, Payload = { fuente = "gleif_rr" } }
                Next       = "CargarSilverRelaciones"
              })
              CargarSilverRelaciones = merge(local.paso_glue, {
                Parameters = { JobName = module.glue_gleif_relaciones.job_name }
                ResultPath = "$.silver"
                End        = true
              })
            }
          },
        ]
      }

      # Gold: dbt build en CodeBuild (ADR 0011). Solo llega acá si las cuatro ramas terminaron bien.
      ArmarGold = {
        Type     = "Task"
        Resource = "arn:aws:states:::codebuild:startBuild.sync" # .sync: espera a que el build termine
        Parameters = {
          ProjectName = aws_codebuild_project.dbt.name
        }
        ResultSelector = {
          "estado.$" = "$.Build.BuildStatus" # SUCCEEDED; si falló, el paso ya falló antes
          "build.$"  = "$.Build.Id"          # para buscar el log del build
        }
        ResultPath     = "$.gold"
        TimeoutSeconds = 2400 # 40 minutos: más que el timeout del build (30) más la cola
        # Sin Retry, como Glue: si dbt falla casi siempre es un test de datos, y repetir no lo arregla.
        Next = "PublicarMetricas"
      }

      # Lee el scorecard de gold y lo deja como métricas en CloudWatch (EMF). Ahí miran las alarmas.
      # Mismos reintentos que la ingesta: la Lambda solo lee y escribe un log, se puede repetir.
      PublicarMetricas = merge(local.paso_lambda, {
        Parameters = { FunctionName = aws_lambda_function.metricas.arn }
        OutputPath = "$" # el paso_lambda se queda con $.Payload; acá, con todo lo que venía...
        ResultSelector = {
          "valores.$" = "$.Payload" # ...así, lo que devolvió la Lambda...
        }
        ResultPath = "$.metricas" # ...se agrega a lo que venía, como los otros pasos
        Next       = "TablasSilver"
      })

      # Mantenimiento de Iceberg: al final, con gold ya armado, para no competir con nada.
      # Pass solo pone la lista de tablas (con sus dos consultas) en la entrada del Map.
      TablasSilver = {
        Type       = "Pass"
        Result     = local.mantenimiento_silver
        ResultPath = "$.mantenimiento"
        Next       = "MantenerSilver"
      }

      # Una iteración por tabla, de a una (MaxConcurrency = 1): son consultas cortas y así no
      # compiten por el límite de consultas simultáneas de Athena.
      MantenerSilver = {
        Type           = "Map"
        ItemsPath      = "$.mantenimiento"
        MaxConcurrency = 1
        ResultPath     = null # lo que devuelve cada consulta no sirve: la salida queda como venía
        ItemProcessor = {
          ProcessorConfig = { Mode = "INLINE" }
          StartAt         = "FijarRetencion"
          States = {
            FijarRetencion = {
              Type       = "Task"
              Resource   = "arn:aws:states:::athena:startQueryExecution.sync" # espera a que termine
              Parameters = { "QueryString.$" = "$.retencion", WorkGroup = aws_athena_workgroup.hub.name }
              ResultPath = null # se queda con la tabla de esta iteración, para el paso siguiente
              # Sin Retry: si falla, la ejecución falla y la alarma avisa. Silver ya está cargada.
              TimeoutSeconds = 300
              Next           = "Vacuum"
            }
            Vacuum = {
              Type           = "Task"
              Resource       = "arn:aws:states:::athena:startQueryExecution.sync"
              Parameters     = { "QueryString.$" = "$.vacuum", WorkGroup = aws_athena_workgroup.hub.name }
              ResultPath     = null
              TimeoutSeconds = 900
              End            = true
            }
          }
        }
        End = true
      }
    }
  })
}

moved {
  from = aws_sfn_state_machine.gleif
  to   = aws_sfn_state_machine.pipeline
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

resource "aws_iam_role" "pipeline_scheduler" {
  name               = "${local.pipeline_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

moved {
  from = aws_iam_role.gleif_scheduler
  to   = aws_iam_role.pipeline_scheduler
}

# QUÉ: arrancar ESTA máquina de estados y nada más.
data "aws_iam_policy_document" "pipeline_scheduler" {
  statement {
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.pipeline.arn]
  }
}

resource "aws_iam_role_policy" "pipeline_scheduler" {
  name   = "arrancar-el-pipeline"
  role   = aws_iam_role.pipeline_scheduler.id
  policy = data.aws_iam_policy_document.pipeline_scheduler.json
}

moved {
  from = aws_iam_role_policy.gleif_scheduler
  to   = aws_iam_role_policy.pipeline_scheduler
}

resource "aws_scheduler_schedule" "pipeline_diario" {
  name                = "${local.pipeline_name}-diario"
  state               = "DISABLED"            # APAGADO: existe, pero no dispara nada
  schedule_expression = "cron(30 18 * * ? *)" # 18:30 UTC: GLEIF deja los archivos a las 18:00 UTC

  flexible_time_window {
    mode = "OFF" # a la hora exacta, sin ventana de tolerancia
  }

  target {
    arn      = aws_sfn_state_machine.pipeline.arn  # a quién dispara
    role_arn = aws_iam_role.pipeline_scheduler.arn # con qué permiso
    input    = jsonencode({})                      # entrada de la ejecución: un JSON vacío
  }
}

moved {
  from = aws_scheduler_schedule.gleif_diario
  to   = aws_scheduler_schedule.pipeline_diario
}
