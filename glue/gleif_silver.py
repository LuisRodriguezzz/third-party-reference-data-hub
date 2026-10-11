"""Job de Glue: bronze.gleif_lei -> contrato -> silver.gleif_lei (tipada) + cuarentena.

Idempotente por archivo: procesa los archivos de bronze que no están en el registro
gleif_archivos_procesados, y cada escritura se puede repetir sin duplicar.

El contrato (refhub.contract, probado con pytest) se hace cumplir en dos niveles:
- estructura: las tablas se crean con su esquema declarado y ningún DataFrame se escribe
  si no trae exactamente esas columnas y tipos;
- validez: las reglas por fila (row_problem) deciden qué va a cuarentena.
"""

import sys
from importlib.metadata import version

from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import StringType

from refhub.bronze import column_name
from refhub.contract import PROCESSED_SCHEMA, QUARANTINE_SCHEMA, SILVER_SCHEMA, row_problem
from refhub.schema import create_table_sql, schema_problems
from refhub.sources.gleif import COLUMNS

args = getResolvedOptions(sys.argv, ["BRONZE_DB", "SILVER_DB"])
bronze = f"glue_catalog.{args['BRONZE_DB']}.gleif_lei"
silver = f"glue_catalog.{args['SILVER_DB']}.gleif_lei"
quarantine = f"glue_catalog.{args['SILVER_DB']}.gleif_lei_cuarentena"
processed = f"glue_catalog.{args['SILVER_DB']}.gleif_archivos_procesados"

# Cada tabla que escribe este job: su esquema declarado y por qué columna se particiona.
TABLES = {
    silver: (SILVER_SCHEMA, None),
    quarantine: (QUARANTINE_SCHEMA, "_archivo"),
    processed: (PROCESSED_SCHEMA, None),
}

spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue


def check_schema(df, table, check_nullable=False):
    """Frena si df no tiene exactamente las columnas y los tipos declarados para la tabla.

    La tabla ya rechaza sola lo peligroso (texto en una columna timestamp, un nulo en una
    NOT NULL), pero deja pasar conversiones silenciosas: una fecha (date) en una columna
    timestamp, un número en una de texto. Y el MERGE con UPDATE SET * ignora sin avisar las
    columnas de más. Este chequeo cierra esos huecos y dice qué columna falló.
    """
    actual = [(f.name, f.dataType.simpleString(), f.nullable) for f in df.schema.fields]
    problems = schema_problems(TABLES[table][0], actual, check_nullable=check_nullable)
    if problems:
        raise ValueError(f"{table} no coincide con su esquema declarado: {'; '.join(problems)}")
    return df


def create_tables():
    """Paso 0: crea las tablas que falten con su esquema declarado y revisa las que ya estaban."""
    for table, (schema, partition) in TABLES.items():
        spark.sql(create_table_sql(table, schema, partitioned_by=partition))
        # IF NOT EXISTS no toca una tabla que ya existe. Si el esquema declarado cambió (o
        # alguien cambió la tabla a mano), mejor enterarse acá, antes de escribir nada:
        # cambiar una tabla que ya tiene datos es una migración aparte (ALTER TABLE).
        check_schema(spark.table(table), table, check_nullable=True)


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
    rejected = batch.where(F.col("motivo").isNotNull()).withColumn(
        "_procesado_en", F.current_timestamp()
    )
    check_schema(rejected, quarantine).writeTo(quarantine).overwritePartitions()

    # 5. Las válidas, tipadas: los textos de fecha pasan a timestamp (en UTC).
    valid = (
        batch.where(F.col("motivo").isNull())
        .drop("motivo")
        .withColumn("_next_renewal_texto", F.col("next_renewal"))  # para el chequeo de abajo
        .withColumn("last_update", F.to_timestamp("last_update"))
        .withColumn("next_renewal", F.to_timestamp("next_renewal"))
    )
    # El contrato dijo "fecha válida" pero Spark no la pudo convertir: mejor parar que dejar
    # un nulo. next_renewal puede venir vacía (la regla lo permite), pero si traía un texto y
    # quedó nula, se perdió un dato.
    lost_date = F.col("last_update").isNull() | (
        F.col("next_renewal").isNull() & (F.coalesce(F.col("_next_renewal_texto"), F.lit("")) != "")
    )
    if valid.where(lost_date).limit(1).count() > 0:
        raise ValueError("Hay fechas que el contrato aceptó y Spark no pudo convertir")
    valid = valid.drop("_next_renewal_texto")

    # 6. Una fila por LEI: la más nueva por fecha de actualización (y si empatan, el archivo
    #    más nuevo). Los deltas se solapan, así que el mismo LEI puede venir varias veces.
    newest_first = Window.partitionBy("lei").orderBy(F.desc("last_update"), F.desc("_archivo"))
    latest = valid.withColumn("_n", F.row_number().over(newest_first)).where("_n = 1").drop("_n")

    # 7. Silver: MERGE = "si el LEI ya está y lo que llega es más nuevo (misma regla del paso 6),
    #    reemplazalo; si no está, agregalo". Si llega algo igual o más viejo, no se toca:
    #    repetir una corrida no cambia nada, y el orden en que llegan los archivos no importa.
    #    La tabla ya existe (paso 0), así que la primera corrida es un MERGE contra una vacía.
    check_schema(latest, silver).createOrReplaceTempView("latest")
    spark.sql(f"""
        MERGE INTO {silver} AS t
        USING latest AS s
        ON t.lei = s.lei
        WHEN MATCHED AND (
            s.last_update > t.last_update
            OR (s.last_update = t.last_update AND s._archivo > t._archivo)
        ) THEN UPDATE SET *
        WHEN NOT MATCHED THEN INSERT *
    """)

    # 8. El registro, al final: si algo falló antes, el archivo se vuelve a procesar entero.
    summary = batch.groupBy(F.col("_archivo").alias("archivo")).agg(
        F.count("*").alias("filas"),
        F.count("motivo").alias("rechazadas"),  # count de una columna no cuenta los nulos
    )
    done_now = summary.withColumn("procesado_en", F.current_timestamp())
    check_schema(done_now, processed).writeTo(processed).append()
    for row in summary.orderBy("archivo").collect():
        print(f"{row['archivo']}: {row['filas']} filas, {row['rechazadas']} a cuarentena")


# 0. Las tablas, con su esquema declarado (no con el que traiga el primer DataFrame).
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
