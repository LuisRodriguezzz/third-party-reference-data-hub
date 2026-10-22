"""Carga el buscador de contrapartes en el OpenSearch local, con la Bulk API.

Lee los CSV de exportar.py, arma un documento por empresa (refhub.contrapartes, donde están las
reglas) y recrea el índice `contrapartes` desde cero: es una copia de gold, no un sistema con
datos propios, así que recargar entero es lo más simple y siempre da lo mismo.

    uv run --group local python local/cargar_opensearch.py
"""

import csv
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from refhub.contrapartes import armar_documentos

DATOS = Path(os.environ.get("REFHUB_LOCAL_DATOS", Path.home() / "refhub-local" / "datos"))
URL = "http://127.0.0.1:9200"
INDICE = "contrapartes"
# La Bulk API rinde mejor con pedidos de unos pocos MB que con uno gigante o con miles chicos.
TAMANO_LOTE = 5_000_000


def pedir(metodo: str, ruta: str, cuerpo: bytes | None = None, tipo="application/json") -> dict:
    pedido = urllib.request.Request(f"{URL}{ruta}", data=cuerpo, method=metodo)
    pedido.add_header("Content-Type", tipo)
    with urllib.request.urlopen(pedido) as respuesta:
        return json.load(respuesta)


def leer(nombre: str) -> list[dict]:
    with (DATOS / f"{nombre}.csv").open(encoding="utf-8", newline="") as archivo:
        return list(csv.DictReader(archivo))


def enviar(lote: list[bytes]) -> None:
    respuesta = pedir("POST", "/_bulk", b"".join(lote), "application/x-ndjson")
    # Bulk responde 200 aunque fallen documentos sueltos: hay que mirar cada uno.
    if respuesta["errors"]:
        primero = next(i for i in respuesta["items"] if "error" in i["index"])
        raise RuntimeError(f"Bulk con errores, el primero: {primero}")


def main() -> None:
    docs = armar_documentos(leer("empresas"), leer("identificadores"), leer("gleif_us"))

    try:
        pedir("DELETE", f"/{INDICE}")
    except urllib.error.HTTPError as error:
        if error.code != 404:  # 404: todavía no existía, que es lo esperable la primera vez
            raise
    indice = (Path(__file__).parent / "opensearch" / "indice.json").read_bytes()
    pedir("PUT", f"/{INDICE}", indice)

    lote, tamano = [], 0
    for id_doc, doc in docs.items():
        accion = json.dumps({"index": {"_index": INDICE, "_id": id_doc}})
        linea = f"{accion}\n{json.dumps(doc, ensure_ascii=False)}\n".encode()
        lote.append(linea)
        tamano += len(linea)
        if tamano >= TAMANO_LOTE:
            enviar(lote)
            lote, tamano = [], 0
    if lote:
        enviar(lote)
    pedir("POST", f"/{INDICE}/_refresh")
    total = pedir("GET", f"/{INDICE}/_count")["count"]
    print(f"{total} documentos en {INDICE}")


if __name__ == "__main__":
    main()
