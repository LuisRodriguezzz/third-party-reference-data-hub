"""Las métricas del pipeline en CloudWatch, a partir del scorecard de gold.

Se publican con Embedded Metric Format (EMF): la Lambda imprime un JSON con una forma fija y
CloudWatch Logs lo convierte solo en métricas. No hace falta PutMetricData ni un permiso de
CloudWatch: alcanza con escribir el log.

Pocas y agregadas: cada métrica (cada combinación de nombre y dimensiones) se paga aparte, y el
free tier de CloudWatch cubre 10. El detalle por fuente queda en las tablas del scorecard.
"""

import json
import os
import time

NAMESPACE = "refhub"

# Cada métrica con su unidad de CloudWatch. Agregar una acá es sumar una métrica paga.
UNIDADES = {
    "fuentes_atrasadas": "Count",
    "filas_cuarentena": "Count",
    "empresas": "Count",
    "porcentaje_con_lei": "Percent",
    "conflictos": "Count",
    "ambiguos": "Count",
}


def calcular(fuentes: list[dict], cruce: dict) -> dict[str, float]:
    """Las métricas a partir de las filas de scorecard_fuentes y la fila de scorecard_cruce.

    Las filas vienen como las devuelve Athena: todos los valores son texto, y los nulos faltan
    o son None. Si atrasada es o no, lo decide la regla de scorecard_fuentes (dbt): acá solo se
    cuentan.
    """
    return {
        "fuentes_atrasadas": sum(1 for f in fuentes if f.get("atrasada") == "true"),
        # OpenFIGI no tiene cuarentena (nulo): cuenta como 0.
        "filas_cuarentena": sum(int(f.get("filas_cuarentena") or 0) for f in fuentes),
        "empresas": int(cruce["empresas"]),
        "porcentaje_con_lei": float(cruce.get("porcentaje_con_lei") or 0),
        "conflictos": int(cruce["conflictos"]),
        "ambiguos": int(cruce["ambiguos"]),
    }


def documento_emf(metricas: dict[str, float], ambiente: str, timestamp_ms: int) -> dict:
    """El JSON que CloudWatch convierte en métricas: los valores más el bloque _aws que dice
    cuáles de esos campos son métricas, con qué unidad y con qué dimensión."""
    return {
        "_aws": {
            "Timestamp": timestamp_ms,
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    # Una sola dimensión, el ambiente: una serie por métrica (y no una por fuente).
                    "Dimensions": [["ambiente"]],
                    "Metrics": [{"Name": nombre, "Unit": UNIDADES[nombre]} for nombre in metricas],
                }
            ],
        },
        "ambiente": ambiente,
        **metricas,
    }


def _consultar(athena, sql: str, workgroup: str) -> list[dict]:
    """Corre una consulta en Athena, espera a que termine y devuelve las filas como dicts."""
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup)["QueryExecutionId"]
    while True:
        estado = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if estado["State"] == "SUCCEEDED":
            break
        if estado["State"] in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"La consulta {qid} terminó en {estado['State']}: {estado}")
        time.sleep(1)
    # Las tablas del scorecard tienen 5 filas y 1: entran en una página de resultados.
    filas = athena.get_query_results(QueryExecutionId=qid)["ResultSet"]["Rows"]
    columnas = [c["VarCharValue"] for c in filas[0]["Data"]]  # la primera fila son los nombres
    # Un nulo viene como {} (sin VarCharValue) y queda None. Cada fila trae todas las columnas.
    return [
        dict(zip(columnas, [c.get("VarCharValue") for c in f["Data"]], strict=True))
        for f in filas[1:]
    ]


def handler(event, context):
    """Punto de entrada de la Lambda: lee el scorecard, imprime el EMF y devuelve las métricas."""
    import boto3  # viene en el runtime de Lambda; acá adentro para que los tests no lo pidan

    athena = boto3.client("athena")
    gold = os.environ["GOLD_DB"]
    workgroup = os.environ["ATHENA_WORKGROUP"]
    fuentes = _consultar(athena, f"select * from {gold}.scorecard_fuentes", workgroup)
    cruce = _consultar(athena, f"select * from {gold}.scorecard_cruce", workgroup)[0]

    metricas = calcular(fuentes, cruce)
    # Una línea de JSON en el log: CloudWatch la reconoce como EMF por el bloque _aws.
    print(json.dumps(documento_emf(metricas, os.environ["AMBIENTE"], int(time.time() * 1000))))
    return metricas  # Step Functions lo muestra como salida del paso
