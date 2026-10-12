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
_COUNTRY = re.compile(r"[A-Z]{2}")  # código ISO 3166 de dos letras


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
