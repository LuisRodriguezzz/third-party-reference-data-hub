# El catálogo (qué tablas hay y dónde están) y Athena (para consultarlas con SQL).

data "aws_region" "actual" {}

locals {
  # ARNs del Glue Data Catalog que usan los permisos de los jobs.
  glue_catalog_arn = "arn:aws:glue:${data.aws_region.actual.region}:${local.account_id}:catalog"
}

# Una "base de datos" del catálogo es solo un nombre y una carpeta por defecto: no hay servidor.
# Las tablas Iceberg que se creen acá van a parar a s3://<bucket>/bronze/<tabla>.
resource "aws_glue_catalog_database" "bronze" {
  name         = "refhub_bronze_${var.environment}"
  description  = "Bronze del hub: las filas de cada fuente tal cual, como texto, con linaje."
  location_uri = "s3://${aws_s3_bucket.data.bucket}/bronze/"
}

# Un workgroup de Athena es un "espacio" con sus reglas: dónde van los resultados y cuánto
# puede leer como máximo una consulta. Athena cobra por byte leído: el tope es tu red de seguridad.
resource "aws_athena_workgroup" "hub" {
  name          = "refhub-${var.environment}"
  force_destroy = true # destroy lo borra aunque tenga consultas guardadas

  configuration {
    enforce_workgroup_configuration    = true       # las reglas del workgroup ganan sobre las del cliente
    publish_cloudwatch_metrics_enabled = false      # sin métricas: no hacen falta
    bytes_scanned_cutoff_per_query     = 1073741824 # 1 GB: una consulta que lea más se cancela (0,005 USD)

    engine_version {
      selected_engine_version = "Athena engine version 3"
    }

    result_configuration {
      output_location = "s3://${aws_s3_bucket.data.bucket}/athena-results/" # se borran a los 7 días

      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}

# Silver: las tablas tipadas, la cuarentena y el registro de archivos procesados.
resource "aws_glue_catalog_database" "silver" {
  name         = "refhub_silver_${var.environment}"
  description  = "Silver del hub: datos tipados y validados, cuarentena con motivo."
  location_uri = "s3://${aws_s3_bucket.data.bucket}/silver/"
}

# Gold: la golden copy, con las fuentes ya cruzadas. Sus tablas no las crea Spark sino dbt
# (carpeta dbt/), así que el esquema de cada una vive en el YAML de dbt (ADR 0006 y 0008).
# Terraform solo crea la base y le da su carpeta; dbt guarda cada tabla en gold/<tabla>/<id>.
resource "aws_glue_catalog_database" "gold" {
  name         = "refhub_gold_${var.environment}"
  description  = "Gold del hub: la golden copy de empresas, una fila por CIK, armada con dbt."
  location_uri = "s3://${aws_s3_bucket.data.bucket}/gold/"
}
