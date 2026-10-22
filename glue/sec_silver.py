"""Job de Glue: el último archivo de la SEC en landing -> contrato -> silver.sec_empresas.

Es una foto completa, como ISIN↔LEI: la tabla se reemplaza entera con el archivo más nuevo (sin
bronze y sin MERGE). Si ese archivo ya está en silver, no hace nada, salvo con
--FULL_REFRESH true, que lo vuelve a procesar (por ejemplo, después de cambiar una regla; ver
docs/adr/0007).

Son unas 10 mil filas: entran de sobra en la memoria del driver, así que se leen y se validan con
Python común, sin UDF. Spark está para escribir las tablas Iceberg.
"""

import sys
from collections import Counter
from importlib.metadata import version

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from refhub.bronze import file_name
from refhub.contract import sec_problem
from refhub.names import normalize_name
from refhub.silver import already_in_silver, create_tables, full_refresh_flag, latest_landing_key
from refhub.sources.sec import parse, publish_date

# FULL_REFRESH tiene default "false" en Terraform: Step Functions llama sin argumentos.
args = getResolvedOptions(sys.argv, ["DATA_BUCKET", "SILVER_DB", "FULL_REFRESH"])
full_refresh = full_refresh_flag(args["FULL_REFRESH"])
bucket = args["DATA_BUCKET"]
silver_db = f"glue_catalog.{args['SILVER_DB']}"
table = f"{silver_db}.sec_empresas"
quarantine = f"{silver_db}.sec_empresas_cuarentena"

spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
print(f"Modo: {'full refresh' if full_refresh else 'normal'}")
s3 = boto3.client("s3")


def process(key: str):
    name = file_name(key)
    rows = parse(s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8"))

    # El contrato: la MISMA función que probás con pytest. Las válidas llevan su nombre
    # normalizado; las de cuarentena no lo necesitan.
    for row in rows:
        row["motivo"] = sec_problem(row)
        row["nombre_normalizado"] = normalize_name(row["name"]) if row["motivo"] is None else None

    # La tabla promete una fila por ticker. Si la SEC repite uno, no sabemos cuál de los dos
    # vale: mejor parar que elegir al azar.
    counts = Counter(row["ticker"] for row in rows if row["motivo"] is None)
    repeated = sorted(ticker for ticker, n in counts.items() if n > 1)
    if repeated:
        raise ValueError(f"Tickers repetidos en {name}: {repeated[:10]}")

    batch = (
        spark.createDataFrame(
            rows,
            "cik string, name string, ticker string, exchange string, "
            "motivo string, nombre_normalizado string",
        )
        .withColumn("_archivo", F.lit(name))
        .withColumn("_fecha_publicacion", F.lit(publish_date(name)))
    )

    # Cuarentena: la partición de este archivo (reprocesarlo la reemplaza, no la duplica). Con
    # overwrite y no con overwritePartitions, que solo reemplaza las particiones que traen filas:
    # si al reprocesarlo ya no hay rechazadas, las viejas quedarían. Así se borran igual.
    batch.where(F.col("motivo").isNotNull()).select(
        "cik",
        "name",
        "ticker",
        "exchange",
        "_archivo",
        "_fecha_publicacion",
        "motivo",
        F.current_timestamp().alias("_procesado_en"),
    ).writeTo(quarantine).overwrite(F.col("_archivo") == name)

    # Silver: reemplazo total en un solo commit, como en ISIN↔LEI. El CIK va con 10 dígitos,
    # como lo escribe EDGAR (CIK0000320193): así se cruza tal cual con las otras APIs de la SEC.
    batch.where(F.col("motivo").isNull()).select(
        F.lpad("cik", 10, "0").alias("cik"),
        "name",
        "ticker",
        "exchange",
        "nombre_normalizado",
        "_archivo",
        "_fecha_publicacion",
    ).writeTo(table).overwrite(F.lit(True))

    rejected = sum(1 for row in rows if row["motivo"] is not None)
    print(f"{name}: {len(rows)} filas, {len(rows) - rejected} a silver, {rejected} a cuarentena")


# Las tablas con su DDL (si ya existen, no se tocan), y el archivo más nuevo de landing.
create_tables(spark, silver_db, ["silver_sec_empresas", "silver_sec_empresas_cuarentena"])
key = latest_landing_key(s3, bucket, "landing/sec/")
if already_in_silver(spark, table, file_name(key)) and not full_refresh:
    print(f"{file_name(key)} ya está en silver: no se escribe nada")
else:
    process(key)
