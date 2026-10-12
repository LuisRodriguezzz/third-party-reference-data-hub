"""La Lambda de ingesta: baja a landing/ la fuente que pide el evento.

{"fuente": "gleif"} (o un evento vacío, como manda Step Functions desde el hito 3): el delta
diario de GLEIF. {"fuente": "gleif_isin_lei"}: el archivo ISIN↔LEI. {"fuente": "sec"}: las
empresas de la SEC.
"""

import os

from refhub.sources import gleif, gleif_isin_lei, sec


def handler(event, context):
    """Punto de entrada de la Lambda. Lambda llama a esta función con (event, context)."""
    # boto3 viene incluido en el runtime de Lambda. Se importa acá adentro para que
    # los tests funcionen sin tenerlo instalado.
    import boto3

    s3 = boto3.client("s3")
    bucket = os.environ["DATA_BUCKET"]  # lo define Terraform en la configuración de la Lambda
    fuente = (event or {}).get("fuente", "gleif")
    if fuente == "gleif":
        result = gleif.upload_to_landing(s3, bucket, gleif.latest_delta_url())
    elif fuente == "gleif_isin_lei":
        result = gleif_isin_lei.upload_latest(s3, bucket)
    elif fuente == "sec":
        result = sec.upload_latest(s3, bucket, os.environ["SEC_CONTACT"])
    else:
        raise ValueError(f"Fuente desconocida: {fuente!r}")
    print(result)  # queda en CloudWatch Logs
    return result  # y Step Functions lo muestra como salida del paso
