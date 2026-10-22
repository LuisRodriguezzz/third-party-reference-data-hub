"""¿Esta aplicación puede usar este dataset para este propósito? El evaluador de licencias ODRL.

El catálogo (DCAT), las políticas (ODRL) y las aplicaciones están en `refhub/catalogo/*.ttl`.
`evaluar` responde una pregunta y dice con qué regla lo decidió; `compilar` responde todas de
antemano, para que la API no tenga que evaluar en caliente (ADR 0009 y 0012).

Necesita el extra `licencias` (`pip install refhub[licencias]`), que trae rdflib. No es una
dependencia obligatoria porque solo se usa al compilar, en el CI: ni los jobs de Glue ni la
Lambda de la API (que lee la tabla ya compilada, `refhub.permisos`) la necesitan.

Compilar la tabla que publica el CI y sirve la API:

    uv run --no-dev --extra licencias python -m refhub.licencias dist/decisiones.json

Semántica, cada punto con su criterio:

- **La prohibición gana sobre el permiso** (deny-overrides): si una regla prohíbe y otra
  permite, se niega. Es el algoritmo deny-overrides de XACML y la estrategia de conflicto
  `odrl:prohibit` de ODRL (la política ficticia la declara con `odrl:conflict`): ante la duda,
  lo que el contrato prohíbe pesa más.
- **Sin un permiso explícito, no** (default deny): una licencia enumera lo que se puede hacer; lo
  que no dice no está concedido.
- **Los propósitos respetan la jerarquía:** una regla para `uso_interno` vale también para
  `riesgo_credito`, que es un uso interno (`skos:broader`, ver aplicaciones.ttl).
- **Un derivado hereda las restricciones de sus fuentes:** se evalúa el dataset y todo su linaje
  hacia arriba (`prov:wasDerivedFrom`), y gana lo más restrictivo. Un dato derivado no puede
  tener más derechos que lo que lo originó.
"""

import json
import sys
from dataclasses import dataclass
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.namespace import DCAT, ODRL2, PROV, SKOS
from rdflib.plugins.sparql import prepareQuery

ARCHIVOS = ("catalogo.ttl", "politicas.ttl", "aplicaciones.ttl")


@dataclass(frozen=True)
class Decision:
    permitido: bool
    # "prohibicion", "permiso" o "sin_permiso" (default deny: no hay regla que citar).
    motivo: str
    # La regla ODRL que decidió; None cuando se niega porque ningún permiso alcanza.
    regla: URIRef | None
    # Dónde se decidió: el dataset pedido o la fuente de su linaje que lo restringe.
    decidido_en: URIRef
    # Lo que hay que cumplir para usar el dato (por ejemplo, citar a la SEC), de todo el linaje.
    obligaciones: tuple[URIRef, ...] = ()


def cargar() -> Graph:
    """El catálogo, las políticas y las aplicaciones en un solo grafo (viajan en el .whl)."""
    grafo = Graph()
    for nombre in ARCHIVOS:
        grafo.parse(data=_leer(nombre), format="turtle")
    return grafo


def consultar(grafo: Graph, nombre: str) -> list[tuple]:
    """Corre una consulta de `catalogo/consultas/<nombre>.rq` y devuelve las filas."""
    return [tuple(fila) for fila in grafo.query(_leer(f"consultas/{nombre}.rq"))]


# Las reglas de la política de un dataset, con lo que hace falta para saber si alcanzan a un
# pedido: la acción, la aplicación a la que se otorga (si la regla nombra una) y el propósito.
_REGLAS = prepareQuery(
    """
SELECT ?regla ?tipo ?accion ?asignatario ?proposito WHERE {
    VALUES ?tipo { odrl:permission odrl:prohibition }
    ?dataset odrl:hasPolicy ?politica .
    ?politica ?tipo ?regla .
    ?regla odrl:action ?accion .
    OPTIONAL { ?regla odrl:assignee ?asignatario }
    OPTIONAL {
        ?regla odrl:constraint ?restriccion .
        ?restriccion odrl:leftOperand odrl:purpose ;
            odrl:operator odrl:isA ;
            odrl:rightOperand ?proposito .
    }
}
ORDER BY ?regla
""",
    initNs={"odrl": ODRL2},
)  # se prepara una vez: compilar la corre cientos de veces


def evaluar(grafo: Graph, app: URIRef, dataset: URIRef, proposito: URIRef) -> Decision:
    """¿`app` puede usar `dataset` para `proposito`? Con la regla que lo decidió."""
    _exigir(grafo, app, dataset, proposito)
    incluido_en = set(grafo.transitive_objects(proposito, SKOS.broader))  # él y sus ancestros

    # El dataset pedido se usa directamente; sus fuentes, a través de un derivado.
    niveles = [(dataset, False)] + [(fuente, True) for fuente in _linaje(grafo, dataset)]
    prohibiciones, sin_permiso, permisos = [], [], []
    for nivel, es_fuente in niveles:
        reglas = _reglas(grafo, nivel, app, incluido_en, es_fuente)
        prohibiciones += [(r, nivel) for r, tipo in reglas if tipo == ODRL2.prohibition]
        permitidas = [r for r, tipo in reglas if tipo == ODRL2.permission]
        if permitidas:
            permisos.append((permitidas, nivel))
        else:
            sin_permiso.append(nivel)

    if prohibiciones:  # deny-overrides: una prohibición en cualquier nivel alcanza
        regla, nivel = prohibiciones[0]
        return Decision(False, "prohibicion", regla, nivel)
    if sin_permiso:  # default deny: un nivel sin permiso frena todo lo que deriva de él
        return Decision(False, "sin_permiso", None, sin_permiso[0])

    # Permitido. Las obligaciones son las de todos los permisos que alcanzaron, en todo el
    # linaje: si la golden copy trae datos de la SEC, hay que citar a la SEC.
    obligaciones = sorted(
        {deber for reglas, _ in permisos for r in reglas for deber in grafo.objects(r, ODRL2.duty)}
    )
    return Decision(True, "permiso", permisos[0][0][0], dataset, tuple(obligaciones))


def compilar(grafo: Graph) -> list[tuple[URIRef, URIRef, URIRef, Decision]]:
    """La tabla de decisiones: todas las combinaciones aplicación × dataset × propósito.

    Es lo que sirve la API (hito 8): responder es buscar una fila, no evaluar el grafo en cada
    pedido. Cuando cambia una política se vuelve a compilar.
    """
    apps = sorted(grafo.subjects(PROV.actedOnBehalfOf, None))
    datasets = sorted(grafo.objects(None, DCAT.dataset))
    propositos = sorted(grafo.subjects(SKOS.inScheme, None))
    return [
        (app, dataset, proposito, evaluar(grafo, app, dataset, proposito))
        for app in apps
        for dataset in datasets
        for proposito in propositos
    ]


def tabla_de_decisiones(grafo: Graph, version_politicas: str) -> dict:
    """La tabla compilada como JSON: lo que el CI publica y la API de permisos sirve (ADR 0012).

    Lo que el cliente manda (aplicación, dataset, propósito) y el dataset donde se decidió van
    por nombre corto (`motor_trading`), que es como los pide la API. La regla y las obligaciones
    van con su IRI completo: es su identidad en ODRL y lleva a la política en el catálogo.
    """
    return {
        # Las políticas viajan en el paquete, así que su versión es la del paquete: cada
        # decisión dice de qué versión salió, y esa versión no se pisa en S3.
        "version_politicas": version_politicas,
        "decisiones": [
            {
                "app": _nombre(app),
                "dataset": _nombre(dataset),
                "proposito": _nombre(proposito),
                "permitido": decision.permitido,
                "motivo": decision.motivo,
                "regla": str(decision.regla) if decision.regla else None,
                "decidido_en": _nombre(decision.decidido_en),
                "obligaciones": [str(o) for o in decision.obligaciones],
            }
            for app, dataset, proposito, decision in compilar(grafo)
        ],
    }


def _nombre(iri: URIRef) -> str:
    """`https://refhub.example.org/aplicacion/motor_trading` -> `motor_trading`."""
    return str(iri).rsplit("/", 1)[1]


def _reglas(
    grafo: Graph, dataset: URIRef, app: URIRef, incluido_en: set, es_fuente: bool
) -> list[tuple[URIRef, URIRef]]:
    """Las reglas de la política de `dataset` que alcanzan al pedido, como (regla, tipo)."""
    alcanzan = []
    for regla, tipo, accion, asignatario, proposito in grafo.query(
        _REGLAS, initBindings={"dataset": dataset}
    ):
        if asignatario is not None and asignatario != app:
            continue  # la regla se otorga a otra aplicación
        if proposito is not None and proposito not in incluido_en:
            continue  # la regla es para otro propósito (una regla sin propósito vale para todos)
        if tipo == ODRL2.permission and not _permiso_alcanza(accion, es_fuente):
            continue
        alcanzan.append((regla, tipo))
    return alcanzan


def _permiso_alcanza(accion: URIRef, es_fuente: bool) -> bool:
    """Qué acción tiene que conceder un permiso para alcanzar al pedido.

    Usar un derivado es ejercer `odrl:derive` sobre su fuente: el permiso de la fuente tiene que
    ser para derivar (o para cualquier uso). Usar el dataset directamente es cualquier acción
    menos derivar: un permiso para derivar no deja usar el feed en sí. Las prohibiciones, en
    cambio, alcanzan sea cual sea la acción: un derivado no puede tener más derechos que su
    origen.
    """
    if es_fuente:
        return accion in (ODRL2.use, ODRL2.derive)
    return accion != ODRL2.derive


def _linaje(grafo: Graph, dataset: URIRef) -> list[URIRef]:
    """Todo lo que está arriba de `dataset` en el linaje, sin el dataset mismo."""
    return sorted(set(grafo.transitive_objects(dataset, PROV.wasDerivedFrom)) - {dataset})


def _exigir(grafo: Graph, app: URIRef, dataset: URIRef, proposito: URIRef) -> None:
    """Un IRI mal escrito no puede terminar en una respuesta: con un permiso de cualquier uso,
    un propósito inexistente saldría permitido."""
    if (None, DCAT.dataset, dataset) not in grafo:
        raise ValueError(f"dataset desconocido: {dataset}")
    if (app, PROV.actedOnBehalfOf, None) not in grafo:
        raise ValueError(f"aplicación desconocida: {app}")
    if (proposito, SKOS.inScheme, None) not in grafo:
        raise ValueError(f"propósito desconocido: {proposito}")


def _leer(nombre: str) -> str:
    return files("refhub").joinpath(f"catalogo/{nombre}").read_text(encoding="utf-8")


if __name__ == "__main__":
    # El CI lo corre al publicar una versión: las políticas se evalúan acá, una vez, y no en
    # cada pedido a la API.
    destino = Path(sys.argv[1])
    tabla = tabla_de_decisiones(cargar(), version("refhub"))
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(tabla, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(tabla['decisiones'])} decisiones -> {destino}")
