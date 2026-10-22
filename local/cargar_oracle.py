"""Carga el sistema de riesgo en el Oracle Free local: árbol de consolidación, nombres y cartera.

Lee los CSV de exportar.py. La primera vez crea el usuario RIESGO (con la misma contraseña local
de local/.env); después recrea las tablas (oracle/esquema.sql) y las llena. oracledb en modo
thin habla el protocolo de Oracle directo: no hace falta instalar el Instant Client.

    uv run --group local python local/cargar_oracle.py
"""

import csv
import os
from pathlib import Path

import oracledb

DATOS = Path(os.environ.get("REFHUB_LOCAL_DATOS", Path.home() / "refhub-local" / "datos"))
AQUI = Path(__file__).parent
DSN = "127.0.0.1:1521/FREEPDB1"  # la base enchufable que trae Oracle Free para las aplicaciones

# CSV -> (tabla, columnas del INSERT, en el orden del CSV)
CARGAS = {
    "entidades": ("entidades", "lei, nombre, pais"),
    "relaciones_directas": ("relaciones_directas", "hija_lei, controlante_lei"),
    "cartera": ("cartera_sintetica", "prestamo_id, lei, monto_usd, producto"),
    "controlante_publicada": ("controlante_publicada", "lei, controlante_final_lei"),
}


def contrasena() -> str:
    """ORACLE_PWD del entorno o de local/.env, el mismo archivo que lee compose."""
    if "ORACLE_PWD" in os.environ:
        return os.environ["ORACLE_PWD"]
    for linea in (AQUI / ".env").read_text(encoding="utf-8").splitlines():
        if linea.startswith("ORACLE_PWD="):
            return linea.split("=", 1)[1].strip()
    raise RuntimeError("Falta ORACLE_PWD en local/.env")


def main() -> None:
    clave = contrasena()
    with oracledb.connect(user="system", password=clave, dsn=DSN) as admin:
        # Un usuario propio para el sistema de riesgo: las tablas no van en SYSTEM.
        # DB_DEVELOPER_ROLE es el rol de Oracle 23 para quien crea tablas y consulta. La imagen
        # lite no trae el tablespace USERS: se da espacio sin límite en el que haya por defecto,
        # aceptable en una base local de prueba.
        admin.cursor().execute(f'CREATE USER IF NOT EXISTS riesgo IDENTIFIED BY "{clave}"')
        admin.cursor().execute("GRANT DB_DEVELOPER_ROLE, UNLIMITED TABLESPACE TO riesgo")

    with oracledb.connect(user="riesgo", password=clave, dsn=DSN) as conexion:
        cursor = conexion.cursor()
        esquema = (AQUI / "oracle" / "esquema.sql").read_text(encoding="utf-8")
        for sentencia in esquema.split(";"):
            # Se sacan los comentarios de línea para ver si quedó algo para correr.
            codigo = "\n".join(
                linea for linea in sentencia.splitlines() if not linea.strip().startswith("--")
            )
            if codigo.strip():
                cursor.execute(codigo)

        for csv_nombre, (tabla, columnas) in CARGAS.items():
            with (DATOS / f"{csv_nombre}.csv").open(encoding="utf-8", newline="") as archivo:
                filas = list(csv.reader(archivo))[1:]  # sin el encabezado
            marcas = ", ".join(f":{i}" for i in range(1, len(filas[0]) + 1))
            sql = f"INSERT INTO {tabla} ({columnas}) VALUES ({marcas})"
            # De a 50 mil filas: executemany manda el lote en un solo viaje a la base.
            for inicio in range(0, len(filas), 50_000):
                cursor.executemany(sql, filas[inicio : inicio + 50_000])
            conexion.commit()
            print(f"{tabla}: {len(filas)} filas")


if __name__ == "__main__":
    main()
