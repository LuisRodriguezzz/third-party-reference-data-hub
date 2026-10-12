"""Job de Glue: bronze.gleif_lei -> contrato -> silver.gleif_lei (tipada) + cuarentena.

Idempotente por archivo: procesa los archivos de bronze que no están en el registro
gleif_archivos_procesados, y cada escritura se puede repetir sin duplicar.

El contrato se hace cumplir en dos niveles:
- estructura: las tablas se crean con su DDL (src/refhub/ddl/*.sql: tipos, NOT NULL y
  descripciones), e Iceberg rechaza cualquier escritura que no lo respete;
- validez: las reglas por fila (refhub.contract.row_problem) deciden qué va a cuarentena.
"""

import sys
from importlib.metadata import version
from importlib.resources import files

from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StringType

from refhub.bronze import column_name
from refhub.contract import row_problem
from refhub.names import normalize_name
from refhub.sources.gleif import COLUMNS

args = getResolvedOptions(sys.argv, ["BRONZE_DB", "SILVER_DB"])
silver_db = f"glue_catalog.{args['SILVER_DB']}"
bronze = f"glue_catalog.{args['BRONZE_DB']}.gleif_lei"
silver = f"{silver_db}.gleif_lei"
quarantine = f"{silver_db}.gleif_lei_cuarentena"
processed = f"{silver_db}.gleif_archivos_procesados"

spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
normalize = F.udf(normalize_name, StringType())  # la misma función que probás con pytest


def create_tables():
    """Paso 0: crea las tablas con su DDL, que viaja dentro del .whl (refhub/ddl/*.sql).

    IF NOT EXISTS: si la tabla ya existe, no la toca. Cambiar una tabla que ya tiene datos
    es una migración aparte (ALTER TABLE), no algo que el job haga solo.
    """
    for name in [
        "silver_gleif_lei",
        "silver_gleif_lei_cuarentena",
        "silver_gleif_archivos_procesados",
    ]:
        ddl = files("refhub").joinpath(f"ddl/{name}.sql").read_text(encoding="utf-8")
        spark.sql(ddl.format(db=silver_db))


def process(pending):
    """Pasos 2 a 8 para los archivos pendientes."""
    # 2. Las columnas que usa silver, con los nombres del hito 1 (COLUMNS de gleif.py).
    selection = [F.col(column_name(gleif)).alias(ours) for gleif, ours in COLUMNS.items()]
    batch = (
        spark.table(bronze)
        .where(F.col("_archivo").isin(pending))
        .select(*selection, "_archivo", "_fecha_publicacion")
    )

    # 3. El contrato: la MISMA función que probás con pytest, aplicada a cada fila.
    problem = F.udf(lambda row: row_problem(row.asDict()), StringType())
    batch = batch.withColumn("motivo", problem(F.struct(*COLUMNS.values()))).cache()

    # 4. Cuarentena: las filas que no cumplen, con su motivo. Siguen intactas en bronze.
    #    Reemplaza la partición de cada archivo: reprocesar no duplica.
    rejected = batch.where(F.col("motivo").isNotNull()).select(
        *COLUMNS.values(),
        "_archivo",
        "_fecha_publicacion",
        "motivo",
        F.current_timestamp().alias("_procesado_en"),
    )
    rejected.writeTo(quarantine).overwritePartitions()

    # 5. Las válidas, tipadas: los textos de fecha pasan a timestamp (en UTC).
    valid = batch.where(F.col("motivo").isNull()).select(
        "lei",
        "legal_name",
        normalize("legal_name").alias("nombre_normalizado"),  # para cruzar con la SEC
        "country",
        "entity_status",
        "registration_status",
        F.to_timestamp("last_update").alias("last_update"),
        F.to_timestamp("next_renewal").alias("next_renewal"),
        "_archivo",
        "_fecha_publicacion",
        F.col("next_renewal").alias("_next_renewal_texto"),  # solo para el chequeo de abajo
    )
    # El contrato dijo "fecha válida" pero Spark no la pudo convertir: mejor parar que dejar
    # un nulo. next_renewal puede venir vacía (la regla lo permite), pero si traía un texto y
    # quedó nula, se perdió un dato.
    lost_date = F.col("last_update").isNull() | (
        F.col("next_renewal").isNull() & (F.coalesce("_next_renewal_texto", F.lit("")) != "")
    )
    if valid.where(lost_date).limit(1).count() > 0:
        raise ValueError("Hay fechas que el contrato aceptó y Spark no pudo convertir")

    # 6. Una fila por LEI: la del archivo más nuevo (y dentro de un archivo, la de fecha de
    #    actualización más nueva). Los deltas se solapan, así que el mismo LEI puede venir
    #    varias veces. Gana lo que GLEIF publicó último y no la fecha más alta, porque la fecha
    #    puede ir para atrás (ver refhub.contract.latest_per_lei).
    newest_first = Window.partitionBy("lei").orderBy(F.desc("_archivo"), F.desc("last_update"))
    latest = (
        valid.drop("_next_renewal_texto")
        .withColumn("_n", F.row_number().over(newest_first))
        .where("_n = 1")
        .drop("_n")
    )

    # 7. Silver: MERGE = "si el LEI ya está y lo que llega es más nuevo (misma regla del paso 6),
    #    reemplazalo; si no está, agregalo". Si llega algo igual o más viejo, no se toca:
    #    repetir una corrida no cambia nada, y el orden en que llegan los archivos no importa.
    #    La tabla ya existe (paso 0): la primera corrida es un MERGE contra una tabla vacía.
    latest.createOrReplaceTempView("latest")
    spark.sql(f"""
        MERGE INTO {silver} AS t
        USING latest AS s
        ON t.lei = s.lei
        WHEN MATCHED AND (
            s._archivo > t._archivo
            OR (s._archivo = t._archivo AND s.last_update > t.last_update)
        ) THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

    # 8. El registro, al final: si algo falló antes, el archivo se vuelve a procesar entero.
    summary = batch.groupBy(F.col("_archivo").alias("archivo")).agg(
        F.count("*").alias("filas"),
        F.count("motivo").alias("rechazadas"),  # count de una columna no cuenta los nulos
    )
    summary.withColumn("procesado_en", F.current_timestamp()).writeTo(processed).append()
    for row in summary.orderBy("archivo").collect():
        print(f"{row['archivo']}: {row['filas']} filas, {row['rechazadas']} a cuarentena")


def fill_missing_names():
    """Las filas cargadas antes de que existiera nombre_normalizado (hito 5C) lo tienen vacío.

    Se completan una sola vez, con un MERGE que solo toca esa columna. Después ya no queda
    ninguna vacía y no se escribe nada. Cuando haya corrido, se puede sacar en un PR de
    limpieza.
    """
    missing = spark.table(silver).where(F.col("nombre_normalizado").isNull())
    if missing.limit(1).count() == 0:
        return
    missing.select(
        "lei", normalize("legal_name").alias("nombre_normalizado")
    ).createOrReplaceTempView("nombres")
    spark.sql(f"""
        MERGE INTO {silver} AS t
        USING nombres AS s
        ON t.lei = s.lei
        WHEN MATCHED THEN UPDATE SET t.nombre_normalizado = s.nombre_normalizado
    """)
    print("nombre_normalizado completado en las filas que lo tenían vacío")


# 0. Las tablas, con su DDL (no con lo que traiga el primer DataFrame).
create_tables()

# 1. ¿Qué archivos de bronze faltan procesar?
in_bronze = {row["_archivo"] for row in spark.table(bronze).select("_archivo").distinct().collect()}
done = {row["archivo"] for row in spark.table(processed).select("archivo").collect()}
pending = sorted(in_bronze - done)
print(f"Archivos para procesar: {pending}")

if pending:
    process(pending)
else:
    print("Nada nuevo en bronze: no se escribe nada")

# 9. Una sola vez, después de la migración del 5C: completar la columna nueva.
fill_missing_names()
