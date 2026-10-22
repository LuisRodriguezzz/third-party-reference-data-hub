"""Los documentos del buscador de contrapartes (OpenSearch, ADR 0014): uno por empresa.

Un analista busca "berkshire hathway" y tiene que encontrar UNA fila por empresa, con todos sus
códigos. Las entradas vienen de tres tablas que no dicen lo mismo:

- la golden copy (`gold.empresas`), una fila por CIK de la SEC, con el LEI elegido o sin LEI;
- sus identificadores (`gold.identificadores`): ISINs, FIGIs y tickers de cada CIK;
- las empresas de EE. UU. de GLEIF (`silver.gleif_lei`), que en su mayoría no cotizan.

Las reglas para juntarlas:

- **La clave de la empresa es el LEI.** Si un CIK de la SEC eligió un LEI, ese CIK y el
  registro de GLEIF de ese LEI son la misma empresa: un solo documento.
- **Una empresa de la SEC sin LEI** (sin candidatos, o ambigua) entra igual, con clave
  `CIK-<cik>`: que no tenga LEI no quiere decir que no sea una contraparte.
- **Dos CIKs con el mismo LEI** (pasa: la golden copy lo permite) son un documento con los dos
  CIKs, no dos documentos que compiten en la búsqueda.
- **Una empresa extranjera de la golden copy** entra aunque no esté entre las de EE. UU. de
  GLEIF: su nombre legal ya viene en la golden copy.
"""

ESQUEMAS = {"ISIN": "isins", "FIGI": "figis", "TICKER": "tickers"}


def _nuevo(lei: str | None) -> dict:
    return {
        "lei": lei,
        "nombre": None,
        "nombres": set(),
        "pais": None,
        "estado_registro": None,
        "en_golden_copy": False,
        "camino": None,
        "conflicto": False,
        "ambiguo": False,
        # Conjuntos mientras se arma (una empresa puede tener 128 mil ISINs y los repetidos se
        # descartan solos); al final pasan a listas ordenadas, que es lo que acepta JSON.
        "ciks": set(),
        "isins": set(),
        "figis": set(),
        "tickers": set(),
    }


def _agregar(conjunto: set, valor: str | None) -> None:
    if valor:
        conjunto.add(valor)


def armar_documentos(
    empresas: list[dict], identificadores: list[dict], gleif_us: list[dict]
) -> dict[str, dict]:
    """Devuelve {id del documento: documento}. El id es el LEI, o `CIK-<cik>` si no hay LEI.

    Las filas son las de los CSV exportados (todo texto; los booleanos de Athena como "true").
    """
    docs: dict[str, dict] = {}
    for fila in gleif_us:
        doc = docs.setdefault(fila["lei"], _nuevo(fila["lei"]))
        doc.update(
            nombre=fila["legal_name"], pais="US", estado_registro=fila["registration_status"]
        )
        _agregar(doc["nombres"], fila["legal_name"])

    doc_de_cik = {}
    for fila in empresas:
        lei = fila["lei"] or None
        id_doc = lei or f"CIK-{fila['cik']}"
        doc = docs.setdefault(id_doc, _nuevo(lei))
        doc_de_cik[fila["cik"]] = doc
        doc["en_golden_copy"] = True
        _agregar(doc["ciks"], fila["cik"])
        if lei:
            # El nombre legal de GLEIF es el oficial; el de la SEC queda como otro nombre buscable.
            doc.update(
                nombre=fila["legal_name"],
                pais=fila["country"],
                estado_registro=fila["registration_status"],
            )
            _agregar(doc["nombres"], fila["legal_name"])
        elif not doc["nombre"]:
            doc["nombre"] = fila["nombre_sec"]
        _agregar(doc["nombres"], fila["nombre_sec"])
        # Si dos CIKs comparten LEI, el camino por códigos es la evidencia más fuerte (ADR 0008),
        # y una marca de conflicto o ambigüedad en cualquiera de los dos se tiene que ver.
        if doc["camino"] != "codigos":
            doc["camino"] = fila["camino"] or doc["camino"]
        doc["conflicto"] |= fila["conflicto"] == "true"
        doc["ambiguo"] |= fila["ambiguo"] == "true"

    for fila in identificadores:
        doc = doc_de_cik.get(fila["cik"])
        if doc is not None and fila["esquema"] in ESQUEMAS:
            _agregar(doc[ESQUEMAS[fila["esquema"]]], fila["valor"])
    for doc in docs.values():
        for campo in ("nombres", "ciks", *ESQUEMAS.values()):
            doc[campo] = sorted(doc[campo])
    return docs
