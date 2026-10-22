"""Validación de ISIN (International Securities Identification Number, norma ISO 6166)."""

import re

# Dos letras del país, nueve caracteres que asigna ese país y un dígito verificador.
_FORMATO = re.compile(r"[A-Z]{2}[A-Z0-9]{9}[0-9]")


def isin_problem(value: str | None) -> str | None:
    """Devuelve el motivo por el que el ISIN es inválido, o None si es válido."""
    if not value:
        return "vacio"
    if len(value) != 12:
        return "longitud"
    if not _FORMATO.fullmatch(value):
        return "caracteres"
    # Algoritmo de Luhn (el mismo de las tarjetas de crédito): las letras pasan a números
    # (A=10 ... Z=35) y, desde la derecha, se duplica un dígito sí y otro no; si un doble da
    # más de 9 se le resta 9. La suma de todo tiene que terminar en 0.
    digits = "".join(str(int(ch, 36)) for ch in value)
    total = 0
    for position, digit in enumerate(reversed(digits)):
        n = int(digit)
        if position % 2 == 1:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    if total % 10 != 0:
        return "digito_verificador"
    return None


def is_us_equity(isin: str) -> bool:
    """¿Es una acción de EE. UU.? Sirve para no preguntarle a OpenFIGI por bonos.

    Un ISIN de EE. UU. es "US" + el CUSIP (9 caracteres) + el verificador. En el CUSIP, los
    caracteres 7 y 8 (las posiciones 9 y 10 del ISIN) son el número de emisión: por convención,
    de 10 a 88 son acciones; con letras, deuda (bonos, pagarés). Así, Apple US0378331005 tiene
    "10" (acción) y su bono US037833DX52 tiene "DX".
    """
    issue = isin[8:10]
    return isin.startswith("US") and issue.isdigit() and 10 <= int(issue) <= 88
