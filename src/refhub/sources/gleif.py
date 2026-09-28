"""Fuente GLEIF: baja el delta diario de la Golden Copy y separa filas válidas e inválidas."""

import csv
import io
import json
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


def latest_delta_url(kind: str = "LastDay") -> str:
    """Pregunta a la API de GLEIF cuál es la URL del último archivo delta."""
    with urllib.request.urlopen(PUBLISHES_URL, timeout=30) as resp:
        data = json.load(resp)["data"]
    return data["lei2"]["delta_files"][kind]["csv"]["url"]


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
    landing = Path("data/landing/gleif") / f"dt={date.today().isoformat()}"
    zip_path = download(latest_delta_url(), landing)
    valid, rejected = split_valid_invalid(read_rows(zip_path))
    total = len(valid) + len(rejected)
    print(f"{zip_path.name}: {total} filas | {len(valid)} validas | {len(rejected)} rechazadas")
    for status, n in Counter(r["registration_status"] for r in valid).most_common():
        print(f"  {status:<18} {n:>6}  ({n / total:.1%})")


if __name__ == "__main__":
    main()
