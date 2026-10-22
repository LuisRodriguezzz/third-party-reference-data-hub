# ADR 0012 · La API de permisos: políticas compiladas en el CI, una Lambda con Function URL

- Estado: aceptado
- Fecha: 2026-10-21

## Contexto

El hito 7 dejó el catálogo DCAT, las licencias en ODRL y un evaluador con rdflib (ADR 0009).
Falta que las aplicaciones del banco puedan preguntar, en el momento de usar un dato, **¿puedo
usar este dataset para este propósito?**, y que cada respuesta quede registrada: un banco tiene
que poder mostrar quién consumió qué dato y con qué permiso.

## Decisión

- **Las políticas se compilan en el CI, no se evalúan en cada pedido.** El job `publicar` corre
  `python -m refhub.licencias`, que evalúa todas las combinaciones aplicación × dataset ×
  propósito (hoy 432) y escribe `decisiones.json`. Se publica en
  `artifacts/refhub/<versión>/decisiones.json`, junto al código de esa versión y con la misma
  regla de no pisar una versión publicada. La API solo busca la fila (`refhub.permisos`).
  Criterio: es el patrón de los *bundles* de OPA (Open Policy Agent): las políticas se
  construyen y versionan como un artefacto, y el punto de decisión solo las carga. Consecuencias
  buenas:
  - La Lambda no necesita rdflib (ni el extra `licencias`): usa el mismo `refhub-lambda.zip` que
    la ingesta, responde en milisegundos y su arranque en frío es leer un JSON de S3.
  - Cada respuesta dice de qué versión de las políticas salió (`version_politicas`, la versión
    del paquete). Como esa versión no se pisa en S3, una decisión vieja del log se puede
    reproducir buscando la tabla de su versión.
  - La tabla entera se puede revisar antes de publicarla, y los tests corren el mismo camino
    (compilar → JSON → buscar).
  - Esto cambia lo que decía el ADR 0009 sobre que la Lambda iba a empaquetar rdflib: rdflib
    queda solo en el CI y en los tests.
- **Un nombre desconocido es un error, no un "no".** Un pedido con una aplicación, un dataset o
  un propósito que el catálogo no tiene recibe un 400 que dice cuál. Si se negara en silencio,
  quien pide no podría distinguir "la licencia no lo permite" de "escribiste mal el nombre".
- **La tabla vive en un JSON publicado, no en DynamoDB.** Son cientos de filas que cambian solo
  cuando cambia una política, y una política cambia por PR. Una tabla de DynamoDB sumaría un
  recurso, permisos y una carga de datos para guardar lo que entra en la memoria de la Lambda.
  Pasa a convenir cuando la tabla llegue a millones de combinaciones (no entra cómoda en
  memoria ni se lee rápido en un arranque en frío) o cuando haya que cambiar políticas sin
  desplegar una versión.
- **Function URL con `AuthType = AWS_IAM`, sin API Gateway.** La URL es privada: cada pedido va
  firmado con SigV4 por una identidad IAM con permiso de invocarla; sin firma, 403. Para una
  sola ruta, API Gateway agrega un recurso, etapas y costo sin dar nada que haga falta hoy.
  Pasa a convenir cuando haga falta lo que solo da API Gateway: varias rutas, cuotas por
  cliente, WAF, un dominio propio o autenticación con tokens (por ejemplo, OIDC de las apps).
- **Una línea de log estructurada por decisión (el registro de consumo).** JSON con el
  `request_id`, el ARN IAM que firmó el pedido (`llamante`), el pedido, el estado y la
  respuesta, en el log group de la Lambda con retención de 14 días. Se consulta con Logs
  Insights sin otra infraestructura. Criterio: el log de decisiones de OPA y los requisitos de
  trazabilidad de uso de datos de un banco (quién, qué, cuándo, con qué regla).
- **Permisos mínimos.** El rol de la Lambda lee un solo objeto (`decisiones.json` de su
  versión) y escribe en su log group. Nada más del bucket.

## Alternativas consideradas

- **Evaluar en caliente con rdflib en la Lambda:** suma rdflib al zip (o una capa), un arranque
  en frío más lento (parsear los `.ttl`) y una respuesta que depende de correr el evaluador en
  producción. La tabla compilada responde lo mismo, porque las políticas no cambian entre
  versiones.
- **DynamoDB:** ver arriba; es la evolución natural si la tabla crece o si las políticas tienen
  que cambiar sin desplegar.
- **API Gateway (HTTP API o REST):** ver arriba.
- **Una Function URL pública (`AuthType = NONE`) con una clave propia:** sería inventar
  autenticación; IAM ya la resuelve, firma cada pedido y deja registro en CloudTrail.
- **OPA como servicio:** obligaría a traducir ODRL a Rego (ADR 0009) y a operar un contenedor.
  Se toma de OPA el patrón (compilar y distribuir un bundle), no el motor.

## Consecuencias

- Cambiar una política es editar el `.ttl`, subir la versión y mergear: el CI compila, publica y
  el apply apunta la Lambda a la tabla nueva. Sin subir la versión, la tabla vieja sigue
  publicada y en uso (el CI avisa "ya existía y no se pisa").
- La aplicación (`app`) la declara quien pide; la identidad que se verifica es la IAM que firma.
  Hoy cualquiera con permiso de invocar puede preguntar en nombre de cualquier aplicación (la
  respuesta es informativa, no da acceso al dato). Si la API pasara a ser la que habilita el
  acceso, hay que atar cada rol IAM a su aplicación y rechazar el pedido que no coincida.
- Con `aws lambda invoke` el evento no trae la identidad: el `llamante` queda vacío en el log y
  quién invocó se ve en CloudTrail.
- Los logs duran 14 días, como el resto del hub. Un banco real guardaría este registro mucho más
  (años, según el regulador), exportándolo a S3; acá alcanza para mostrar el mecanismo.
