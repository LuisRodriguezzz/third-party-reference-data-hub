"""Reglas de las fuentes del hito 5: dónde se guarda cada archivo y cómo se le pide a la SEC."""

import pytest

from refhub.sources import gleif_isin_lei, sec


def test_isin_lei_se_guarda_con_la_fecha_de_publicacion():
    assert gleif_isin_lei.landing_key("isin-lei-20261012T071510.zip") == (
        "landing/gleif_isin_lei/dt=2026-10-12/isin-lei-20261012T071510.zip"
    )


def test_isin_lei_falla_si_cambia_el_formato_del_nombre():
    with pytest.raises(ValueError):
        gleif_isin_lei.landing_key("lei-isin-20261012T071510.csv")


def test_sec_se_guarda_con_la_fecha_de_su_ultima_actualizacion():
    # La fecha sale de la SEC (Last-Modified), no del reloj: misma versión, misma clave.
    assert sec.landing_key("Wed, 07 Oct 2026 20:38:00 GMT") == (
        "landing/sec/dt=2026-10-07/company_tickers_exchange-20261007T203800.json"
    )


def test_sec_cada_pedido_lleva_el_contacto():
    assert sec.headers("datos@ejemplo.com") == {"User-Agent": "refhub datos@ejemplo.com"}
