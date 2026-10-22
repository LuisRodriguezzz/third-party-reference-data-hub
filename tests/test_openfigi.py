"""Reglas de OpenFIGI: lotes de 100, emparejar por posición, qué fila se elige y el motivo."""

import pytest

from refhub.sources.openfigi import batches, rows_from_response

APPLE = {
    "figi": "BBG000B9XRY4",
    "compositeFIGI": "BBG000B9XRY4",
    "ticker": "AAPL",
    "name": "APPLE INC",
    "securityType2": "Common Stock",
    "marketSector": "Equity",
}


def test_lotes_de_100_como_maximo():
    # Más de 100 trabajos en un pedido -> 413, y además cuenta para el límite de ritmo.
    isins = [f"US{i:010d}" for i in range(250)]
    lotes = batches(isins)
    assert [len(lote) for lote in lotes] == [100, 100, 50]
    assert sum(lotes, []) == isins  # sin perder ni reordenar ninguno


def test_empareja_por_posicion():
    # La respuesta no trae el ISIN: el segundo elemento es del segundo ISIN mandado.
    filas = rows_from_response(
        ["US0378331005", "US0000000002"],
        [{"data": [APPLE]}, {"warning": "No identifier found."}],
    )
    assert [(f["isin"], f["ticker"]) for f in filas] == [
        ("US0378331005", "AAPL"),
        ("US0000000002", None),
    ]


def test_falla_si_no_vienen_tantas_respuestas_como_isin():
    with pytest.raises(ValueError):
        rows_from_response(["US0378331005", "US0000000002"], [{"data": [APPLE]}])


def test_entre_varias_filas_gana_la_compuesta():
    bolsa = {**APPLE, "figi": "BBG000B9Y5X2"}  # un listado de una bolsa, no el compuesto
    (fila,) = rows_from_response(["US0378331005"], [{"data": [bolsa, APPLE]}])
    assert fila["figi"] == "BBG000B9XRY4"
    assert fila["resultados"] == 2
    assert fila["motivo"] is None


def test_sin_compuesta_gana_la_primera():
    primera = {**APPLE, "figi": "BBG000000001", "ticker": "A1"}
    segunda = {**APPLE, "figi": "BBG000000002", "ticker": "A2"}
    (fila,) = rows_from_response(["US0378331005"], [{"data": [primera, segunda]}])
    assert fila["ticker"] == "A1"


@pytest.mark.parametrize(
    ("respuesta", "motivo"),
    [
        ({"warning": "No identifier found."}, "No identifier found."),
        ({"error": "Invalid idValue format."}, "Invalid idValue format."),
    ],
)
def test_sin_resultado_queda_la_fila_con_su_motivo(respuesta, motivo):
    (fila,) = rows_from_response(["US0000000002"], [respuesta])
    assert fila["figi"] is None
    assert fila["resultados"] == 0
    assert fila["motivo"] == motivo
