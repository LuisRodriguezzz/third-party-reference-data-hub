import pytest
from rdflib import Namespace

from refhub.licencias import cargar, compilar, consultar, evaluar

APP = Namespace("https://refhub.example.org/aplicacion/")
DS = Namespace("https://refhub.example.org/dataset/")
POL = Namespace("https://refhub.example.org/politica/")
PROP = Namespace("https://refhub.example.org/proposito/")


@pytest.fixture(scope="module")
def grafo():
    return cargar()


def test_cc0_permite_el_uso_comercial(grafo):
    decision = evaluar(grafo, APP.portal_clientes, DS.gleif_lei, PROP.producto_comercial)
    assert decision.permitido
    assert decision.regla == POL.gleif_cc0_cualquier_uso
    assert decision.obligaciones == ()  # CC0 no pide atribución


def test_la_sec_obliga_a_citar_la_fuente(grafo):
    decision = evaluar(grafo, APP.riesgo_corporativo, DS.sec_empresas, PROP.riesgo_credito)
    assert decision.permitido
    assert decision.obligaciones == (POL.sec_citar_la_fuente,)


def test_la_golden_copy_hereda_la_obligacion_de_citar_a_la_sec(grafo):
    decision = evaluar(grafo, APP.portal_clientes, DS.gold_empresas, PROP.publicacion_externa)
    assert decision.permitido
    assert POL.sec_citar_la_fuente in decision.obligaciones


def test_el_feed_ficticio_prohibe_el_uso_algoritmico(grafo):
    decision = evaluar(grafo, APP.motor_trading, DS.precios_ficticios, PROP.trading_algoritmico)
    assert not decision.permitido
    assert decision.regla == POL.ficticio_prohibe_non_display


def test_el_feed_ficticio_permite_el_display_interno_a_la_app_suscripta(grafo):
    decision = evaluar(grafo, APP.monitor_mercado, DS.precios_ficticios, PROP.display_interno)
    assert decision.permitido
    assert decision.regla == POL.ficticio_permite_display_interno


def test_el_display_del_feed_ficticio_es_solo_para_la_app_suscripta(grafo):
    decision = evaluar(grafo, APP.riesgo_corporativo, DS.precios_ficticios, PROP.display_interno)
    assert not decision.permitido
    assert decision.motivo == "sin_permiso"


def test_un_derivado_del_feed_ficticio_hereda_la_prohibicion_de_redistribuir(grafo):
    decision = evaluar(
        grafo, APP.portal_clientes, DS.precios_cierre_internos, PROP.publicacion_externa
    )
    assert not decision.permitido
    assert decision.regla == POL.ficticio_prohibe_redistribuir
    assert decision.decidido_en == DS.precios_ficticios  # lo frena la fuente, no el derivado


def test_un_derivado_del_feed_ficticio_se_puede_usar_internamente(grafo):
    # El feed permite derivados para uso interno, y riesgo de crédito es un uso interno.
    decision = evaluar(
        grafo, APP.riesgo_corporativo, DS.precios_cierre_internos, PROP.riesgo_credito
    )
    assert decision.permitido


def test_un_proposito_sin_permiso_explicito_se_niega(grafo):
    # El feed no dice nada de riesgo de crédito sobre el feed en sí: no está concedido.
    decision = evaluar(grafo, APP.riesgo_corporativo, DS.precios_ficticios, PROP.riesgo_credito)
    assert not decision.permitido
    assert decision.motivo == "sin_permiso"
    assert decision.regla is None


def test_un_proposito_desconocido_no_se_responde(grafo):
    with pytest.raises(ValueError):
        evaluar(grafo, APP.portal_clientes, DS.gleif_lei, PROP.no_existe)


def test_la_tabla_compilada_incluye_lo_que_hereda_cada_derivado(grafo):
    # La API responde buscando una fila: la tabla tiene que decir lo mismo que el evaluador,
    # también para un derivado que nadie consultó antes.
    fila = {(a, d, p): decision for a, d, p, decision in compilar(grafo)}
    decision = fila[(APP.motor_trading, DS.precios_cierre_internos, PROP.trading_algoritmico)]
    assert not decision.permitido
    assert decision.regla == POL.ficticio_prohibe_non_display


def test_consulta_que_datasets_no_se_pueden_redistribuir(grafo):
    filas = consultar(grafo, "prohiben_redistribuir")
    assert {(dataset, regla) for dataset, _, regla in filas} == {
        (DS.precios_ficticios, POL.ficticio_prohibe_redistribuir),
        (DS.precios_cierre_internos, POL.ficticio_prohibe_redistribuir),
    }


def test_consulta_de_que_fuentes_deriva_la_golden_copy(grafo):
    filas = consultar(grafo, "fuentes_de_la_golden_copy")
    assert {fuente for fuente, _, _ in filas} == {
        DS.gleif_lei,
        DS.gleif_isin_lei,
        DS.sec_empresas,
        DS.openfigi_tickers,
    }
