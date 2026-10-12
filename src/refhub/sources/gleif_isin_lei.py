"""Fuente GLEIF ISIN↔LEI: qué títulos (ISIN) emitió cada empresa (LEI).

GLEIF lo publica junto con ANNA una vez por día, como una foto completa (no hay deltas).
"""

import json
import re
import urllib.request
from datetime import date

from refhub.landing import upload

LATEST_URL = "https://mapping.gleif.org/api/v2/isin-lei/latest"

# isin-lei-20261012T071510.zip -> publicado el 2026-10-12 a las 07:15:10 (UTC).
_FILE_NAME = re.compile(r"isin-lei-(\d{4})(\d{2})(\d{2})T\d{6}\.zip")


def landing_key(file_name: str) -> str:
    """Dónde se guarda: landing/gleif_isin_lei/dt=<fecha de publicación>/<nombre original>."""
    match = _FILE_NAME.fullmatch(file_name)
    if match is None:
        # Si GLEIF cambia el formato del nombre, mejor fallar que inventar una fecha.
        raise ValueError(f"No encuentro la fecha de publicación en {file_name!r}")
    published = date(*(int(part) for part in match.groups()))
    return f"landing/gleif_isin_lei/dt={published.isoformat()}/{file_name}"


def latest_file() -> tuple[str, str]:
    """Nombre y link de descarga del último archivo, según la API de GLEIF."""
    with urllib.request.urlopen(LATEST_URL, timeout=30) as resp:
        attributes = json.load(resp)["data"]["attributes"]
    return attributes["fileName"], attributes["downloadLink"]


def upload_latest(s3, bucket: str) -> dict[str, str]:
    """Sube a landing el último archivo ISIN↔LEI. Si ya estaba, no hace nada."""
    file_name, url = latest_file()
    return upload(s3, bucket, url, landing_key(file_name))
