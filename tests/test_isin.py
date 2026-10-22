import pytest

from refhub.isin import is_us_equity, isin_problem


@pytest.mark.parametrize(
    "isin",
    [
        "US0378331005",  # Apple, acción
        "US5949181045",  # Microsoft, acción
        "US037833DX52",  # Apple, un bono: letras en el medio
        "DE000BAY0017",  # Bayer: otro país
    ],
)
def test_isin_validos(isin):
    assert isin_problem(isin) is None


@pytest.mark.parametrize(
    ("isin", "motivo"),
    [
        ("", "vacio"),
        (None, "vacio"),
        ("US037833100", "longitud"),  # le falta un carácter
        ("us0378331005", "caracteres"),  # minúsculas
        ("120378331005", "caracteres"),  # el país tiene que ser dos letras
        ("US037833100X", "caracteres"),  # el verificador es un número
        ("US0378331006", "digito_verificador"),  # último dígito cambiado
        ("US0378313005", "digito_verificador"),  # dos dígitos intercambiados
    ],
)
def test_isin_invalidos(isin, motivo):
    assert isin_problem(isin) == motivo


@pytest.mark.parametrize(
    ("isin", "es_accion"),
    [
        ("US0378331005", True),  # Apple, acción: emisión "10"
        ("US037833DX52", False),  # Apple, un bono: emisión "DX", con letras
        ("DE000BAY0017", False),  # Bayer: no es de EE. UU.
    ],
)
def test_solo_acciones_de_eeuu(isin, es_accion):
    assert is_us_equity(isin) is es_accion
