"""Fuente SEC: las empresas que cotizan en EE. UU., con su CIK, nombre, ticker y bolsa."""

import json
import re
import urllib.request
from datetime import date
from email.utils import parsedate_to_datetime

from refhub.landing import upload

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"

# Las columnas del archivo, en el orden en que vienen los valores de cada fila.
FIELDS = ["cik", "name", "ticker", "exchange"]

# company_tickers_exchange-20261007T203836.json -> la SEC lo actualizó el 2026-10-07.
_FILE_NAME = re.compile(r"company_tickers_exchange-(\d{4})(\d{2})(\d{2})T\d{6}\.json")


def headers(contact: str) -> dict[str, str]:
    """La SEC exige que cada pedido diga quién es y un mail de contacto; si no, bloquea la IP."""
    return {"User-Agent": f"refhub {contact}"}


def landing_key(last_modified: str) -> str:
    """'Wed, 07 Oct 2026 20:38:00 GMT' ->
    landing/sec/dt=2026-10-07/company_tickers_exchange-20261007T203800.json

    El nombre del archivo no trae fecha: se usa la de su última actualización (Last-Modified),
    que la pone la SEC. Si la SEC no lo cambió, la clave es la misma y no se baja de nuevo.
    """
    ts = parsedate_to_datetime(last_modified)
    return (
        f"landing/sec/dt={ts.date().isoformat()}/company_tickers_exchange-{ts:%Y%m%dT%H%M%S}.json"
    )


def last_modified(contact: str) -> str:
    """Pregunta solo los encabezados (HEAD) para saber cuándo cambió el archivo."""
    request = urllib.request.Request(TICKERS_URL, method="HEAD", headers=headers(contact))
    with urllib.request.urlopen(request, timeout=30) as resp:
        return resp.headers["Last-Modified"]


def upload_latest(s3, bucket: str, contact: str) -> dict[str, str]:
    """Sube a landing la lista de empresas de la SEC. Si no cambió, no hace nada."""
    key = landing_key(last_modified(contact))
    return upload(s3, bucket, TICKERS_URL, key, headers(contact))


def publish_date(file_name: str) -> date:
    """Fecha en que la SEC actualizó el archivo, según el nombre que le dio landing_key."""
    match = _FILE_NAME.fullmatch(file_name)
    if match is None:
        raise ValueError(f"No encuentro la fecha de actualización en {file_name!r}")
    return date(*(int(part) for part in match.groups()))


def parse(text: str) -> list[dict[str, str | None]]:
    """El JSON de la SEC -> una fila (dict) por ticker, con los valores como texto.

    El archivo no es una lista de filas sino una tabla compacta:
    {"fields": ["cik", "name", "ticker", "exchange"],
     "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"], ...]}

    Los valores quedan como texto, tal cual vinieron (el CIK 320193 pasa a "320193"): el
    contrato decide si sirven, y la cuarentena guarda el original.
    """
    document = json.loads(text)
    if document["fields"] != FIELDS:
        # Los valores vienen por posición: si la SEC cambia las columnas, cada dato caería en
        # la columna equivocada. Mejor parar.
        raise ValueError(f"La SEC cambió las columnas del archivo: {document['fields']}")
    return [
        {
            field: None if value is None else str(value)
            for field, value in zip(FIELDS, values, strict=True)
        }
        for values in document["data"]
    ]
