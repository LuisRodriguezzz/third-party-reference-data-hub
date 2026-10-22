import json

import pytest

from refhub import licencias, permisos

POL = "https://refhub.example.org/politica/"


@pytest.fixture(scope="module")
def tabla():
    # La misma tabla que publica el CI, pasada por JSON como la lee la Lambda de S3.
    compilada = licencias.tabla_de_decisiones(licencias.cargar(), "0.0.0-test")
    return permisos.cargar(json.loads(json.dumps(compilada)))


def test_el_feed_ficticio_le_niega_el_trading_algoritmico_al_motor(tabla):
    respuesta = permisos.decidir(
        tabla,
        {
            "app": "motor_trading",
            "dataset": "precios_ficticios",
            "proposito": "trading_algoritmico",
        },
    )
    assert respuesta["permitido"] is False
    assert respuesta["regla"] == POL + "ficticio_prohibe_non_display"
    assert respuesta["decidido_en"] == "precios_ficticios"


def test_la_golden_copy_permite_riesgo_de_credito_citando_a_la_sec(tabla):
    respuesta = permisos.decidir(
        tabla,
        {"app": "riesgo_corporativo", "dataset": "gold_empresas", "proposito": "riesgo_credito"},
    )
    assert respuesta["permitido"] is True
    assert respuesta["obligaciones"] == [POL + "sec_citar_la_fuente"]


def test_cada_respuesta_dice_de_que_version_de_las_politicas_salio(tabla):
    respuesta = permisos.decidir(
        tabla, {"app": "portal_clientes", "dataset": "gleif_lei", "proposito": "producto_comercial"}
    )
    assert respuesta["version_politicas"] == "0.0.0-test"


@pytest.mark.parametrize(
    ("pedido", "campo"),
    [
        ({"app": "no_existe", "dataset": "gleif_lei", "proposito": "riesgo_credito"}, "app"),
        (
            {"app": "motor_trading", "dataset": "no_existe", "proposito": "riesgo_credito"},
            "dataset",
        ),
        ({"app": "motor_trading", "dataset": "gleif_lei", "proposito": "no_existe"}, "proposito"),
    ],
)
def test_un_nombre_desconocido_es_un_error_que_dice_cual_y_no_un_no(tabla, pedido, campo):
    with pytest.raises(permisos.PedidoInvalido, match=f"{campo} desconocido: 'no_existe'"):
        permisos.decidir(tabla, pedido)


def test_un_pedido_incompleto_es_un_error_que_dice_que_falta(tabla):
    with pytest.raises(permisos.PedidoInvalido, match="proposito"):
        permisos.decidir(tabla, {"app": "motor_trading", "dataset": "gleif_lei"})
