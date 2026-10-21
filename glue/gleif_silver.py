"""Job de Glue: bronze.gleif_lei -> contrato -> silver.gleif_lei (tipada) + cuarentena.

Dos modos, como en dbt (ver docs/adr/0007):
- incremental (el de todos los días): procesa los archivos de bronze que no están en el registro
  gleif_archivos_procesados y los suma con un MERGE. Cada escritura se puede repetir sin duplicar.
- full refresh (--FULL_REFRESH true): procesa todos los archivos de bronze y reemplaza silver y el
  registro enteros, en un commit cada uno. Es para cuando cambia una regla y hay que recalcular.

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

# FULL_REFRESH tiene default "false" en Terraform: Step Functions llama sin argumentos.
args = getResolvedOptions(sys.argv, ["BRONZE_DB", "SILVER_DB", "FULL_REFRESH"])
if args["FULL_REFRESH"] not in ("true", "false"):  # un "True" o un "si" no pasa en silencio
    raise ValueError(f"--FULL_REFRESH tiene que ser true o false, no {args['FULL_REFRESH']!r}")
full_refresh = args["FULL_REFRESH"] == "true"
silver_db = f"glue_catalog.{args['SILVER_DB']}"
bronze = f"glue_catalog.{args['BRONZE_DB']}.gleif_lei"
silver = f"{silver_db}.gleif_lei"
quarantine = f"{silver_db}.gleif_lei_cuarentena"
processed = f"{silver_db}.gleif_archivos_procesados"

spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
print(f"Modo: {'full refresh' if full_refresh else 'incremental'}")
normalize = F.udf(normalize_name, StringType())  # la misma función que probás con pytest


def create_tables():
    """Paso 0: crea las tablas con su DDL, que viaja dentro del .whl (refhub/ddl/*.sql).

    IF NOT EXISTS: si la tabla ya existe, no la toca. Un ambiente nuevo nace con el esquema
    actual; cómo se cambia una tabla que ya tiene datos está en docs/adr/0007.
    """
    for name in [
        "silver_gleif_lei",
        "silver_gleif_lei_cuarentena",
        "silver_gleif_archivos_procesados",
    ]:
        ddl = files("refhub").joinpath(f"ddl/{name}.sql").read_text(encoding="utf-8")
        spark.sql(ddl.format(db=silver_db))


def process(file_names):
    """Pasos 2 a 8 para esos archivos: los pendientes, o todos si es un full refresh."""
    # 2. Las columnas que usa silver, con los nombres del hito 1 (COLUMNS de gleif.py).
    selection = [F.col(column_name(gleif)).alias(ours) for gleif, ours in COLUMNS.items()]
    batch = (
        spark.table(bronze)
        .where(F.col("_archivo").isin(file_names))
        .select(*selection, "_archivo", "_fecha_publicacion")
    )

    # 3. El contrato: la MISMA función que probás con pytest, aplicada a cada fila.
    problem = F.udf(lambda row: row_problem(row.asDict()), StringType())
    batch = batch.withColumn("motivo", problem(F.struct(*COLUMNS.values()))).cache()

    # 4. Cuarentena: las filas que no cumplen, con su motivo. Siguen intactas en bronze.
    #    Reemplaza la partición de cada archivo: reprocesar no duplica. Con overwrite y no con
    #    overwritePartitions, que solo reemplaza las particiones que traen filas: si un archivo
    #    reprocesado ya no tiene rechazadas, sus filas viejas quedarían. Así se borran aunque
    #    no venga ninguna (el filtro coincide con particiones enteras, como pide Iceberg).
    rejected = batch.where(F.col("motivo").isNotNull()).select(
        *COLUMNS.values(),
        "_archivo",
        "_fecha_publicacion",
        "motivo",
        F.current_timestamp().alias("_procesado_en"),
    )
    rejected.writeTo(quarantine).overwrite(F.col("_archivo").isin(file_names))

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

    # 7. Silver.
    #    Full refresh: latest ya tiene todos los archivos, así que ES la tabla entera.
    #    overwrite(True) = "borrá todas las filas y escribí estas", en un solo commit. Da lo
    #    mismo que las corridas incrementales (la regla de qué versión gana es la misma
    #    ventana), pero con las reglas de hoy aplicadas a todas las filas.
    #    Incremental: MERGE = "si el LEI ya está y lo que llega es más nuevo (misma regla del
    #    paso 6), reemplazalo; si no está, agregalo". Si llega algo igual o más viejo, no se
    #    toca: repetir una corrida no cambia nada, y el orden en que llegan los archivos no
    #    importa. Por eso reprocesar un archivo con MERGE no recalcula nada: hace falta el full
    #    refresh. La tabla ya existe (paso 0): la primera corrida es un MERGE contra una vacía.
    if full_refresh:
        latest.writeTo(silver).overwrite(F.lit(True))
    else:
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
    #    En el full refresh se reemplaza entero, como silver: los dos cuentan la misma historia.
    summary = batch.groupBy(F.col("_archivo").alias("archivo")).agg(
        F.count("*").alias("filas"),
        F.count("motivo").alias("rechazadas"),  # count de una columna no cuenta los nulos
    )
    summary = summary.withColumn("procesado_en", F.current_timestamp())
    if full_refresh:
        summary.writeTo(processed).overwrite(F.lit(True))
    else:
        summary.writeTo(processed).append()
    for row in summary.orderBy("archivo").collect():
        print(f"{row['archivo']}: {row['filas']} filas, {row['rechazadas']} a cuarentena")


# 0. Las tablas, con su DDL (no con lo que traiga el primer DataFrame).
create_tables()

# 1. ¿Qué archivos de bronze hay que procesar? Los que faltan, o todos en un full refresh.
in_bronze = {row["_archivo"] for row in spark.table(bronze).select("_archivo").distinct().collect()}
if full_refresh:
    to_process = sorted(in_bronze)
else:
    done = {row["archivo"] for row in spark.table(processed).select("archivo").collect()}
    to_process = sorted(in_bronze - done)
print(f"Archivos para procesar: {to_process}")

if to_process:
    process(to_process)
else:
    print("Nada nuevo en bronze: no se escribe nada")
