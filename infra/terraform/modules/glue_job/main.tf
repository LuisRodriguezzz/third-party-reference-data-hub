# Un job de Glue del hub: su rol, sus permisos y el job, con la configuración que comparten
# todos (Glue 5.1, 2 workers, sin reintentos, una corrida a la vez).

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# QUIÉN puede usar el rol: solo el servicio Glue.
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "refhub-glue-${var.nombre}-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# QUÉ puede hacer: lo que diga permisos_json, y nada más.
resource "aws_iam_role_policy" "this" {
  name   = "permisos-minimos"
  role   = aws_iam_role.this.id
  policy = var.permisos_json
}

resource "aws_glue_job" "this" {
  name              = "refhub-${var.nombre}-${var.environment}"
  role_arn          = aws_iam_role.this.arn
  glue_version      = "5.1"  # Python 3.11: el que acepta refhub (>=3.11,<3.13)
  worker_type       = "G.1X" # 1 DPU por worker: 4 vCPU y 16 GB
  number_of_workers = 2      # el mínimo para un job de Spark: 1 driver + 1 executor
  timeout           = var.timeout
  max_retries       = 0 # si falla, mirás el log antes de gastar otra corrida

  command {
    name            = "glueetl" # job de Spark (aunque el script no use Spark)
    python_version  = "3"
    script_location = var.script_location
  }

  default_arguments = var.argumentos

  execution_property {
    max_concurrent_runs = 1 # nunca dos corridas a la vez: cargarían lo mismo dos veces
  }
}
