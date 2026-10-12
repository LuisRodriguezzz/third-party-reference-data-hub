"""El nombre normalizado: la forma de un nombre de empresa que se usa para comparar fuentes.

GLEIF dice "THE WALT DISNEY COMPANY" y la SEC "Walt Disney Co": es la misma empresa escrita de
dos maneras. Normalizar es sacar lo que cambia de una fuente a otra (mayúsculas, tildes,
puntuación, "THE", la forma legal) y quedarse con lo que identifica a la empresa.
"""

import re
import unicodedata

# Formas legales que se sacan del final. HOLDINGS y GROUP no están a propósito: "X Holdings" y
# "X" suelen ser dos empresas distintas (la controlante y la operativa), cada una con su LEI.
LEGAL_FORMS = frozenset(
    {
        "INC",
        "INCORPORATED",
        "CORP",
        "CORPORATION",
        "CO",
        "COMPANY",
        "LTD",
        "LIMITED",
        "LLC",
        "LP",
        "PLC",
        "NV",
        "SA",
        "AG",
        "SE",
    }
)

# La SEC agrega al final la jurisdicción o el tipo de título: "BANK OF AMERICA CORP /DE/",
# "Siemens Energy AG/ADR", "ONEOK INC /NEW/". Son 2 o 3 letras después de una barra; "A/S"
# (la forma legal danesa) tiene una sola letra y no se toca.
_SEC_SUFFIX = re.compile(r"\s*[/\\]\s*[A-Z]{2,3}[/\\]?\s*$")

# Una letra suelta seguida de punto, antes de otra letra suelta: las siglas "S.A." y "S. A."
# pasan a "SA", como las escribe la otra fuente.
_INITIALS = re.compile(r"\b([A-Z])\.\s?(?=[A-Z]\b)")


def normalize_name(name: str | None) -> str:
    """'THE WALT DISNEY COMPANY' y 'Walt Disney Co' -> 'WALT DISNEY'.

    Nunca devuelve None: si no queda nada para comparar, devuelve ''. Así una fila ya
    normalizada nunca queda con la columna vacía.
    """
    if not name:
        return ""
    # Sin tildes: NFKD separa "é" en "e" + tilde, y la tilde no es ASCII.
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    text = _SEC_SUFFIX.sub("", text)
    text = _INITIALS.sub(r"\1", text)
    text = text.replace("&", " AND ")
    words = re.sub(r"[^A-Z0-9]+", " ", text).split()  # la puntuación pasa a ser un espacio
    if words[:1] == ["THE"]:
        words = words[1:]
    # Se saca la forma legal del final, y también el "AND" de "& Co." ("y compañía").
    # Siempre queda al menos una palabra: "The Company" no se vacía.
    while len(words) > 1 and (words[-1] in LEGAL_FORMS or words[-1] == "AND"):
        words.pop()
    return " ".join(words)
