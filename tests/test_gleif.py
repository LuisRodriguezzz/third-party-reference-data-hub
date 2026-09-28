import csv
import io
import zipfile

from refhub.sources.gleif import read_rows, split_valid_invalid


def _zip_con_csv(tmp_path, filas):
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=["LEI", "Entity.LegalName", "Registration.RegistrationStatus"]
    )
    writer.writeheader()
    writer.writerows(filas)
    path = tmp_path / "muestra.csv.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("muestra.csv", buf.getvalue())
    return path


def test_lee_y_separa(tmp_path):
    path = _zip_con_csv(
        tmp_path,
        [
            {
                "LEI": "HWUPKR0MPOU8FGXBT394",
                "Entity.LegalName": "Apple Inc.",
                "Registration.RegistrationStatus": "ISSUED",
            },
            {
                "LEI": "HWUPKR0MPOU8FGXBT39",
                "Entity.LegalName": "Cortado",
                "Registration.RegistrationStatus": "ISSUED",
            },
        ],
    )
    valid, rejected = split_valid_invalid(read_rows(path))
    assert [r["legal_name"] for r in valid] == ["Apple Inc."]
    assert rejected[0]["motivo"] == "longitud"
    assert valid[0]["country"] == ""  # columna que no vino -> vacía, no error
