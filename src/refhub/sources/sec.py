"""Fuente SEC: las empresas que cotizan en EE. UU., con su CIK, nombre, ticker y bolsa."""

import urllib.request
from email.utils import parsedate_to_datetime

from refhub.landing import upload

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"


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
