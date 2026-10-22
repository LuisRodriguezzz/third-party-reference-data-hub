"""Fuente OpenFIGI: para cada ISIN de acciones de EE. UU., su ticker y su FIGI en EE. UU.

Es el eslabón que permite cruzar por códigos: ticker de la SEC -> OpenFIGI -> ISIN -> LEI.
OpenFIGI no publica un archivo: se le pregunta por la API de mapeo, de a lotes.
"""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime

MAPPING_URL = "https://api.openfigi.com/v3/mapping"

# Límites de OpenFIGI con clave: hasta 100 trabajos por pedido (más -> 413) y 25 pedidos cada
# 6 segundos (más -> 429). Un pedido cada 0,25 s da 24 cada 6 s: justo por debajo del límite.
BATCH_SIZE = 100
MIN_INTERVAL = 0.25
DEFAULT_WAIT = 6.0  # si un 429 no dice cuánto esperar, lo que dura la ventana del límite
MAX_RETRIES = 5


def batches(isins: list[str], size: int = BATCH_SIZE) -> list[list[str]]:
    """Corta la lista en lotes de `size` como máximo: un lote = un pedido a OpenFIGI."""
    return [isins[i : i + size] for i in range(0, len(isins), size)]


def request_body(isins: list[str]) -> list[dict[str, str]]:
    """Un trabajo por ISIN. exchCode "US" pide el listado compuesto de EE. UU., no el de cada
    bolsa (sin él, Apple devuelve una fila por bolsa: Nasdaq, NYSE Arca, ...)."""
    return [{"idType": "ID_ISIN", "idValue": isin, "exchCode": "US"} for isin in isins]


def _pick(data: list[dict]) -> dict:
    """Si vienen varias filas, la que es su propio compuesto (figi == compositeFIGI): es el
    listado de EE. UU. en su conjunto. Si ninguna lo es, la primera."""
    return next((item for item in data if item.get("figi") == item.get("compositeFIGI")), data[0])


def rows_from_response(isins: list[str], response: list[dict]) -> list[dict]:
    """Una fila por ISIN mandado, con las columnas de silver.openfigi_tickers (sin el linaje,
    que lo agrega el job).

    La respuesta no trae el ISIN: el elemento i corresponde al trabajo i. Si no vienen tantos
    elementos como ISIN, emparejar por posición pondría tickers en ISIN equivocados: mejor parar.
    """
    if len(response) != len(isins):
        raise ValueError(f"Mandé {len(isins)} ISIN y OpenFIGI respondió {len(response)} elementos")
    rows = []
    for isin, item in zip(isins, response, strict=True):
        data = item.get("data") or []
        chosen = _pick(data) if data else {}
        rows.append(
            {
                "isin": isin,
                "figi": chosen.get("figi"),
                "composite_figi": chosen.get("compositeFIGI"),
                "ticker": chosen.get("ticker"),
                "name": chosen.get("name"),
                "security_type": chosen.get("securityType2"),
                "market_sector": chosen.get("marketSector"),
                "resultados": len(data),
                # Sin resultado, el porqué: "No identifier found." (warning) o el error.
                "motivo": None if data else item.get("warning") or item.get("error"),
            }
        )
    return rows


def landing_key(now: datetime) -> str:
    """landing/openfigi/dt=2026-10-21/20261021T153000.jsonl: una consulta, un archivo.

    A diferencia de las otras fuentes, la fecha es la de la consulta (no hay un archivo publicado
    con su fecha): cada corrida es una foto nueva y no pisa las anteriores.
    """
    return f"landing/openfigi/dt={now.date().isoformat()}/{now:%Y%m%dT%H%M%S}.jsonl"


def _wait_seconds(headers) -> float:
    """Cuánto esperar después de un 429: lo que diga OpenFIGI, o la ventana entera."""
    for name in ("ratelimit-reset", "Retry-After"):
        try:
            return float(headers.get(name))
        except (TypeError, ValueError):
            continue
    return DEFAULT_WAIT


def _post(api_key: str, isins: list[str]) -> list[dict]:
    request = urllib.request.Request(
        MAPPING_URL,
        data=json.dumps(request_body(isins)).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-OPENFIGI-APIKEY": api_key},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as resp:
        return json.load(resp)


def fetch_all(api_key: str, isins: list[str]) -> list[tuple[list[str], list[dict]]]:
    """Pregunta todos los ISIN, de a lotes y a ritmo. Devuelve (ISIN del lote, respuesta).

    Ante un 429 espera y reintenta; si un lote sigue rechazado después de MAX_RETRIES, falla:
    una foto con lotes salteados parecería completa y no lo sería.
    """
    results = []
    last_request = 0.0
    for batch in batches(isins):
        for _ in range(MAX_RETRIES + 1):
            # Cada intento cuenta para el límite, también los rechazados: todos van a ritmo.
            time.sleep(max(0.0, last_request + MIN_INTERVAL - time.monotonic()))
            last_request = time.monotonic()
            try:
                results.append((batch, _post(api_key, batch)))
                break
            except urllib.error.HTTPError as err:
                if err.code != 429:
                    raise
                time.sleep(_wait_seconds(err.headers))
        else:
            raise RuntimeError(
                f"OpenFIGI siguió respondiendo 429 al lote que empieza en {batch[0]} "
                f"después de {MAX_RETRIES} reintentos"
            )
    return results
