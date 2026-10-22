"""Job de Glue: el último archivo de relaciones de GLEIF (nivel 2) en landing -> contrato ->
silver.gleif_relaciones.

Es una foto completa, como ISIN↔LEI y la SEC: la tabla se reemplaza entera con el archivo más
nuevo (sin bronze y sin MERGE). Si ese archivo ya está en silver, no hace nada, salvo con
--FULL_REFRESH true, que lo vuelve a procesar (por ejemplo, después de cambiar una regla; ver
docs/adr/0007).

Son unas 490 mil filas (230 MB de CSV; con las columnas que usamos, ~500 MB en memoria): entran
de sobra en el driver (16 GB), así que se leen y se validan con Python común, sin UDF, como en la
SEC. Spark está para escribir las tablas Iceberg.
"""

import io
import sys
from collections import Counter
from importlib.metadata import version

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql import functions as F

from refhub.bronze import file_name
from refhub.contract import parse_timestamp, relationship_problem
from refhub.silver import already_in_silver, create_tables, full_refresh_flag, latest_landing_key
from refhub.sources.gleif import publish_date
from refhub.sources.gleif_rr import read_rows

# FULL_REFRESH tiene default "false" en Terraform: Step Functions llama sin argumentos.
args = getResolvedOptions(sys.argv, ["DATA_BUCKET", "SILVER_DB", "FULL_REFRESH"])
full_refresh = full_refresh_flag(args["FULL_REFRESH"])
bucket = args["DATA_BUCKET"]
silver_db = f"glue_catalog.{args['SILVER_DB']}"
table = f"{silver_db}.gleif_relaciones"
quarantine = f"{silver_db}.gleif_relaciones_cuarentena"

spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
print(f"Modo: {'full refresh' if full_refresh else 'normal'}")
s3 = boto3.client("s3")

DATES = ["relationship_start", "relationship_end", "last_update"]
# Las columnas de la fuente, en el orden del DDL. La cuarentena guarda todo como texto, tal
# cual llegó; silver, las fechas como timestamp.
QUARANTINE_SCHEMA = (
    "child_lei string, parent_lei string, relationship_type string, "
    "relationship_status string, relationship_start string, relationship_end string, "
    "accounting_standard string, registration_status string, validation_sources string, "
    "last_update string, motivo string"
)
SILVER_SCHEMA = (
    "child_lei string, parent_lei string, relationship_type string, "
    "relationship_status string, relationship_start timestamp, relationship_end timestamp, "
    "accounting_standard string, registration_status string, validation_sources string, "
    "last_update timestamp"
)


def process(key: str):
    name = file_name(key)
    zip_file = io.BytesIO(s3.get_object(Bucket=bucket, Key=key)["Body"].read())  # ~23 MB
    rows = list(read_rows(zip_file))

    # El contrato: la MISMA función que probás con pytest.
    for row in rows:
        row["motivo"] = relationship_problem(row)
    valid = [row for row in rows if row["motivo"] is None]
    rejected = [row for row in rows if row["motivo"] is not None]

    # La tabla promete una fila por hijo y tipo de relación: una empresa tiene UNA controlante
    # final. Si GLEIF repite una, la empresa sumaría su exposición en dos grupos: mejor parar
    # que elegir al azar.
    counts = Counter((row["child_lei"], row["relationship_type"]) for row in valid)
    repeated = sorted(pair for pair, n in counts.items() if n > 1)
    if repeated:
        raise ValueError(f"Relaciones repetidas (hijo, tipo) en {name}: {repeated[:10]}")

    # Las fechas, con la misma función que usó el contrato: si el contrato la aceptó, se
    # convierte (con su huso horario, así Spark la guarda en UTC). Nunca queda un nulo de más.
    for row in valid:
        for column in DATES:
            row[column] = parse_timestamp(row[column])

    lineage = [F.lit(name).alias("_archivo"), F.lit(publish_date(name)).alias("_fecha_publicacion")]

    # Cuarentena: la partición de este archivo (reprocesarlo la reemplaza, no la duplica). Con
    # overwrite y no con overwritePartitions, que solo reemplaza las particiones que traen filas:
    # si al reprocesarlo ya no hay rechazadas, las viejas quedarían. Así se borran igual.
    spark.createDataFrame(rejected, QUARANTINE_SCHEMA).select(
        "*", *lineage, F.current_timestamp().alias("_procesado_en")
    ).writeTo(quarantine).overwrite(F.col("_archivo") == name)

    # Silver: overwrite(True) = "borrá todas las filas y escribí estas", en un solo commit.
    # Nadie ve la tabla a medias ni vacía, y las relaciones que GLEIF dio de baja desaparecen.
    spark.createDataFrame(valid, SILVER_SCHEMA).select("*", *lineage).writeTo(table).overwrite(
        F.lit(True)
    )

    print(f"{name}: {len(rows)} filas, {len(valid)} a silver, {len(rejected)} a cuarentena")
    for relationship_type, n in Counter(row["relationship_type"] for row in valid).most_common():
        print(f"  {relationship_type:<30} {n:>7}")


# Las tablas con su DDL (si ya existen, no se tocan), y el archivo más nuevo de landing.
create_tables(spark, silver_db, ["silver_gleif_relaciones", "silver_gleif_relaciones_cuarentena"])
key = latest_landing_key(s3, bucket, "landing/gleif_rr/")
if already_in_silver(spark, table, file_name(key)) and not full_refresh:
    print(f"{file_name(key)} ya está en silver: no se escribe nada")
else:
    process(key)
