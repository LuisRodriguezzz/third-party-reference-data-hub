"""Tests del contrato de silver, sin Spark."""

import pytest

from refhub.contract import latest_per_lei, parse_timestamp, row_problem

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


def test_latest_per_lei_se_queda_con_la_mas_nueva_en_utc():
    vieja = {**VALIDA, "last_update": "2026-10-01T10:00:00+02:00", "_archivo": "b.zip"}
    nueva = {**VALIDA, "last_update": "2026-10-01T09:00:00Z", "_archivo": "a.zip"}
    otra = {**VALIDA, "lei": "5493001KJTIIGC8Y1R12", "_archivo": "a.zip"}
    resultado = latest_per_lei([vieja, nueva, otra])
    assert len(resultado) == 2
    assert nueva in resultado  # como texto, "10:00+02:00" parecería más nueva: no lo es


def test_latest_per_lei_si_empatan_gana_el_archivo_mas_nuevo():
    # Dos deltas seguidos traen el mismo registro, idéntico: queda uno solo.
    del_0800 = {**VALIDA, "_archivo": "20261002-0800-gleif-goldencopy-lei2-last-day.csv.zip"}
    del_1600 = {**VALIDA, "_archivo": "20261002-1600-gleif-goldencopy-lei2-last-day.csv.zip"}
    assert latest_per_lei([del_1600, del_0800]) == [del_1600]
