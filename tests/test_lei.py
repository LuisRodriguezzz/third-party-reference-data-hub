import pytest

from refhub.lei import is_valid_lei, lei_problem


@pytest.mark.parametrize(
    "lei",
    [
        "HWUPKR0MPOU8FGXBT394",  # Apple Inc.
        "5493001KJTIIGC8Y1R12",
    ],
)
def test_lei_validos(lei):
    assert is_valid_lei(lei)


@pytest.mark.parametrize(
    ("lei", "motivo"),
    [
        ("", "vacio"),
        (None, "vacio"),
        ("HWUPKR0MPOU8FGXBT39", "longitud"),  # le falta un carácter
        ("hwupkr0mpou8fgxbt394", "caracteres"),  # minúsculas
        ("HWUPKR0MPOU8FGXBT39A", "caracteres"),  # verificador con letra
        ("HWUPKR0MPOU8FGXBT395", "digito_verificador"),  # último dígito cambiado
    ],
)
def test_lei_invalidos(lei, motivo):
    assert lei_problem(lei) == motivo
