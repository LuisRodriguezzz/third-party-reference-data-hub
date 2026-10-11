"""Tests de la carga del archivo completo, sin internet: la API de GLEIF es de mentira."""

import io
import json
from datetime import date

import pytest

from refhub.sources import gleif

FULL_URL = (
    "https://goldencopy.gleif.org/storage/golden-copy-files/2026/10/02/1283642/"
    "20261002-1600-gleif-goldencopy-lei2-golden-copy.csv.zip"
)


def test_latest_full_url_lee_la_url_del_archivo_completo(monkeypatch):
    # Lo mínimo de la respuesta real de la API: data -> lei2 -> full_file -> csv -> url
    respuesta = {"data": {"lei2": {"full_file": {"csv": {"url": FULL_URL}}}}}

    def fake_urlopen(url, timeout):
        return io.BytesIO(json.dumps(respuesta).encode())

    monkeypatch.setattr(gleif.urllib.request, "urlopen", fake_urlopen)
    assert gleif.latest_full_url() == FULL_URL


def test_el_archivo_completo_va_a_la_particion_de_su_fecha():
    assert gleif.landing_key(FULL_URL) == (
        "landing/gleif/dt=2026-10-02/20261002-1600-gleif-goldencopy-lei2-golden-copy.csv.zip"
    )


def test_publish_date():
    assert gleif.publish_date("20261002-1600-gleif-goldencopy-lei2-golden-copy.csv.zip") == date(
        2026, 10, 2
    )


def test_publish_date_falla_si_no_hay_fecha():
    with pytest.raises(ValueError):
        gleif.publish_date("golden-copy.csv.zip")
