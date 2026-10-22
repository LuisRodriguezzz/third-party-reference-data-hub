"""Reglas que comparten los jobs de silver de foto completa: qué archivo es el último y qué
acepta --FULL_REFRESH."""

import pytest

from refhub.silver import full_refresh_flag, latest_landing_key


class FakeS3:
    """S3 de mentira que lista las claves en dos páginas, como hace S3 con muchas."""

    def __init__(self, keys):
        self.keys = keys

    def get_paginator(self, name):
        return self

    def paginate(self, Bucket, Prefix):
        keys = [k for k in self.keys if k.startswith(Prefix)]
        half = len(keys) // 2
        return [{"Contents": [{"Key": k} for k in part]} for part in (keys[:half], keys[half:])]


def test_el_ultimo_archivo_es_el_de_publicacion_mas_nueva():
    # Dos publicaciones el mismo día: gana la de las 16:00 aunque S3 la liste antes.
    s3 = FakeS3(
        [
            "landing/gleif_rr/dt=2026-10-21/20261021-1600-gleif-goldencopy-rr-golden-copy.csv.zip",
            "landing/gleif_rr/dt=2026-10-20/20261020-1600-gleif-goldencopy-rr-golden-copy.csv.zip",
            "landing/gleif_rr/dt=2026-10-21/20261021-0800-gleif-goldencopy-rr-golden-copy.csv.zip",
        ]
    )
    assert latest_landing_key(s3, "bucket", "landing/gleif_rr/").endswith(
        "20261021-1600-gleif-goldencopy-rr-golden-copy.csv.zip"
    )


def test_sin_archivos_en_landing_falla():
    with pytest.raises(ValueError):
        latest_landing_key(FakeS3([]), "bucket", "landing/gleif_rr/")


@pytest.mark.parametrize("valor", ["True", "si", ""])
def test_full_refresh_no_acepta_otra_cosa(valor):
    # Con un typo el job correría en modo normal y no recalcularía nada, sin avisar.
    with pytest.raises(ValueError):
        full_refresh_flag(valor)
