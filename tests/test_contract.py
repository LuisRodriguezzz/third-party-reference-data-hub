"""Tests del contrato de silver, sin Spark."""

import pytest

from refhub.contract import (
    isin_lei_problem,
    latest_per_lei,
    parse_timestamp,
    row_problem,
    sec_problem,
)

VALIDA = {
    "lei": "HWUPKR0MPOU8FGXBT394",
    "legal_name": "Apple Inc.",
    "country": "US",
    "entity_status": "ACTIVE",
    "registration_status": "ISSUED",
    "last_update": "2026-09-30T14:02:51.123+02:00",
    "next_renewal": "2027-01-15T00:00:00Z",
}


def test_una_fila_valida_no_tiene_motivo():
    assert row_problem(VALIDA) is None


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("lei", "HWUPKR0MPOU8FGXBT395", "lei_digito_verificador"),
        ("legal_name", "   ", "nombre_vacio"),
        ("legal_name", None, "nombre_vacio"),  # Spark lee los campos vacíos como None
        ("country", "usa", "pais_invalido"),
        ("entity_status", "ACTIVO", "estado_entidad_desconocido"),
        ("registration_status", "", "estado_registro_desconocido"),
        ("last_update", "30/09/2026", "fecha_actualizacion_invalida"),
        ("last_update", "2026-09-30T14:02:51", "fecha_actualizacion_invalida"),  # sin huso
        ("next_renewal", "mañana", "fecha_renovacion_invalida"),
    ],
)
def test_cada_regla_da_su_motivo(campo, valor, motivo):
    assert row_problem({**VALIDA, campo: valor}) == motivo


def test_la_renovacion_puede_venir_vacia():
    assert row_problem({**VALIDA, "next_renewal": None}) is None


def test_parse_timestamp_entiende_los_husos():
    # 10:00 en +02:00 son las 08:00 UTC: una hora ANTES que 09:00Z
    assert parse_timestamp("2026-10-01T10:00:00+02:00") < parse_timestamp("2026-10-01T09:00:00Z")


def test_latest_per_lei_gana_el_archivo_mas_nuevo_aunque_su_fecha_sea_mas_vieja():
    # Caso real (LEI 74370055WK4U9VLVZH47): el 2-oct otra LOU pidió la transferencia; el 10-oct
    # el LEI volvió a la LOU original con su registro del 28-sep. Vale lo que GLEIF publicó último.
    pedido = {
        **VALIDA,
        "registration_status": "PENDING_TRANSFER",
        "last_update": "2026-10-02T10:12:08Z",
        "_archivo": "20261002-1600-gleif-goldencopy-lei2-last-day.csv.zip",
    }
    vuelta = {
        **VALIDA,
        "registration_status": "ISSUED",
        "last_update": "2026-09-28T14:39:07+03:00",
        "_archivo": "20261010-1600-gleif-goldencopy-lei2-golden-copy.csv.zip",
    }
    assert latest_per_lei([vuelta, pedido]) == [vuelta]


def test_latest_per_lei_en_un_mismo_archivo_gana_la_mas_nueva_en_utc():
    vieja = {**VALIDA, "last_update": "2026-10-01T10:00:00+02:00", "_archivo": "a.zip"}
    nueva = {**VALIDA, "last_update": "2026-10-01T09:00:00Z", "_archivo": "a.zip"}
    otra = {**VALIDA, "lei": "5493001KJTIIGC8Y1R12", "_archivo": "a.zip"}
    resultado = latest_per_lei([vieja, nueva, otra])
    assert len(resultado) == 2
    assert nueva in resultado  # como texto, "10:00+02:00" parecería más nueva: no lo es


def test_isin_lei_valido():
    assert isin_lei_problem({"isin": "US0378331005", "lei": "HWUPKR0MPOU8FGXBT394"}) is None


@pytest.mark.parametrize(
    ("isin", "lei", "motivo"),
    [
        ("US0378331006", "HWUPKR0MPOU8FGXBT394", "isin_digito_verificador"),
        ("US0378331005", "HWUPKR0MPOU8FGXBT395", "lei_digito_verificador"),
        ("US0378331006", "HWUPKR0MPOU8FGXBT395", "isin_digito_verificador"),  # primero el ISIN
    ],
)
def test_isin_lei_da_el_primer_motivo(isin, lei, motivo):
    assert isin_lei_problem({"isin": isin, "lei": lei}) == motivo


SEC = {"cik": "320193", "name": "Apple Inc.", "ticker": "AAPL", "exchange": "Nasdaq"}


@pytest.mark.parametrize(
    "cambio",
    [
        {},
        {"exchange": None},  # la SEC no siempre informa la bolsa
        {"exchange": "TXSE"},  # una bolsa nueva no es un error
        {"ticker": "BRK-B"},
    ],
)
def test_sec_validas(cambio):
    assert sec_problem({**SEC, **cambio}) is None


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        ("cik", None, "cik_invalido"),
        ("cik", "0", "cik_invalido"),
        ("cik", "320193.0", "cik_invalido"),  # vino como decimal
        ("cik", "12345678901", "cik_invalido"),  # más de 10 dígitos
        ("name", " ", "nombre_vacio"),
        ("ticker", "", "ticker_invalido"),
        ("ticker", "aapl", "ticker_invalido"),
    ],
)
def test_sec_invalidas(campo, valor, motivo):
    assert sec_problem({**SEC, campo: valor}) == motivo
