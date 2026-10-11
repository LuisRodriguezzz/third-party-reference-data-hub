"""Fuente GLEIF: baja el delta diario de la Golden Copy y separa filas válidas e inválidas."""

import csv
import io
import json
import os
import re
import urllib.request
import zipfile
from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import date
from pathlib import Path

from refhub.lei import lei_problem

PUBLISHES_URL = "https://goldencopy.gleif.org/api/v2/golden-copies/publishes/latest"

# Columnas del CSV de GLEIF (tiene ~338) -> nombre que usamos nosotros.
COLUMNS = {
    "LEI": "lei",
    "Entity.LegalName": "legal_name",
    "Entity.LegalAddress.Country": "country",
    "Entity.EntityStatus": "entity_status",
    "Registration.RegistrationStatus": "registration_status",
    "Registration.LastUpdateDate": "last_update",
    "Registration.NextRenewalDate": "next_renewal",
}

# GLEIF nombra sus archivos con la fecha y hora de publicación adelante:
# 20260928-1600-gleif-goldencopy-lei2-last-day.csv.zip -> publicado el 2026-09-28 a las 16:00.
_PUBLISH_DATE = re.compile(r"(\d{4})(\d{2})(\d{2})-\d{4}-")


def latest_delta_url(kind: str = "LastDay") -> str:
    """Pregunta a la API de GLEIF cuál es la URL del último archivo delta."""
    with urllib.request.urlopen(PUBLISHES_URL, timeout=30) as resp:
        data = json.load(resp)["data"]
    return data["lei2"]["delta_files"][kind]["csv"]["url"]


def latest_full_url() -> str:
    """URL del último archivo completo de GLEIF (~480 MB en zip, ~3,4 millones de LEIs)."""
    with urllib.request.urlopen(PUBLISHES_URL, timeout=30) as resp:
        data = json.load(resp)["data"]
    return data["lei2"]["full_file"]["csv"]["url"]


def publish_date(name: str) -> date:
    """Fecha de publicación que GLEIF pone al principio del nombre del archivo."""
    match = _PUBLISH_DATE.match(name)
    if match is None:
        # Si GLEIF cambia el formato del nombre, mejor fallar que inventar una fecha.
        raise ValueError(f"No encuentro la fecha de publicación en {name!r}")
    year, month, day = (int(part) for part in match.groups())
    return date(year, month, day)


def landing_key(url: str) -> str:
    """Dónde se guarda el archivo: landing/gleif/dt=<fecha de publicación>/<nombre original>.

    La fecha sale del nombre del archivo (la pone GLEIF), no del reloj de la máquina:
    el mismo archivo va siempre a la misma carpeta, lo bajes hoy o dentro de una semana.
    """
    name = url.rsplit("/", 1)[-1]
    return f"landing/gleif/dt={publish_date(name).isoformat()}/{name}"


def download(url: str, dest_dir: Path) -> Path:
    """Baja el archivo tal cual. Si ya existe, no lo vuelve a bajar (idempotente)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / url.rsplit("/", 1)[-1]
    if dest.exists():
        return dest
    tmp = dest.with_name(dest.name + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 20):  # de a 1 MB, sin cargar todo en memoria
            out.write(chunk)
    tmp.replace(dest)  # se renombra al final: nunca queda un archivo a medias con el nombre final
    return dest


def object_exists(s3, bucket: str, key: str) -> bool:
    """¿Ya está ese objeto en el bucket? HeadObject pide solo los metadatos, no el archivo."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except s3.exceptions.ClientError as err:
        if err.response["Error"]["Code"] == "404":
            return False
        raise  # 403 (sin permiso) u otro error: que falle, no seguir a ciegas
    return True


def upload_to_landing(s3, bucket: str, url: str) -> dict[str, str]:
    """Baja el archivo de GLEIF directo a S3, sin pasar por disco. Si ya estaba, no hace nada."""
    key = landing_key(url)
    if object_exists(s3, bucket, key):
        return {"bucket": bucket, "key": key, "status": "ya_existia"}
    with urllib.request.urlopen(url, timeout=120) as resp:
        # upload_fileobj lee la respuesta de a pedazos y la sube. S3 publica el objeto
        # recién cuando termina: nunca queda un archivo a medias con el nombre final.
        s3.upload_fileobj(resp, bucket, key)
    return {"bucket": bucket, "key": key, "status": "subido"}


def handler(event, context):
    """Punto de entrada de la Lambda. Lambda llama a esta función con (event, context)."""
    # boto3 viene incluido en el runtime de Lambda. Se importa acá adentro para que
    # los tests y main() funcionen sin tenerlo instalado.
    import boto3

    bucket = os.environ["DATA_BUCKET"]  # lo define Terraform en la configuración de la Lambda
    result = upload_to_landing(boto3.client("s3"), bucket, latest_delta_url())
    print(result)  # queda en CloudWatch Logs
    return result  # y Step Functions lo muestra como salida del paso


def read_rows(zip_path: Path) -> Iterator[dict[str, str]]:
    """Lee el CSV dentro del zip y devuelve solo las columnas que nos importan."""
    with zipfile.ZipFile(zip_path) as zf:
        (name,) = zf.namelist()  # GLEIF pone un solo CSV por zip; si no, que falle
        with zf.open(name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            for row in reader:
                yield {new: row.get(old, "") for old, new in COLUMNS.items()}


def split_valid_invalid(
    rows: Iterable[dict[str, str]],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    valid, rejected = [], []
    for row in rows:
        problem = lei_problem(row["lei"])
        if problem is None:
            valid.append(row)
        else:
            rejected.append({**row, "motivo": problem})
    return valid, rejected


def main() -> None:
    url = latest_delta_url()
    # Mismo layout que en S3: data/ hace de "bucket local".
    landing = (Path("data") / landing_key(url)).parent
    zip_path = download(url, landing)
    valid, rejected = split_valid_invalid(read_rows(zip_path))
    total = len(valid) + len(rejected)
    print(f"{zip_path.name}: {total} filas | {len(valid)} validas | {len(rejected)} rechazadas")
    for status, n in Counter(r["registration_status"] for r in valid).most_common():
        print(f"  {status:<18} {n:>6}  ({n / total:.1%})")


if __name__ == "__main__":
    main()
