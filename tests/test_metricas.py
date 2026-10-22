from refhub.metricas import calcular, documento_emf

# Filas como las devuelve Athena: todo texto, y el nulo de OpenFIGI como None.
FUENTES = [
    {"fuente": "gleif", "atrasada": "false", "filas_cuarentena": "256"},
    {"fuente": "gleif_isin_lei", "atrasada": "true", "filas_cuarentena": "0"},
    {"fuente": "sec", "atrasada": "true", "filas_cuarentena": "3"},
    {"fuente": "gleif_rr", "atrasada": "false", "filas_cuarentena": "1"},
    {"fuente": "openfigi", "atrasada": "false", "filas_cuarentena": None},
]
CRUCE = {"empresas": "8017", "porcentaje_con_lei": "52.9", "conflictos": "55", "ambiguos": "19"}


def test_cuenta_las_fuentes_atrasadas_y_suma_la_cuarentena():
    metricas = calcular(FUENTES, CRUCE)

    assert metricas["fuentes_atrasadas"] == 2
    assert metricas["filas_cuarentena"] == 260  # OpenFIGI, sin cuarentena, suma 0
    assert metricas["porcentaje_con_lei"] == 52.9


def test_el_emf_declara_cada_metrica_y_no_pasa_de_diez():
    metricas = calcular(FUENTES, CRUCE)
    doc = documento_emf(metricas, "dev", 1_700_000_000_000)

    declaradas = [m["Name"] for m in doc["_aws"]["CloudWatchMetrics"][0]["Metrics"]]
    # Cada métrica declarada tiene su valor en el documento: si no, CloudWatch la ignora.
    assert all(nombre in doc for nombre in declaradas)
    # Cada métrica se paga (el free tier cubre 10) y la dimensión es solo el ambiente.
    assert len(declaradas) <= 10
    assert doc["_aws"]["CloudWatchMetrics"][0]["Dimensions"] == [["ambiente"]]
