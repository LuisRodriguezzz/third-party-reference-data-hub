"""Exporta de Athena lo que necesitan los dos consumidores locales (OpenSearch y Oracle), en CSV.

Solo lee: cada consulta es un SELECT en el workgroup refhub-dev (que corta a 1 GB leído). Athena
ya deja el resultado como CSV en S3, así que no se pagina fila por fila: se baja ese archivo.

Los CSV van a una carpeta fuera del repo (por defecto ~/refhub-local/datos, o la que diga
REFHUB_LOCAL_DATOS): son datos, no código, y en Windows una ruta corta evita problemas.

    uv run --group local python local/exportar.py
"""

import os
import time
from pathlib import Path

import boto3

DATOS = Path(os.environ.get("REFHUB_LOCAL_DATOS", Path.home() / "refhub-local" / "datos"))

# La consolidación directa vigente, con el mismo criterio de "vigente" que gold.grupos (ADR 0013):
# relación ACTIVE y sin fecha de fin pasada. Una empresa que se declara su propia controlante no
# es una relación: si entrara, el árbol tendría un ciclo.
_DIRECTAS = """
    select child_lei, parent_lei
    from refhub_silver_dev.gleif_relaciones
    where relationship_type = 'IS_DIRECTLY_CONSOLIDATED_BY'
      and relationship_status = 'ACTIVE'
      and (relationship_end is null or relationship_end > current_timestamp)
      and child_lei <> parent_lei
"""

CONSULTAS = {
    # --- Para OpenSearch: la golden copy y los nombres de GLEIF de EE. UU. ---
    "empresas": """
        select cik, nombre_sec, lei, legal_name, country, registration_status,
               camino, conflicto, ambiguo
        from refhub_gold_dev.empresas
    """,
    # El CIK y el LEI ya están en empresas: de identificadores solo hacen falta los demás.
    "identificadores": """
        select cik, esquema, valor
        from refhub_gold_dev.identificadores
        where esquema in ('ISIN', 'FIGI', 'TICKER')
    """,
    # Las empresas de EE. UU. con el registro vigente o vencido sin renovar (LAPSED sigue siendo
    # la misma empresa). Las RETIRED, DUPLICATE o ANNULLED ya no son una contraparte posible.
    "gleif_us": """
        select lei, legal_name, registration_status
        from refhub_silver_dev.gleif_lei
        where country = 'US' and registration_status in ('ISSUED', 'LAPSED')
    """,
    # --- Para Oracle: el árbol de consolidación directa, los nombres y la cartera ---
    "relaciones_directas": _DIRECTAS,
    # Los nombres de todas las empresas que aparecen en el árbol o en la cartera.
    "entidades": f"""
        with directas as ({_DIRECTAS})
        select g.lei, g.legal_name, g.country
        from refhub_silver_dev.gleif_lei as g
        where g.lei in (select child_lei from directas)
           or g.lei in (select parent_lei from directas)
           or g.lei in (select lei from refhub_gold_dev.cartera_sintetica)
           or g.lei in (
               select controlante_final_lei from refhub_gold_dev.grupos
               where lei in (select lei from refhub_gold_dev.cartera_sintetica)
           )
    """,
    # Montos INVENTADOS (ADR 0013): la cartera sintética, tal cual está en gold.
    "cartera": """
        select prestamo_id, lei, monto_usd, producto
        from refhub_gold_dev.cartera_sintetica
    """,
    # La controlante final que publica GLEIF para cada empresa de la cartera (gold.grupos), para
    # comparar en Oracle el árbol recorrido con la cabeza publicada.
    "controlante_publicada": """
        select lei, controlante_final_lei
        from refhub_gold_dev.grupos
        where lei in (select lei from refhub_gold_dev.cartera_sintetica)
    """,
}


def exportar(athena, s3, nombre: str, sql: str) -> None:
    qid = athena.start_query_execution(QueryString=sql, WorkGroup="refhub-dev")["QueryExecutionId"]
    while True:
        ejecucion = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]
        estado = ejecucion["Status"]
        if estado["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    if estado["State"] != "SUCCEEDED":
        raise RuntimeError(f"{nombre}: {estado['State']} {estado.get('StateChangeReason')}")
    # s3://bucket/carpeta/<id>.csv: el CSV que Athena ya escribió, con encabezado.
    bucket, clave = ejecucion["ResultConfiguration"]["OutputLocation"][5:].split("/", 1)
    destino = DATOS / f"{nombre}.csv"
    s3.download_file(bucket, clave, str(destino))
    leidos = ejecucion["Statistics"]["DataScannedInBytes"] / 1e6
    print(f"{nombre}: {destino.stat().st_size / 1e6:.1f} MB de CSV, {leidos:.0f} MB leídos")


def main() -> None:
    DATOS.mkdir(parents=True, exist_ok=True)
    athena = boto3.client("athena", region_name="us-east-1")
    s3 = boto3.client("s3", region_name="us-east-1")
    for nombre, sql in CONSULTAS.items():
        exportar(athena, s3, nombre, sql)


if __name__ == "__main__":
    main()
