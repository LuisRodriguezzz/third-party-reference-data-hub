"""Tests de bronze sin Spark y sin AWS."""

import io
import zipfile

import pytest

from refhub.bronze import column_name, column_names, extract_csv, pending_files


def test_column_name():
    assert column_name("LEI") == "lei"
    assert column_name("Entity.LegalName") == "entity_legalname"
    assert column_name("Entity.OtherEntityNames.OtherEntityName.1.xmllang") == (
        "entity_otherentitynames_otherentityname_1_xmllang"
    )


def test_column_names_falla_si_dos_quedan_iguales():
    with pytest.raises(ValueError):
        column_names(["Entity.LegalName", "Entity_LegalName"])


def test_pending_files_saltea_lo_cargado_y_ordena_por_fecha():
    landing = [
        "landing/gleif/dt=2026-10-02/20261002-1600-gleif-goldencopy-lei2-last-day.csv.zip",
        "landing/gleif/dt=2026-10-02/20261002-1600-gleif-goldencopy-lei2-golden-copy.csv.zip",
        "landing/gleif/dt=2026-10-01/20261001-1600-gleif-goldencopy-lei2-last-day.csv.zip",
        "landing/gleif/dt=2026-10-01/",  # una "carpeta" vacía creada desde la consola
    ]
    cargados = ["20261001-1600-gleif-goldencopy-lei2-last-day.csv.zip"]
    assert pending_files(landing, cargados) == [
        "landing/gleif/dt=2026-10-02/20261002-1600-gleif-goldencopy-lei2-golden-copy.csv.zip",
        "landing/gleif/dt=2026-10-02/20261002-1600-gleif-goldencopy-lei2-last-day.csv.zip",
    ]


class FakeS3:
    """S3 de mentira con lo que usa extract_csv: bajar a un archivo y subir desde un stream."""

    def __init__(self, objects):
        self.objects = objects  # {(bucket, key): bytes}

    def download_file(self, Bucket, Key, Filename):
        with open(Filename, "wb") as f:
            f.write(self.objects[(Bucket, Key)])

    def upload_fileobj(self, Fileobj, Bucket, Key):
        self.objects[(Bucket, Key)] = Fileobj.read()


def test_extract_csv_deja_el_csv_en_tmp():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("20261002-1600-gleif-goldencopy-lei2-last-day.csv", "LEI\nABC\n")
    zip_key = "landing/gleif/dt=2026-10-02/20261002-1600-gleif-goldencopy-lei2-last-day.csv.zip"
    s3 = FakeS3({("b", zip_key): buf.getvalue()})

    csv_key = extract_csv(s3, "b", zip_key)

    assert csv_key == "tmp/gleif/20261002-1600-gleif-goldencopy-lei2-last-day.csv"
    assert s3.objects[("b", csv_key)] == b"LEI\nABC\n"
