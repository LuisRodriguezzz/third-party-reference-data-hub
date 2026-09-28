"""Validación de LEI (Legal Entity Identifier, norma ISO 17442)."""

import re

_ALFANUM = re.compile(r"[A-Z0-9]+")


def lei_problem(value: str | None) -> str | None:
    """Devuelve el motivo por el que el LEI es inválido, o None si es válido."""
    if not value:
        return "vacio"
    if len(value) != 20:
        return "longitud"
    if not _ALFANUM.fullmatch(value) or not value[-2:].isdigit():
        return "caracteres"
    # ISO 7064 MOD 97-10 (el mismo método que el IBAN): cada carácter pasa a número
    # (0-9 quedan igual, A=10, B=11 ... Z=35), se pegan todos y el número resultante
    # tiene que dar resto 1 al dividirlo por 97.
    digits = "".join(str(int(ch, 36)) for ch in value)
    if int(digits) % 97 != 1:
        return "digito_verificador"
    return None


def is_valid_lei(value: str | None) -> bool:
    return lei_problem(value) is None
