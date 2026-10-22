# Gold en AWS: un proyecto de CodeBuild que corre `dbt build` (ADR 0011). No hay servidor ni
# imagen propia: cada corrida levanta un contenedor estándar de AWS, instala dbt con las
# versiones fijas de uv.lock, corre los modelos contra Athena y se apaga. Se paga por minuto.

locals {
  dbt_name = "refhub-dbt-${var.environment}" # -> refhub-dbt-dev
}

# ---------------------------------------------------------------- 1. Logs con retención

# Si no lo creamos nosotros, CodeBuild usa uno propio con retención infinita.
resource "aws_cloudwatch_log_group" "dbt" {
  name              = "/aws/codebuild/${local.dbt_name}"
  retention_in_days = 14
}

# ---------------------------------------------------------------- 2. Permisos

# QUIÉN: solo el servicio CodeBuild.
data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dbt" {
  name               = "${local.dbt_name}-codebuild"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

# QUÉ: bajar el proyecto dbt publicado, consultar con Athena (que usa estos mismos permisos para
# leer silver y escribir gold), y nada más. Gold se escribe; silver solo se lee.
data "aws_iam_policy_document" "dbt" {
  statement {
    sid       = "EscribirSusLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.dbt.arn}:*"]
  }

  statement {
    sid       = "BajarElProyectoDbt" # el zip que publicó el CI para esta versión
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.data.arn}/artifacts/refhub/*/refhub-dbt.zip"]
  }

  statement {
    # GetBucketLocation lo piden CodeBuild (para bajar el zip) y Athena (para los resultados).
    # ListBucket, para recibir 404 en vez de 403 y para que dbt borre las carpetas viejas de gold.
    sid       = "VerElBucket"
    actions   = ["s3:GetBucketLocation", "s3:GetBucketAcl", "s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    sid       = "LeerSilver" # solo leer: gold nunca modifica silver
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/silver/*"]
  }

  statement {
    # Las tablas de gold (datos y metadatos de Iceberg) y los resultados de cada consulta.
    sid       = "EscribirGoldYResultados"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.data.arn}/gold/*", "${aws_s3_bucket.data.arn}/athena-results/*"]
  }

  statement {
    sid = "ConsultarConAthena" # solo en el workgroup del hub, que tiene el tope de 1 GB
    actions = [
      "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
      "athena:StopQueryExecution", "athena:GetWorkGroup",
    ]
    resources = [aws_athena_workgroup.hub.arn]
  }

  statement {
    sid     = "CatalogoLeerSilver" # ver las tablas de silver (Athena las necesita para leerlas)
    actions = ["glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:GetPartitions"]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.silver.name}/*",
    ]
  }

  statement {
    # Crear, cambiar y borrar tablas, solo en gold. dbt crea la tabla nueva al lado, la cambia
    # por la vieja (rename = crear + borrar) y limpia las versiones viejas de la tabla.
    sid = "CatalogoEscribirGold"
    actions = [
      "glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables",
      "glue:GetPartitions", "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
      "glue:BatchDeleteTable", "glue:GetTableVersions", "glue:DeleteTableVersion",
      "glue:BatchDeleteTableVersion",
    ]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.gold.arn,
      "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:table/${aws_glue_catalog_database.gold.name}/*",
    ]
  }
}

resource "aws_iam_role_policy" "dbt" {
  name   = "permisos-minimos"
  role   = aws_iam_role.dbt.id
  policy = data.aws_iam_policy_document.dbt.json
}

# ---------------------------------------------------------------- 3. El proyecto de CodeBuild

resource "aws_codebuild_project" "dbt" {
  name                   = local.dbt_name
  description            = "Corre dbt build: gold del hub en Athena (ADR 0011)."
  service_role           = aws_iam_role.dbt.arn
  build_timeout          = 30 # minutos; hoy tarda unos 4. Si se pasa, CodeBuild lo corta
  queued_timeout         = 30 # si en media hora no consiguió máquina, falla en vez de esperar 8 h
  concurrent_build_limit = 1  # nunca dos builds a la vez: los dos reemplazarían las mismas tablas

  # El proyecto dbt que publicó el CI para esta versión, con su buildspec.yml adentro (cómo se
  # instala y se corre). Versión nueva = otra clave = proyecto nuevo, como la Lambda y Glue.
  source {
    type     = "S3"
    location = "${aws_s3_bucket.data.bucket}/artifacts/refhub/${var.refhub_version}/refhub-dbt.zip"
  }

  artifacts {
    type = "NO_ARTIFACTS" # dbt no deja archivos: deja tablas en gold
  }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"                          # 2 vCPU y 3 GB: entran en los minutos gratis
    image        = "aws/codebuild/amazonlinux-x86_64-standard:5.0" # imagen de AWS, trae Python 3.12
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "REFHUB_DATA_BUCKET" # la lee profiles.yml, igual que en tu máquina
      value = aws_s3_bucket.data.bucket
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.dbt.name
    }
    s3_logs {
      status = "DISABLED"
    }
  }

  # Sin vpc_config: CodeBuild sale a internet (a PyPI) sin NAT Gateway y llega a Athena y a S3
  # por sus direcciones públicas, con TLS, como la Lambda.
  depends_on = [aws_cloudwatch_log_group.dbt, aws_iam_role_policy.dbt]
}
