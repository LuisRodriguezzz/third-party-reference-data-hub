"""Job de Glue: baja el archivo completo de GLEIF a landing/ (carga inicial, una vez).

No usa Spark: corre como un programa Python común en el driver del job. Usa las mismas
funciones que la Lambda, instaladas desde el .whl de refhub (--additional-python-modules).
"""

import sys
from importlib.metadata import version

import boto3
from awsglue.utils import getResolvedOptions

from refhub.sources.gleif import latest_full_url, upload_to_landing

# Glue le pasa al script los parámetros del job como "--DATA_BUCKET valor" en sys.argv.
args = getResolvedOptions(sys.argv, ["DATA_BUCKET"])

print(f"refhub {version('refhub')}")  # qué versión del paquete instaló Glue
result = upload_to_landing(boto3.client("s3"), args["DATA_BUCKET"], latest_full_url())
print(result)  # queda en el log group /aws-glue/refhub-dev/output
