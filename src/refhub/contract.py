"""Contratos de silver: qué tiene que cumplir una fila de cada fuente para pasar a silver.

Si una fila no cumple, no se tira: va a la tabla de cuarentena con el motivo (y el original
sigue en bronze o en landing).
"""

import re
from collections.abc import Iterable
from datetime import datetime

from refhub.isin import isin_problem
from refhub.lei import lei_problem

# Valores posibles según el formato de GLEIF (LEI-CDF 3.1).
ENTITY_STATUSES = frozenset({"ACTIVE", "INACTIVE", "NULL"})
REGISTRATION_STATUSES = frozenset(
    {
        "PENDING_VALIDATION",
        "ISSUED",
        "DUPLICATE",
        "LAPSED",
        "MERGED",
        "RETIRED",
        "ANNULLED",
        "CANCELLED",
        "TRANSFERRED",
        "PENDING_TRANSFER",
        "PENDING_ARCHIVAL",
    }
)
# Nivel 2 (relationship records), según el formato RR-CDF 2.1 de GLEIF.
RELATIONSHIP_TYPES = frozenset(
    {
        "IS_DIRECTLY_CONSOLIDATED_BY",  # la controlante directa
        "IS_ULTIMATELY_CONSOLIDATED_BY",  # la controlante final: la cabeza del grupo
        "IS_INTERNATIONAL_BRANCH_OF",
        "IS_FUND-MANAGED_BY",
        "IS_SUBFUND_OF",
        "IS_FEEDER_TO",
    }
)
RELATIONSHIP_STATUSES = frozenset({"ACTIVE", "INACTIVE", "NULL"})
# El registro de una relación tiene sus propios estados: PUBLISHED en vez del ISSUED de un LEI.
RELATIONSHIP_REGISTRATION_STATUSES = frozenset(
    {
        "PENDING_VALIDATION",
        "PUBLISHED",
        "DUPLICATE",
        "LAPSED",
        "RETIRED",
        "ANNULLED",
        "TRANSFERRED",
        "PENDING_TRANSFER",
        "PENDING_ARCHIVAL",
    }
)
_COUNTRY = re.compile(r"[A-Z]{2}")  # código ISO 3166 de dos letras
_CIK = re.compile(r"[0-9]{1,10}")  # el CIK de la SEC: un número de hasta 10 dígitos
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]*")  # AAPL, BRK-B


def parse_timestamp(value: str | None) -> datetime | None:
    """'2026-10-01T10:00:00.123+02:00' o '...Z' -> datetime con zona; None si no se puede.

    GLEIF manda las fechas con distintos husos horarios. Compararlas como texto da mal:
    '10:00+02:00' parece más nuevo que '09:00Z', pero es una hora antes.
    """
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo is not None else None  # sin huso horario no sabemos qué hora es


def row_problem(row: dict[str, str | None]) -> str | None:
    """Devuelve el motivo por el que la fila no cumple el contrato, o None si lo cumple.

    Las reglas se revisan en orden y se devuelve la primera que falla.
    """
    problem = lei_problem(row["lei"])
    if problem is not None:
        return f"lei_{problem}"
    if not (row["legal_name"] or "").strip():
        return "nombre_vacio"
    if not _COUNTRY.fullmatch(row["country"] or ""):
        return "pais_invalido"
    if row["entity_status"] not in ENTITY_STATUSES:
        return "estado_entidad_desconocido"
    if row["registration_status"] not in REGISTRATION_STATUSES:
        return "estado_registro_desconocido"
    if parse_timestamp(row["last_update"]) is None:
        return "fecha_actualizacion_invalida"
    if row["next_renewal"] and parse_timestamp(row["next_renewal"]) is None:
        return "fecha_renovacion_invalida"
    return None


def latest_per_lei(rows: Iterable[dict[str, str | None]]) -> list[dict[str, str | None]]:
    """Una fila por LEI: la del archivo más nuevo; dentro de un mismo archivo, la de fecha de
    actualización más nueva. Es la regla que el job de silver aplica con una ventana de Spark
    y con el MERGE.

    Gana lo que GLEIF publicó último (el nombre del archivo empieza con la fecha y hora de
    publicación), no la fecha de actualización más alta: esa fecha la pone cada LOU y puede ir
    para atrás. Si una transferencia entre LOUs no se concreta, el LEI vuelve con el registro
    de la LOU original, que tiene una fecha más vieja que la del pedido de transferencia.
    """
    best: dict[str, tuple[tuple[str, datetime], dict[str, str | None]]] = {}
    for row in rows:
        key = (row["_archivo"], parse_timestamp(row["last_update"]))
        current = best.get(row["lei"])
        if current is None or key > current[0]:
            best[row["lei"]] = (key, row)
    return [row for _, row in best.values()]


def isin_lei_problem(row: dict[str, str | None]) -> str | None:
    """Contrato de ISIN↔LEI: el ISIN y el LEI con su formato y su dígito verificador.

    Devuelve el primer motivo que encuentra (primero el ISIN), o None si la fila cumple.
    """
    problem = isin_problem(row["isin"])
    if problem is not None:
        return f"isin_{problem}"
    problem = lei_problem(row["lei"])
    if problem is not None:
        return f"lei_{problem}"
    return None


def relationship_problem(row: dict[str, str | None]) -> str | None:
    """Contrato de las relaciones de GLEIF (nivel 2). Devuelve el primer motivo, o None si cumple.

    Los dos LEIs tienen que ser válidos: una relación con un LEI roto no se puede unir con
    gleif_lei, y si fuera el de la controlante, la empresa quedaría en un grupo que no existe.
    El tipo, los estados y las fechas, porque gold va a filtrar por ellos (la controlante
    final, la relación activa y vigente): un valor desconocido se perdería en silencio.
    """
    for side in ("child_lei", "parent_lei"):
        problem = lei_problem(row[side])
        if problem is not None:
            return f"{side}_{problem}"
    if row["relationship_type"] not in RELATIONSHIP_TYPES:
        return "tipo_relacion_desconocido"
    if row["relationship_status"] not in RELATIONSHIP_STATUSES:
        return "estado_relacion_desconocido"
    if row["registration_status"] not in RELATIONSHIP_REGISTRATION_STATUSES:
        return "estado_registro_desconocido"
    if parse_timestamp(row["last_update"]) is None:
        return "fecha_actualizacion_invalida"
    # El período puede faltar (GLEIF no lo exige), pero si viene tiene que ser una fecha.
    if row["relationship_start"] and parse_timestamp(row["relationship_start"]) is None:
        return "fecha_inicio_invalida"
    if row["relationship_end"] and parse_timestamp(row["relationship_end"]) is None:
        return "fecha_fin_invalida"
    return None


def sec_problem(row: dict[str, str | None]) -> str | None:
    """Contrato de la SEC: CIK, nombre y ticker. Devuelve el primer motivo, o None si cumple.

    La bolsa no se valida: la SEC la deja vacía en algunos tickers (176 de 10.435 en el archivo
    del 7-oct) y no conviene una lista cerrada de bolsas: en ese mismo archivo ya aparece TXSE
    (la bolsa de Texas), y una lista la habría mandado a cuarentena sin que la fila tuviera
    nada malo.
    """
    cik = row["cik"] or ""
    if not _CIK.fullmatch(cik) or int(cik) == 0:
        return "cik_invalido"
    if not (row["name"] or "").strip():
        return "nombre_vacio"
    if not _TICKER.fullmatch(row["ticker"] or ""):
        return "ticker_invalido"
    return None
