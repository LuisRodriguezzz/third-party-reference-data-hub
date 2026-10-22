"""Job de Glue: los ISIN de acciones de EE. UU. de silver -> OpenFIGI -> silver.openfigi_tickers.

A diferencia de las otras fuentes, acá no hay un archivo que esperar en landing: el job le
pregunta a la API de OpenFIGI y guarda lo que respondió. Cada corrida es una foto nueva, así que
siempre recalcula todo y no lleva --FULL_REFRESH (no hay un "ya está en silver" que saltear).

Pasos: lee los ISIN de gleif_isin_lei y se queda con las acciones de EE. UU. (unos 77 mil; los
bonos no tienen ticker), los pregunta de a 100, guarda las respuestas crudas en landing/openfigi/
y reemplaza la tabla entera en un solo commit. Un ISIN sin resultado es una fila con su motivo:
no hace falta cuarentena.
"""

import json
import sys
from datetime import UTC, datetime
from importlib.metadata import version
from importlib.resources import files

import boto3
from awsglue.utils import getResolvedOptions
from pyspark.sql import SparkSession
from pyspark.sql import functions as F
from pyspark.sql.types import BooleanType

from refhub.bronze import file_name
from refhub.isin import is_us_equity
from refhub.sources.openfigi import fetch_all, landing_key, rows_from_response

args = getResolvedOptions(sys.argv, ["DATA_BUCKET", "SILVER_DB", "OPENFIGI_KEY_PARAM"])
bucket = args["DATA_BUCKET"]
silver_db = f"glue_catalog.{args['SILVER_DB']}"
table = f"{silver_db}.openfigi_tickers"

spark = SparkSession.builder.getOrCreate()
print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
s3 = boto3.client("s3")

# La clave vive en SSM y se lee al correr: no está en el código, ni en Terraform, ni en el state.
ssm = boto3.client("ssm")
parameter = ssm.get_parameter(Name=args["OPENFIGI_KEY_PARAM"], WithDecryption=True)
api_key = parameter["Parameter"]["Value"]

ddl = files("refhub").joinpath("ddl/silver_openfigi_tickers.sql").read_text(encoding="utf-8")
spark.sql(ddl.format(db=silver_db))

# La regla corre en Spark (la MISMA función que probás con pytest) sobre los 9 millones de filas;
# al driver llegan solo las acciones. Ordenados, para que dos corridas manden los mismos lotes.
us_equity = F.udf(is_us_equity, BooleanType())
isins = sorted(
    row["isin"]
    for row in spark.table(f"{silver_db}.gleif_isin_lei")
    .select("isin")
    .distinct()
    .where(us_equity("isin"))
    .collect()
)
if not isins:
    raise ValueError("No hay ISIN de acciones de EE. UU. en gleif_isin_lei: primero cargala")

now = datetime.now(UTC)
results = fetch_all(api_key, isins)

# Lo crudo primero, tal cual. Cada línea lleva los ISIN mandados junto a la respuesta: la
# respuesta sola no sirve, porque no dice a qué ISIN corresponde cada elemento.
key = landing_key(now)
raw = "".join(
    json.dumps({"isins": batch, "respuesta": response}) + "\n" for batch, response in results
)
s3.put_object(Bucket=bucket, Key=key, Body=raw.encode("utf-8"))

rows = [row for batch, response in results for row in rows_from_response(batch, response)]
foto = (
    spark.createDataFrame(
        rows,
        "isin string, figi string, composite_figi string, ticker string, name string, "
        "security_type string, market_sector string, resultados int, motivo string",
    )
    .withColumn("_archivo", F.lit(file_name(key)))
    .withColumn("_fecha_publicacion", F.lit(now.date()))
)

# overwrite(True) = "borrá todas las filas y escribí estas", en un solo commit: nadie ve la
# tabla a medias, y lo que OpenFIGI ya no devuelve desaparece.
foto.select(
    "isin",
    "figi",
    "composite_figi",
    "ticker",
    "name",
    "security_type",
    "market_sector",
    "resultados",
    "motivo",
    "_archivo",
    "_fecha_publicacion",
).writeTo(table).overwrite(F.lit(True))

errors = sum(1 for _, response in results for item in response if "error" in item)
with_ticker = sum(1 for row in rows if row["ticker"] is not None)
no_result = sum(1 for row in rows if row["resultados"] == 0) - errors
print(
    f"{file_name(key)}: {len(rows)} ISIN mandados, {with_ticker} con ticker, "
    f"{no_result} sin resultado, {errors} con error"
)
