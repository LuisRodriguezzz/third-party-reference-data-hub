"""Job de Glue: el último archivo ISIN↔LEI de landing -> contrato -> silver.gleif_isin_lei.

Es una foto completa: la tabla se reemplaza entera con el archivo más nuevo (sin bronze y sin
MERGE: lo que no vino en la foto, ya no existe). Si ese archivo ya está en silver, no hace nada,
salvo con --FULL_REFRESH true, que lo vuelve a procesar (por ejemplo, después de cambiar una
regla; ver docs/adr/0007).
"""

import sys
from importlib.metadata import version

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import StringType

from refhub.bronze import extract_csv, file_name
from refhub.contract import isin_lei_problem
from refhub.silver import already_in_silver, create_tables, full_refresh_flag, latest_landing_key
from refhub.sources.gleif_isin_lei import publish_date

# FULL_REFRESH tiene default "false" en Terraform: Step Functions llama sin argumentos.
args = getResolvedOptions(sys.argv, ["DATA_BUCKET", "SILVER_DB", "FULL_REFRESH"])
full_refresh = full_refresh_flag(args["FULL_REFRESH"])
bucket = args["DATA_BUCKET"]
silver_db = f"glue_catalog.{args['SILVER_DB']}"
table = f"{silver_db}.gleif_isin_lei"
quarantine = f"{silver_db}.gleif_isin_lei_cuarentena"

spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
print(f"Modo: {'full refresh' if full_refresh else 'normal'}")
s3 = boto3.client("s3")


def process(key: str):
    name = file_name(key)
    csv_key = extract_csv(s3, bucket, key)  # Spark no lee .zip: el CSV va a tmp/
    batch = (
        spark.read.csv(f"s3://{bucket}/{csv_key}", header=True, mode="FAILFAST")
        # Por nombre, no por posición: la ficha de GLEIF dice ISIN,LEI y el archivo trae LEI,ISIN.
        .select(F.col("ISIN").alias("isin"), F.col("LEI").alias("lei"))
        .withColumn("_archivo", F.lit(name))
        .withColumn("_fecha_publicacion", F.lit(publish_date(name)))
    )

    # El contrato: la MISMA función que probás con pytest, aplicada a cada fila.
    problem = F.udf(lambda isin, lei: isin_lei_problem({"isin": isin, "lei": lei}), StringType())
    batch = batch.withColumn("motivo", problem("isin", "lei")).cache()

    # Cuarentena: la partición de este archivo (reprocesarlo la reemplaza, no la duplica). Con
    # overwrite y no con overwritePartitions, que solo reemplaza las particiones que traen filas:
    # si al reprocesarlo ya no hay rechazadas, las viejas quedarían. Así se borran igual.
    rejected = batch.where(F.col("motivo").isNotNull()).withColumn(
        "_procesado_en", F.current_timestamp()
    )
    rejected.select(
        "isin", "lei", "_archivo", "_fecha_publicacion", "motivo", "_procesado_en"
    ).writeTo(quarantine).overwrite(F.col("_archivo") == name)

    # Silver: overwrite(True) = "borrá todas las filas y escribí estas", en un solo commit.
    # Nadie ve la tabla a medias ni vacía, y los ISIN que GLEIF dio de baja desaparecen.
    valid = batch.where(F.col("motivo").isNull())
    valid.select("isin", "lei", "_archivo", "_fecha_publicacion").writeTo(table).overwrite(
        F.lit(True)
    )

    s3.delete_object(Bucket=bucket, Key=csv_key)  # el CSV temporal ya no hace falta
    total, rejected_count = batch.count(), rejected.count()
    print(
        f"{name}: {total} filas, {total - rejected_count} a silver, {rejected_count} a cuarentena"
    )


# Las tablas con su DDL (si ya existen, no se tocan), y el archivo más nuevo de landing.
create_tables(spark, silver_db, ["silver_gleif_isin_lei", "silver_gleif_isin_lei_cuarentena"])
key = latest_landing_key(s3, bucket, "landing/gleif_isin_lei/")
if already_in_silver(spark, table, file_name(key)) and not full_refresh:
    print(f"{file_name(key)} ya está en silver: no se escribe nada")
else:
    process(key)
