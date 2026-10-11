"""Contrato de GLEIF para silver: qué tiene que cumplir una fila de bronze para pasar a silver.

Tiene dos mitades:
- validez: las reglas por fila (row_problem). Si una fila no cumple, no se tira: va a la
  tabla de cuarentena con el motivo (y sigue en bronze);
- estructura: el esquema declarado de cada tabla que escribe el job (SILVER_SCHEMA y las
  demás, al final). El job crea las tablas con ese esquema y no escribe nada que no coincida.
"""

import re
from collections.abc import Iterable
from datetime import datetime

from refhub.lei import lei_problem
from refhub.schema import Column
from refhub.sources.gleif import COLUMNS

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
    """Una fila por LEI: la de fecha de actualización más nueva; si empatan, la del archivo
    más nuevo. Es la regla que el job de silver aplica con una ventana de Spark.
    """
    best: dict[str, tuple[tuple[datetime, str], dict[str, str | None]]] = {}
    for row in rows:
        key = (parse_timestamp(row["last_update"]), row["_archivo"])
        current = best.get(row["lei"])
        if current is None or key > current[0]:
            best[row["lei"]] = (key, row)
    return [row for _, row in best.values()]


# ---------------------------------------------------------------- Estructura: las tablas

# Linaje: de qué archivo de GLEIF salió cada fila. Lo comparten silver y la cuarentena.
_LINEAGE = (
    Column("_archivo", "string", "Linaje: archivo de GLEIF del que salió la fila"),
    Column("_fecha_publicacion", "date", "Linaje: fecha en que GLEIF publicó ese archivo"),
)

# Silver: lo que promete la tabla a quien la lea. Las columnas que row_problem exige son
# NOT NULL; next_renewal puede faltar porque la regla la deja pasar vacía (un test lo revisa).
# Las descripciones quedan en el catálogo de Glue y se ven desde Athena.
SILVER_SCHEMA = (
    Column("lei", "string", "LEI (ISO 17442), con dígito verificador válido. Una fila por LEI"),
    Column("legal_name", "string", "Nombre legal de la entidad"),
    Column("country", "string", "País de la dirección legal (ISO 3166-1, dos letras)"),
    Column("entity_status", "string", "Estado de la entidad: ACTIVE, INACTIVE o NULL (texto)"),
    Column("registration_status", "string", "Estado del registro en GLEIF: ISSUED, LAPSED..."),
    Column("last_update", "timestamp", "Última actualización del registro en GLEIF (UTC)"),
    Column("next_renewal", "timestamp", "Próxima renovación (UTC); vacía si no hay", nullable=True),
    *_LINEAGE,
)

# Cuarentena: las mismas columnas, pero como texto y tal cual venían de bronze (pueden faltar:
# por algo fallaron), más el motivo y cuándo se rechazaron.
QUARANTINE_SCHEMA = (
    *(
        Column(ours, "string", f"Tal cual en bronze (columna {gleif} de GLEIF)", nullable=True)
        for gleif, ours in COLUMNS.items()
    ),
    *_LINEAGE,
    Column("motivo", "string", "Primera regla del contrato que la fila no cumplió"),
    Column("_procesado_en", "timestamp", "Cuándo la mandó a cuarentena el job de silver (UTC)"),
)

# Registro de archivos procesados: lo que ya está acá no se vuelve a procesar.
PROCESSED_SCHEMA = (
    Column("archivo", "string", "Archivo de bronze ya procesado por el job de silver"),
    Column("filas", "bigint", "Filas que tenía el archivo"),
    Column("rechazadas", "bigint", "Cuántas de esas filas fueron a cuarentena"),
    Column("procesado_en", "timestamp", "Cuándo se procesó (UTC)"),
)
