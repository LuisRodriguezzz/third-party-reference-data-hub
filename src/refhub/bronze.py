"""Bronze: lo que necesita el job de Glue para pasar un zip de landing a la tabla bronze.

Acá no hay Spark: son funciones chicas que se prueban con pytest, sin AWS.
"""

import re
import tempfile
import zipfile
from collections.abc import Iterable
from pathlib import Path


def column_name(header: str) -> str:
    """Nombre de columna para bronze: 'Entity.LegalName' -> 'entity_legalname'.

    Glue y Athena guardan los nombres en minúscula, y un punto en el nombre obliga a
    escribirlo entre comillas invertidas en cada consulta. Mejor normalizarlo una vez.
    """
    return re.sub(r"[^0-9a-z]+", "_", header.lower()).strip("_")


def column_names(headers: Iterable[str]) -> list[str]:
    """Normaliza todos los encabezados del CSV y falla si dos quedan con el mismo nombre."""
    names = [column_name(h) for h in headers]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise ValueError(f"Dos columnas quedan con el mismo nombre: {repeated}")
    return names


def file_name(key: str) -> str:
    """'landing/gleif/dt=2026-10-02/archivo.csv.zip' -> 'archivo.csv.zip'."""
    return key.rsplit("/", 1)[-1]


def pending_files(landing_keys: Iterable[str], loaded: Iterable[str]) -> list[str]:
    """Las claves de landing cuyo archivo todavía no está en bronze, de la más vieja a la más nueva.

    GLEIF pone fecha y hora al principio del nombre, así que ordenar por nombre es ordenar por
    fecha de publicación.
    """
    already = set(loaded)
    pending = [k for k in landing_keys if k.endswith(".csv.zip") and file_name(k) not in already]
    return sorted(pending, key=file_name)


def extract_csv(s3, bucket: str, zip_key: str) -> str:
    """Copia el CSV que hay dentro del zip a tmp/gleif/ en el mismo bucket y devuelve su clave.

    Spark no sabe leer .zip (sí .gz). El zip se baja al disco del job y el CSV se sube
    descomprimiéndolo de a pedazos: nunca está entero en memoria (son ~5 GB en el completo).
    """
    with tempfile.TemporaryDirectory() as tmp:
        local_zip = Path(tmp) / "archivo.zip"
        s3.download_file(bucket, zip_key, str(local_zip))
        with zipfile.ZipFile(local_zip) as zf:
            (name,) = zf.namelist()  # GLEIF pone un solo CSV por zip; si no, que falle
            csv_key = f"tmp/gleif/{name}"
            with zf.open(name) as csv_file:
                s3.upload_fileobj(csv_file, bucket, csv_key)
    return csv_key
