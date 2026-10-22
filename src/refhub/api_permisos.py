"""La Lambda de la API de permisos: recibe `{app, dataset, proposito}` y responde la decisión.

Es un enchufe fino: lee la tabla de decisiones de S3, le pasa el pedido a `refhub.permisos` y
deja una línea de log por cada decisión. Se llama por su Function URL (con firma IAM) o con
`aws lambda invoke`; en los dos casos responde lo mismo (ver el runbook de infra/terraform).
"""

import base64
import json
import os

from refhub import permisos

# La tabla se lee de S3 en el arranque en frío y queda en memoria mientras el entorno de la
# Lambda viva: los pedidos siguientes no vuelven a S3. Para cambiar de tabla hay que desplegar
# otra versión, que es otra clave en S3 y un entorno nuevo.
_tabla = None


def handler(event, context):
    global _tabla
    if _tabla is None:
        import boto3  # viene en el runtime de Lambda; acá adentro, para no exigirlo en los tests

        objeto = boto3.client("s3").get_object(
            Bucket=os.environ["DECISIONES_BUCKET"], Key=os.environ["DECISIONES_KEY"]
        )
        _tabla = permisos.cargar(json.loads(objeto["Body"].read()))

    pedido = None
    try:
        pedido = _pedido(event)
        respuesta, estado = permisos.decidir(_tabla, pedido), 200
    except permisos.PedidoInvalido as error:
        respuesta, estado = {"error": str(error)}, 400

    # El registro de consumo: quién pidió qué y qué se le respondió, una línea JSON por decisión.
    # Es lo que un banco audita ("¿quién usó el feed ficticio para trading?") con Logs Insights.
    registro = {
        "evento": "decision_de_permiso",
        "request_id": context.aws_request_id,
        # La identidad IAM que firmó el pedido (solo por la Function URL). Con `aws lambda
        # invoke` no viene en el evento y queda None: quién invocó está en CloudTrail.
        "llamante": event.get("requestContext", {})
        .get("authorizer", {})
        .get("iam", {})
        .get("userArn"),
        "pedido": pedido,
        "estado": estado,
        "respuesta": respuesta,
    }
    print(json.dumps(registro, ensure_ascii=False))

    # La forma que espera una Function URL; con `aws lambda invoke` llega igual, tal cual.
    return {
        "statusCode": estado,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(respuesta, ensure_ascii=False),
    }


def _pedido(event: dict) -> dict:
    """Por la Function URL, el pedido viene como texto en `body`; por invoke, es el evento."""
    if "body" not in event:
        return event
    cuerpo = event["body"] or ""
    if event.get("isBase64Encoded"):  # la URL codifica en base64 los cuerpos que no son texto
        cuerpo = base64.b64decode(cuerpo)
    try:
        return json.loads(cuerpo)
    except json.JSONDecodeError as error:
        raise permisos.PedidoInvalido(f"el cuerpo no es JSON: {error}") from error
