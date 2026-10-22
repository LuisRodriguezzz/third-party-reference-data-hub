"""Fuente GLEIF nivel 2 (relationship records): quién consolida a quién.

Cada fila dice que una empresa (el "hijo", StartNode) tiene una relación con otra (el "padre",
EndNode): la controlante directa, la controlante final, la gestora de un fondo, etc. Con la
controlante final (IS_ULTIMATELY_CONSOLIDATED_BY) se arma el grupo económico con un join, sin
recorrer el árbol.

Se usa el archivo completo, como foto completa (igual que ISIN↔LEI): son ~23 MB en zip y unas
490 mil relaciones, y GLEIF lo publica entero en cada publicación. Con deltas habría que
aplicarlos en orden y nunca perder uno; con la foto, el último archivo ya es la verdad.
"""

import csv
import io
import json
import urllib.request
import zipfile
from collections.abc import Iterator

from refhub.landing import upload
from refhub.sources.gleif import PUBLISHES_URL, publish_date

# Columnas del CSV de GLEIF (tiene 54) -> nombre que usamos nosotros. Las que no están acá
# (el período y la norma contable) vienen repetidas en columnas numeradas: ver relationship().
COLUMNS = {
    "Relationship.StartNode.NodeID": "child_lei",
    "Relationship.EndNode.NodeID": "parent_lei",
    "Relationship.RelationshipType": "relationship_type",
    "Relationship.RelationshipStatus": "relationship_status",
    "Registration.RegistrationStatus": "registration_status",
    "Registration.ValidationSources": "validation_sources",
    "Registration.LastUpdateDate": "last_update",
}


def latest_full_url() -> str:
    """URL del último archivo completo de relaciones (tipo "rr" en la API de GLEIF)."""
    with urllib.request.urlopen(PUBLISHES_URL, timeout=30) as resp:
        data = json.load(resp)["data"]
    return data["rr"]["full_file"]["csv"]["url"]


def landing_key(url: str) -> str:
    """Dónde se guarda: landing/gleif_rr/dt=<fecha de publicación>/<nombre original>.

    El nombre tiene el mismo formato que el de nivel 1
    (20261021-1600-gleif-goldencopy-rr-golden-copy.csv.zip), así que la fecha sale igual.
    """
    name = url.rsplit("/", 1)[-1]
    return f"landing/gleif_rr/dt={publish_date(name).isoformat()}/{name}"


def upload_latest(s3, bucket: str) -> dict[str, str]:
    """Sube a landing el último archivo completo de relaciones. Si ya estaba, no hace nada."""
    url = latest_full_url()
    return upload(s3, bucket, url, landing_key(url))


def _by_type(raw: dict[str, str], group: str, kind_field: str, kind: str, field: str) -> str:
    """El valor de `field` en la repetición de `group` cuyo `kind_field` es `kind`; "" si no hay.

    GLEIF manda hasta 5 períodos y 5 calificadores por fila, en columnas numeradas
    (Relationship.Period.1.periodType, ...Period.2...), y el orden cambia de una fila a otra:
    el período de la relación es el 1 en unas y el 2 en otras. Por eso se busca por el tipo y
    no por la posición.
    """
    for i in range(1, 6):
        if raw.get(f"{group}.{i}.{kind_field}") == kind:
            return raw.get(f"{group}.{i}.{field}", "")
    return ""


def relationship(raw: dict[str, str]) -> dict[str, str | None]:
    """Una fila del CSV de GLEIF -> las columnas que usa silver, todavía como texto.

    Los campos vacíos pasan a None, como los lee Spark: así el contrato ve lo mismo acá y allá.
    """
    period = "Relationship.Period"
    qualifier = "Relationship.Qualifiers"
    row = {ours: raw.get(gleif, "") for gleif, ours in COLUMNS.items()}
    # El período en que la relación vale (no el contable ni el del documento presentado).
    row["relationship_start"] = _by_type(
        raw, period, "periodType", "RELATIONSHIP_PERIOD", "startDate"
    )
    row["relationship_end"] = _by_type(raw, period, "periodType", "RELATIONSHIP_PERIOD", "endDate")
    # Con qué norma contable se consolida (IFRS, US_GAAP...): solo en las consolidaciones.
    row["accounting_standard"] = _by_type(
        raw, qualifier, "QualifierDimension", "ACCOUNTING_STANDARD", "QualifierCategory"
    )
    return {name: value or None for name, value in row.items()}


def read_rows(zip_file) -> Iterator[dict[str, str | None]]:
    """Lee el CSV dentro del zip (una ruta o un archivo abierto) fila por fila."""
    with zipfile.ZipFile(zip_file) as zf:
        (name,) = zf.namelist()  # GLEIF pone un solo CSV por zip; si no, que falle
        with zf.open(name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            expected = {*COLUMNS, "Relationship.Period.1.periodType"}
            missing = sorted(expected - set(reader.fieldnames or []))
            if missing:
                # Si GLEIF cambia el formato, mejor fallar que llenar silver de vacíos.
                raise ValueError(f"Faltan columnas en {name}: {missing}")
            for raw_row in reader:
                yield relationship(raw_row)
