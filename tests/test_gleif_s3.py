"""Tests de la subida a S3, sin internet y sin AWS: un S3 de mentira y una descarga de mentira."""

import io
from types import SimpleNamespace

import pytest

from refhub.sources import gleif

URL = (
    "https://goldencopy.gleif.org/storage/golden-copy-files/2026/09/28/1282055/"
    "20260928-1600-gleif-goldencopy-lei2-last-day.csv.zip"
)


class FakeClientError(Exception):
    """Imita el error de boto3: trae el código HTTP en err.response["Error"]["Code"]."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    """S3 de mentira: guarda los objetos en un diccionario {(bucket, key): bytes}."""

    exceptions = SimpleNamespace(ClientError=FakeClientError)

    def __init__(self, head_error=None):
        self.objects = {}
        self.head_error = head_error  # para simular, por ejemplo, un 403

    def head_object(self, Bucket, Key):
        if self.head_error:
            raise FakeClientError(self.head_error)
        if (Bucket, Key) not in self.objects:
            raise FakeClientError("404")
        return {}

    def upload_fileobj(self, Fileobj, Bucket, Key):
        self.objects[(Bucket, Key)] = Fileobj.read()


def test_landing_key_usa_la_fecha_de_publicacion():
    assert gleif.landing_key(URL) == (
        "landing/gleif/dt=2026-09-28/20260928-1600-gleif-goldencopy-lei2-last-day.csv.zip"
    )


def test_landing_key_falla_si_no_hay_fecha():
    with pytest.raises(ValueError):
        gleif.landing_key("https://ejemplo.com/archivo-sin-fecha.zip")


def test_subir_dos_veces_no_duplica(monkeypatch):
    descargas = []

    def fake_urlopen(url, timeout):
        descargas.append(url)
        return io.BytesIO(b"contenido del zip")  # BytesIO sirve con "with", como la respuesta real

    monkeypatch.setattr(gleif.urllib.request, "urlopen", fake_urlopen)
    s3 = FakeS3()

    primera = gleif.upload_to_landing(s3, "mi-bucket", URL)
    segunda = gleif.upload_to_landing(s3, "mi-bucket", URL)

    assert primera["status"] == "subido"
    assert segunda["status"] == "ya_existia"
    assert len(s3.objects) == 1  # un solo objeto en el bucket
    assert len(descargas) == 1  # y GLEIF se consultó una sola vez
    assert s3.objects[("mi-bucket", primera["key"])] == b"contenido del zip"


def test_sin_permiso_falla_en_vez_de_seguir():
    s3 = FakeS3(head_error="403")
    with pytest.raises(FakeClientError):
        gleif.upload_to_landing(s3, "mi-bucket", URL)
