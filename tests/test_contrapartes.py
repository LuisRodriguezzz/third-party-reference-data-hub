"""Cómo se junta la golden copy con GLEIF en un documento por empresa (buscador, ADR 0014)."""

from refhub.contrapartes import armar_documentos


def _empresa(cik, lei="", nombre_sec="", legal_name="", camino="", ambiguo="false"):
    return {
        "cik": cik,
        "nombre_sec": nombre_sec,
        "lei": lei,
        "legal_name": legal_name,
        "country": "US" if lei else "",
        "registration_status": "ISSUED" if lei else "",
        "camino": camino,
        "conflicto": "false",
        "ambiguo": ambiguo,
    }


def test_la_empresa_de_la_sec_y_su_lei_de_gleif_son_un_solo_documento():
    docs = armar_documentos(
        empresas=[_empresa("0000320193", "LEI_APPLE", "Apple Inc.", "Apple Inc.", "codigos")],
        identificadores=[
            {"cik": "0000320193", "esquema": "TICKER", "valor": "AAPL"},
            {"cik": "0000320193", "esquema": "ISIN", "valor": "US0378331005"},
        ],
        gleif_us=[
            {"lei": "LEI_APPLE", "legal_name": "Apple Inc.", "registration_status": "ISSUED"}
        ],
    )
    assert list(docs) == ["LEI_APPLE"]
    apple = docs["LEI_APPLE"]
    assert apple["en_golden_copy"] and apple["camino"] == "codigos"
    assert apple["ciks"] == ["0000320193"]
    assert apple["tickers"] == ["AAPL"] and apple["isins"] == ["US0378331005"]


def test_una_empresa_de_gleif_que_no_cotiza_entra_solo_con_su_lei():
    docs = armar_documentos(
        [], [], [{"lei": "LEI_X", "legal_name": "X LLC", "registration_status": "LAPSED"}]
    )
    assert docs["LEI_X"]["en_golden_copy"] is False
    assert docs["LEI_X"]["ciks"] == [] and docs["LEI_X"]["estado_registro"] == "LAPSED"


def test_una_empresa_sin_lei_entra_por_su_cik_con_la_marca_de_ambigua():
    docs = armar_documentos(
        [_empresa("0000000003", nombre_sec="GAMMA HOLDINGS", camino="nombre", ambiguo="true")],
        [{"cik": "0000000003", "esquema": "TICKER", "valor": "GMH"}],
        [],
    )
    gamma = docs["CIK-0000000003"]
    assert gamma["lei"] is None and gamma["ambiguo"] is True
    assert gamma["nombre"] == "GAMMA HOLDINGS" and gamma["tickers"] == ["GMH"]


def test_dos_ciks_con_el_mismo_lei_son_un_documento_y_gana_el_camino_por_codigos():
    docs = armar_documentos(
        [
            _empresa("0000000001", "LEI_A", "ACME CORP", "Acme Corporation", "codigos"),
            _empresa("0000000002", "LEI_A", "ACME CORP /DE/", "Acme Corporation", "nombre"),
        ],
        # Los ISINs cuelgan del LEI: los dos CIKs traen los mismos, y no se repiten.
        [
            {"cik": "0000000001", "esquema": "ISIN", "valor": "US0000000001"},
            {"cik": "0000000002", "esquema": "ISIN", "valor": "US0000000001"},
        ],
        [],
    )
    assert list(docs) == ["LEI_A"]
    assert docs["LEI_A"]["ciks"] == ["0000000001", "0000000002"]
    assert docs["LEI_A"]["camino"] == "codigos"
    assert docs["LEI_A"]["isins"] == ["US0000000001"]
    # Los dos nombres de la SEC y el legal de GLEIF se pueden buscar.
    assert docs["LEI_A"]["nombres"] == ["ACME CORP", "ACME CORP /DE/", "Acme Corporation"]


def test_una_emisora_extranjera_entra_aunque_no_sea_de_eeuu():
    fila = _empresa("0000000004", "LEI_SAP", "SAP SE", "SAP SE", "codigos") | {"country": "DE"}
    docs = armar_documentos([fila], [], [])
    assert docs["LEI_SAP"]["pais"] == "DE" and docs["LEI_SAP"]["nombre"] == "SAP SE"
