"""Job de Glue: landing (zips de GLEIF) -> bronze.gleif_lei (Iceberg, todo como texto + linaje).

Idempotente por archivo: solo carga los zips que todavía no están en bronze, y cada archivo
reemplaza su propia partición, así que repetir una corrida no duplica filas.
"""

import sys
from importlib.metadata import version

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from refhub.bronze import column_names, extract_csv, file_name, pending_files
from refhub.sources.gleif import publish_date

args = getResolvedOptions(sys.argv, ["DATA_BUCKET", "BRONZE_DB"])
bucket = args["DATA_BUCKET"]
table = f"glue_catalog.{args['BRONZE_DB']}.gleif_lei"  # catálogo.base.tabla

# La configuración de Iceberg (catálogo glue_catalog) llega en el parámetro --conf del job.
spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
s3 = boto3.client("s3")

# 1. ¿Qué hay en landing y qué ya está en bronze?
pages = s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="landing/gleif/")
landing = [obj["Key"] for page in pages for obj in page.get("Contents", [])]
loaded = []
if spark.catalog.tableExists(table):
    loaded = [row["_archivo"] for row in spark.table(table).select("_archivo").distinct().collect()]
pending = pending_files(landing, loaded)
print(f"Archivos para cargar: {len(pending)}")

# 2. Cada archivo pendiente, de a uno y del más viejo al más nuevo.
for key in pending:
    name = file_name(key)
    csv_key = extract_csv(s3, bucket, key)  # Spark no lee .zip: el CSV va a tmp/gleif/

    df = spark.read.csv(
        f"s3://{bucket}/{csv_key}",
        header=True,  # la primera fila son los nombres de columna
        escape='"',  # GLEIF escribe las comillas dentro de un texto como "" (no como \")
        mode="FAILFAST",  # si una fila está rota, que el job falle: bronze no adivina
    )  # sin inferSchema: todas las columnas quedan como texto (string)
    df = df.toDF(*column_names(df.columns))  # 'Entity.LegalName' -> 'entity_legalname'
    df = (
        df.withColumn("_archivo", F.lit(name))  # linaje: de qué archivo vino la fila
        .withColumn("_fecha_publicacion", F.lit(publish_date(name)))  # cuándo lo publicó GLEIF
        .withColumn("_cargado_en", F.current_timestamp())  # cuándo lo cargamos nosotros
    )

    if spark.catalog.tableExists(table):
        # Reemplaza solo la partición de ESTE archivo, en un único commit atómico.
        df.writeTo(table).overwritePartitions()
    else:
        # La primera vez crea la tabla, particionada por archivo de origen.
        df.writeTo(table).using("iceberg").partitionedBy(F.col("_archivo")).tableProperty(
            "format-version", "2"
        ).create()

    s3.delete_object(Bucket=bucket, Key=csv_key)  # el CSV temporal ya no hace falta
    print(f"{name}: cargado en bronze")
