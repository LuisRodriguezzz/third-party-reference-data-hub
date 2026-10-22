"""Genera cartera_sintetica.csv: una cartera de préstamos INVENTADA para probar la exposición por
grupo económico (ADR 0013).

Los LEIs son reales (salen de silver en Athena); los montos, los productos y los préstamos son
inventados. No es la cartera de ningún banco y sus cifras no son un hallazgo: sirven solo para
que la pregunta "¿cuánto le prestamos a este grupo?" tenga algo que sumar.

Cómo está armada, para que la pregunta tenga sentido:
- 20 grupos reales (12 con la cabeza en la golden copy de la SEC y 8 sin), con préstamos chicos
  a varias de sus controladas: sumados, el grupo más expuesto supera a cualquier préstamo suelto.
- 150 empresas al azar con uno o dos préstamos de cualquier tamaño.

Es reproducible: las consultas ordenan por un hash del LEI (siempre el mismo orden) y el azar
tiene semilla fija. Con la misma foto de GLEIF en silver sale el mismo CSV. El CSV queda
versionado: si GLEIF cambia, el seed no cambia hasta que alguien vuelva a correr esto.

Se corre desde la raíz del repo, con credenciales de AWS (solo lee, en el workgroup refhub-dev):

    uv run --group dbt python dbt/seeds/generar_cartera.py
"""

import csv
import random
import time
from pathlib import Path

import boto3

SEMILLA = 20261021
SALIDA = Path(__file__).with_name("cartera_sintetica.csv")
PRODUCTOS = ["prestamo_comercial", "linea_de_credito", "leasing", "comercio_exterior"]

# Grupos con entre 5 y 200 controladas con el LEI vigente: los más grandes (miles de fondos o
# sucursales) no aportan nada que no muestren estos, y los chicos no tienen qué repartir.
CONSULTA_GRUPOS = """
with hijas as (
    select r.parent_lei, r.child_lei
    from refhub_silver_dev.gleif_relaciones as r
    inner join refhub_silver_dev.gleif_lei as hija
        on hija.lei = r.child_lei and hija.registration_status = 'ISSUED'
    where r.relationship_type = 'IS_ULTIMATELY_CONSOLIDATED_BY'
      and r.relationship_status = 'ACTIVE'
      and r.child_lei <> r.parent_lei
)
select
    hijas.parent_lei,
    max(empresas.lei is not null) as en_sec,
    array_join(array_sort(array_agg(hijas.child_lei)), ',') as controladas
from hijas
inner join refhub_silver_dev.gleif_lei as cabeza
    on cabeza.lei = hijas.parent_lei
left join (select distinct lei from refhub_gold_dev.empresas) as empresas
    on empresas.lei = hijas.parent_lei
group by hijas.parent_lei
having count(*) between 5 and 200
order by xxhash64(to_utf8(hijas.parent_lei))
"""

CONSULTA_SUELTAS = """
select lei
from refhub_silver_dev.gleif_lei
where registration_status = 'ISSUED'
order by xxhash64(to_utf8(lei))
limit 150
"""


def consultar(sql: str) -> list[list[str]]:
    """Corre una consulta de solo lectura en Athena y devuelve las filas sin el encabezado."""
    athena = boto3.client("athena", region_name="us-east-1")
    qid = athena.start_query_execution(QueryString=sql, WorkGroup="refhub-dev")["QueryExecutionId"]
    while True:
        estado = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if estado["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    if estado["State"] != "SUCCEEDED":
        raise RuntimeError(f"Athena: {estado['State']} {estado.get('StateChangeReason')}")
    filas = []
    for pagina in athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
        filas += [[c.get("VarCharValue") for c in f["Data"]] for f in pagina["ResultSet"]["Rows"]]
    return filas[1:]


def monto(azar: random.Random, minimo: float, maximo: float) -> float:
    """Un monto en USD redondeado a miles, como se anota un préstamo."""
    return round(azar.uniform(minimo, maximo), -3)


def main() -> None:
    azar = random.Random(SEMILLA)
    grupos = consultar(CONSULTA_GRUPOS)
    en_sec = [g for g in grupos if g[1] == "true"][:12]
    sin_sec = [g for g in grupos if g[1] == "false"][:8]

    prestamos = []  # (lei, monto, producto)
    totales_por_grupo = []
    for cabeza, _, controladas in en_sec + sin_sec:
        # Préstamos chicos repartidos en varias controladas: de a uno no llaman la atención.
        controladas = controladas.split(",")
        elegidas = azar.sample(controladas, min(len(controladas), azar.randint(4, 9)))
        del_grupo = [(lei, monto(azar, 500_000, 4_000_000)) for lei in elegidas]
        # A veces también se le presta a la cabeza.
        if azar.random() < 0.5:
            del_grupo.append((cabeza, monto(azar, 1_000_000, 8_000_000)))
        totales_por_grupo.append(sum(m for _, m in del_grupo))
        prestamos += [(lei, m, azar.choice(PRODUCTOS)) for lei, m in del_grupo]

    sueltas = [fila[0] for fila in consultar(CONSULTA_SUELTAS)]
    for lei in sueltas:
        prestamos.append((lei, monto(azar, 250_000, 12_000_000), azar.choice(PRODUCTOS)))
    # Algunas empresas tienen dos préstamos: préstamos y empresas no son lo mismo.
    for lei in azar.sample(sueltas, 15):
        prestamos.append((lei, monto(azar, 250_000, 3_000_000), azar.choice(PRODUCTOS)))

    # La razón de ser de la cartera: que mirar préstamo por préstamo no alcance.
    assert max(totales_por_grupo) > max(m for _, m, _ in prestamos), "ningún grupo supera"

    with SALIDA.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo, lineterminator="\n")
        escritor.writerow(["prestamo_id", "lei", "monto_usd", "producto"])
        for numero, (lei, m, producto) in enumerate(prestamos, start=1):
            escritor.writerow([f"P{numero:04d}", lei, f"{m:.2f}", producto])
    print(f"{len(prestamos)} préstamos a {len({p[0] for p in prestamos})} LEIs en {SALIDA.name}")


if __name__ == "__main__":
    main()
