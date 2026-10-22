"""Reglas de las relaciones de GLEIF (nivel 2): dónde se guarda el archivo, cómo se lee cada fila
y qué tiene que cumplir para pasar a silver."""

import pytest

from refhub.contract import relationship_problem
from refhub.sources import gleif_rr

URL = (
    "https://goldencopy.gleif.org/storage/golden-copy-files/2026/10/21/1291385/"
    "20261021-1600-gleif-goldencopy-rr-golden-copy.csv.zip"
)

# Una fila real del archivo del 21-oct, con las columnas que no vienen vacías.
CRUDA = {
    "Relationship.StartNode.NodeID": "001GPB6A9XPE8XJICC14",
    "Relationship.EndNode.NodeID": "C7J4FOV6ELAVE39B7M82",
    "Relationship.RelationshipType": "IS_SUBFUND_OF",
    "Relationship.RelationshipStatus": "ACTIVE",
    "Relationship.Period.1.startDate": "2012-11-29T00:00:00.000Z",
    "Relationship.Period.1.endDate": "",
    "Relationship.Period.1.periodType": "RELATIONSHIP_PERIOD",
    "Registration.LastUpdateDate": "2025-04-19T13:30:05.472Z",
    "Registration.RegistrationStatus": "LAPSED",
    "Registration.ValidationSources": "FULLY_CORROBORATED",
}

VALIDA = gleif_rr.relationship(CRUDA)


def test_se_guarda_con_la_fecha_de_publicacion():
    assert gleif_rr.landing_key(URL) == (
        "landing/gleif_rr/dt=2026-10-21/20261021-1600-gleif-goldencopy-rr-golden-copy.csv.zip"
    )


def test_el_periodo_y_la_norma_se_buscan_por_tipo_no_por_posicion():
    # En unas filas el período de la relación es el 1 y en otras el 2: el 1 puede ser el
    # período contable, que no dice desde cuándo vale la relación.
    cruda = {
        **CRUDA,
        "Relationship.RelationshipType": "IS_ULTIMATELY_CONSOLIDATED_BY",
        "Relationship.Period.1.startDate": "2016-01-01T00:00:00-06:00",
        "Relationship.Period.1.endDate": "2016-12-31T00:00:00-06:00",
        "Relationship.Period.1.periodType": "ACCOUNTING_PERIOD",
        "Relationship.Period.2.startDate": "2015-03-01T00:00:00Z",
        "Relationship.Period.2.periodType": "RELATIONSHIP_PERIOD",
        "Relationship.Qualifiers.1.QualifierDimension": "ACCOUNTING_STANDARD",
        "Relationship.Qualifiers.1.QualifierCategory": "IFRS",
    }
    fila = gleif_rr.relationship(cruda)
    assert fila["relationship_start"] == "2015-03-01T00:00:00Z"
    assert fila["relationship_end"] is None  # sigue vigente
    assert fila["accounting_standard"] == "IFRS"


def test_una_relacion_sin_periodo_ni_norma_queda_vacia():
    fila = gleif_rr.relationship({**CRUDA, "Relationship.Period.1.periodType": ""})
    assert fila["relationship_start"] is None
    assert fila["accounting_standard"] is None


def test_una_fila_valida_no_tiene_motivo():
    assert relationship_problem(VALIDA) is None


@pytest.mark.parametrize(
    ("campo", "valor", "motivo"),
    [
        # Un caso real: el único rechazo del archivo del 21-oct.
        ("child_lei", "4469000001BG7ASKSB18", "child_lei_digito_verificador"),
        ("parent_lei", None, "parent_lei_vacio"),
        ("relationship_type", "IS_OWNED_BY", "tipo_relacion_desconocido"),
        ("relationship_status", "ACTIVO", "estado_relacion_desconocido"),
        ("registration_status", "ISSUED", "estado_registro_desconocido"),  # es de nivel 1
        ("last_update", None, "fecha_actualizacion_invalida"),
        ("relationship_start", "29/11/2012", "fecha_inicio_invalida"),
        ("relationship_end", "2016-12-31T00:00:00", "fecha_fin_invalida"),  # sin huso
    ],
)
def test_cada_regla_da_su_motivo(campo, valor, motivo):
    assert relationship_problem({**VALIDA, campo: valor}) == motivo
