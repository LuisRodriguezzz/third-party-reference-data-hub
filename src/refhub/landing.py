"""Subir el archivo de una fuente a landing/ tal cual llega, sin duplicarlo.

Lo usan todas las fuentes: cada una decide la URL y la clave (dónde va); esto solo sube.
"""

import urllib.request


def object_exists(s3, bucket: str, key: str) -> bool:
    """¿Ya está ese objeto en el bucket? HeadObject pide solo los metadatos, no el archivo."""
    try:
        s3.head_object(Bucket=bucket, Key=key)
    except s3.exceptions.ClientError as err:
        if err.response["Error"]["Code"] == "404":
            return False
        raise  # 403 (sin permiso) u otro error: que falle, no seguir a ciegas
    return True


def upload(
    s3, bucket: str, url: str, key: str, headers: dict[str, str] | None = None
) -> dict[str, str]:
    """Baja la URL directo a S3, sin pasar por disco. Si la clave ya estaba, no hace nada."""
    if object_exists(s3, bucket, key):
        return {"bucket": bucket, "key": key, "status": "ya_existia"}
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=120) as resp:
        # upload_fileobj lee la respuesta de a pedazos y la sube. S3 publica el objeto
        # recién cuando termina: nunca queda un archivo a medias con el nombre final.
        s3.upload_fileobj(resp, bucket, key)
    return {"bucket": bucket, "key": key, "status": "subido"}
