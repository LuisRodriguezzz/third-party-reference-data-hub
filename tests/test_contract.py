"""Tests del contrato de silver, sin Spark."""

import pytest

from refhub.contract import (
    PROCESSED_SCHEMA,
    QUARANTINE_SCHEMA,
    SILVER_SCHEMA,
    latest_per_lei,
    parse_timestamp,
    row_problem,
)
from refhub.schema import create_table_sql
from refhub.sources.gleif import COLUMNS

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


# ---------------------------------------------------------------- Estructura


def nombres(schema):
    return [c.name for c in schema]


def test_silver_tiene_las_columnas_de_gleif_y_el_linaje():
    # Si se suma una columna a COLUMNS (gleif.py), este test pide declararla en silver.
    assert nombres(SILVER_SCHEMA) == [*COLUMNS.values(), "_archivo", "_fecha_publicacion"]


def test_la_cuarentena_tiene_lo_mismo_mas_el_motivo():
    assert nombres(QUARANTINE_SCHEMA) == [*nombres(SILVER_SCHEMA), "motivo", "_procesado_en"]
    # En cuarentena los datos quedan como texto: por algo no se pudieron tipar.
    assert {c.type for c in QUARANTINE_SCHEMA[: len(COLUMNS)]} == {"string"}


def test_las_fechas_de_silver_son_timestamp():
    tipos = {c.name: c.type for c in SILVER_SCHEMA}
    assert tipos["last_update"] == tipos["next_renewal"] == "timestamp"


@pytest.mark.parametrize("campo", COLUMNS.values())
def test_not_null_en_silver_si_y_solo_si_el_contrato_exige_el_campo(campo):
    # Estructura y validez cuentan la misma historia: si row_problem rechaza la fila cuando
    # el campo falta, el campo es NOT NULL en silver; si la deja pasar, acepta nulos.
    acepta_nulos = {c.name: c.nullable for c in SILVER_SCHEMA}
    rechaza_si_falta = row_problem({**VALIDA, campo: None}) is not None
    assert acepta_nulos[campo] is not rechaza_si_falta


@pytest.mark.parametrize("schema", [SILVER_SCHEMA, QUARANTINE_SCHEMA, PROCESSED_SCHEMA])
def test_cada_tabla_tiene_su_create_table(schema):
    sql = create_table_sql("glue_catalog.db.t", schema)
    assert sql.count(" COMMENT ") == len(schema)  # todas las columnas documentadas


def test_el_create_table_de_silver_fija_los_tipos():
    sql = create_table_sql("glue_catalog.refhub_silver_dev.gleif_lei", SILVER_SCHEMA)
    assert "`lei` string NOT NULL" in sql
    assert "`last_update` timestamp NOT NULL" in sql
    assert "`next_renewal` timestamp COMMENT" in sql  # acepta nulos: sin NOT NULL
