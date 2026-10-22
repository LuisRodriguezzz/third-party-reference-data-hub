"""Arma gold_set.csv, el seed con la respuesta correcta para medir el cruce CIK↔LEI (5F, ADR 0008).

La planilla etiquetada trae, para 100 CIK elegidos al azar, el LEI correcto decidido por otro
camino (un agente de IA a ciegas, sin ver lo que eligió el cruce), con su evidencia. El seed se
queda solo con lo que la métrica necesita: el CIK, la respuesta y la confianza. Los nombres y la
evidencia quedan en la planilla; así el seed no carga texto que nadie va a consultar en SQL.

La auditoría (opcional) es otro archivo con las filas que revisó una persona: `cik;coincide`.

Se corre desde la raíz del repo, sin credenciales (no toca AWS):

    uv run python dbt/seeds/preparar_gold_set.py <planilla etiquetada> [<auditoría>]

Los dos archivos de entrada vienen de Excel: separador `;` y, a veces, BOM.
"""

import csv
import re
import sys
from pathlib import Path

SALIDA = Path(__file__).with_name("gold_set.csv")
FILAS_ESPERADAS = 100
# Un LEI son 20 caracteres alfanuméricos (ISO 17442). Acá no se valida el dígito verificador:
# lo que importa es que no se cuele un texto cualquiera ("no tiene", una URL) como respuesta.
FORMATO_LEI = re.compile(r"[A-Z0-9]{20}")
RESPUESTAS_ESPECIALES = {"SIN_LEI", "DUDA"}
# Cómo puede venir escrito "coincide" en la auditoría, hecha a mano.
SI = {"si", "sí", "true", "1", "s"}
NO = {"no", "false", "0", "n"}


def leer(ruta: Path) -> list[dict[str, str]]:
    # utf-8-sig saca el BOM si está; sin él, la primera columna se llamaría "﻿n".
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo, delimiter=";"))


def normalizar_cik(valor: str, donde: str) -> str:
    """El CIK con 10 dígitos, como en la SEC y en gold.empresas (Excel suele comerse los ceros)."""
    cik = valor.strip()
    if not cik.isdigit() or len(cik) > 10:
        raise ValueError(f"{donde}: CIK inválido {valor!r}")
    return cik.zfill(10)


def normalizar_respuesta(valor: str, cik: str) -> str:
    respuesta = valor.strip().upper()
    if respuesta in RESPUESTAS_ESPECIALES or FORMATO_LEI.fullmatch(respuesta):
        return respuesta
    raise ValueError(
        f"CIK {cik}: lei_correcto {valor!r} no es un LEI de 20 caracteres alfanuméricos, "
        "ni SIN_LEI, ni DUDA"
    )


def leer_auditoria(ruta: Path, ciks: set[str]) -> dict[str, bool]:
    auditoria = {}
    for fila in leer(ruta):
        cik = normalizar_cik(fila["cik"], "auditoría")
        if cik not in ciks:
            raise ValueError(f"auditoría: el CIK {cik} no está en la planilla etiquetada")
        if cik in auditoria:
            raise ValueError(f"auditoría: el CIK {cik} está repetido")
        coincide = fila["coincide"].strip().lower()
        if coincide not in SI | NO:
            raise ValueError(f"auditoría: CIK {cik}, coincide {fila['coincide']!r} no es sí ni no")
        auditoria[cik] = coincide in SI
    return auditoria


def main() -> None:
    if len(sys.argv) not in (2, 3):
        sys.exit("uso: preparar_gold_set.py <planilla etiquetada> [<auditoría>]")

    filas = []
    for fila in leer(Path(sys.argv[1])):
        cik = normalizar_cik(fila["cik"], f"fila {fila['n']}")
        filas.append(
            {
                "cik": cik,
                "lei_correcto": normalizar_respuesta(fila["lei_correcto"], cik),
                "confianza": fila["confianza"].strip().lower(),
            }
        )

    # La muestra tiene que ser la que se sorteó: ni filas de menos (casos que se "perdieron") ni
    # un CIK dos veces (pesaría doble en la métrica).
    if len(filas) != FILAS_ESPERADAS:
        raise ValueError(f"la planilla tiene {len(filas)} filas y tienen que ser {FILAS_ESPERADAS}")
    ciks = {f["cik"] for f in filas}
    if len(ciks) != len(filas):
        raise ValueError("la planilla tiene CIK repetidos")

    auditoria = leer_auditoria(Path(sys.argv[2]), ciks) if len(sys.argv) == 3 else {}

    with SALIDA.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo, lineterminator="\n")
        escritor.writerow(
            ["cik", "lei_correcto", "confianza", "etiquetado_por", "auditado", "auditoria_coincide"]
        )
        for fila in filas:
            auditado = fila["cik"] in auditoria
            coincide = str(auditoria[fila["cik"]]).lower() if auditado else ""
            escritor.writerow(
                [
                    fila["cik"],
                    fila["lei_correcto"],
                    fila["confianza"],
                    "agente_ia",
                    str(auditado).lower(),
                    coincide,
                ]
            )

    por_respuesta = {
        "con LEI": sum(f["lei_correcto"] not in RESPUESTAS_ESPECIALES for f in filas),
        "SIN_LEI": sum(f["lei_correcto"] == "SIN_LEI" for f in filas),
        "DUDA": sum(f["lei_correcto"] == "DUDA" for f in filas),
    }
    resumen = ", ".join(f"{cantidad} {clave}" for clave, cantidad in por_respuesta.items())
    print(f"{len(filas)} CIK ({resumen}), {len(auditoria)} auditados, en {SALIDA.name}")


if __name__ == "__main__":
    main()
