"""El nombre normalizado: pares reales de la SEC y de GLEIF que tienen que quedar iguales."""

import pytest

from refhub.names import normalize_name


@pytest.mark.parametrize(
    ("sec", "gleif", "normalizado"),
    [
        ("Apple Inc.", "Apple Inc.", "APPLE"),
        ("MICROSOFT CORP", "MICROSOFT CORPORATION", "MICROSOFT"),  # forma legal abreviada
        ("AMAZON COM INC", "AMAZON.COM, INC.", "AMAZON COM"),  # puntuación
        ("Walt Disney Co", "THE WALT DISNEY COMPANY", "WALT DISNEY"),  # THE adelante
        ("PROCTER & GAMBLE Co", "THE PROCTER & GAMBLE COMPANY", "PROCTER AND GAMBLE"),
        ("ELI LILLY & Co", "ELI LILLY AND COMPANY", "ELI LILLY"),  # "& Co." = "and Company"
        ("BANK OF AMERICA CORP /DE/", "BANK OF AMERICA CORPORATION", "BANK OF AMERICA"),
        ("Siemens Energy AG/ADR", "Siemens Energy AG", "SIEMENS ENERGY"),  # la SEC marca el ADR
        (
            "VERTEX PHARMACEUTICALS INC / MA",
            "VERTEX PHARMACEUTICALS INCORPORATED",
            "VERTEX PHARMACEUTICALS",
        ),
        ("ASML HOLDING NV", "ASML Holding N.V.", "ASML HOLDING"),  # siglas con y sin puntos
    ],
)
def test_la_misma_empresa_queda_igual_en_las_dos_fuentes(sec, gleif, normalizado):
    assert normalize_name(sec) == normalize_name(gleif) == normalizado


def test_sin_tildes():
    assert normalize_name("NESTLÉ S.A.") == "NESTLE"


def test_sigla_con_espacios():
    assert normalize_name("SANOFI-AVENTIS ARGENTINA S. A.") == "SANOFI AVENTIS ARGENTINA"


def test_holdings_no_es_forma_legal():
    # La controlante y la operativa son dos empresas distintas, cada una con su LEI.
    assert normalize_name("Alphabet Holdings Inc.") != normalize_name("Alphabet Inc.")


def test_la_barra_de_una_forma_legal_no_es_una_jurisdiccion():
    # "A/S" es la forma legal danesa: una sola letra después de la barra.
    assert normalize_name("Ascendis Pharma A/S") == "ASCENDIS PHARMA A S"


def test_nunca_queda_vacio_si_hay_palabras():
    assert normalize_name("The Company") == "COMPANY"


@pytest.mark.parametrize("nombre", [None, "", "  ", "..."])
def test_sin_nada_para_comparar_devuelve_texto_vacio(nombre):
    assert normalize_name(nombre) == ""
