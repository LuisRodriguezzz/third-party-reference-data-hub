# ADR 0004 · Ingesta de GLEIF con Lambda y Step Functions

- Estado: aceptado
- Fecha: 2026-10-02

## Contexto

El delta diario de GLEIF tiene que llegar a landing en S3 sin intervención manual, sin
duplicados, sin archivos a medias y con reintentos si GLEIF no responde. GLEIF publica varias
veces por día y cada delta `LastDay` trae los cambios de las últimas 24 horas, así que dos
deltas seguidos se solapan.

## Decisión

- **Una Lambda que solo baja y guarda.** No valida ni transforma: landing es la copia tal cual
  de lo que mandó el proveedor (ADR 0002). La validación y la cuarentena van en el paso
  siguiente (hito 4).
- **Step Functions Standard** invoca la Lambda con reintentos: muchos y rápidos para errores
  pasajeros del servicio Lambda, pocos y espaciados para errores de la tarea (por ejemplo,
  GLEIF caído).
- **EventBridge Scheduler creado apagado** (`DISABLED`): el patrón queda listo, pero nada corre
  ni gasta solo mientras se construye.
- **Partición por fecha de publicación:** `dt=` sale del nombre del archivo que pone GLEIF, no
  de la fecha de ejecución (event time, no processing time).
- **Idempotencia por archivo:** antes de bajar se consulta S3 con HeadObject; si el objeto ya
  existe, no se hace nada. Un PutObject en S3 es atómico, así que no hace falta el `.part`.
- **Permisos mínimos:** la Lambda solo lee y escribe en `landing/gleif/` (más `s3:ListBucket`
  para distinguir 404 de 403); Step Functions solo invoca esa Lambda; el scheduler solo arranca
  esa máquina.
- **Empaquetado:** el zip lo arma Terraform (`archive_file`) y usa el boto3 que trae el runtime
  `python3.12`, porque el código no tiene dependencias.

## Alternativas consideradas

- **Schedule que invoque la Lambda directo:** más simple, pero sin historial de ejecuciones ni
  un lugar para sumar el paso de bronze en el hito 4.
- **`date.today()` para la partición:** un reintento pasada la medianoche guardaría el mismo
  archivo en otra carpeta, y el chequeo de idempotencia no lo detectaría.
- **Validar en la Lambda y guardar solo filas válidas:** un bug en la validación haría perder
  datos sin poder reprocesarlos.
- **Build del paquete en CI, con artefacto versionado en S3 y boto3 empaquetado:** es el patrón
  de producción. Se adopta en el hito 4, cuando Glue necesite el `.whl`; pasar la Lambda a ese
  artefacto es un cambio en el lugar (`~`), sin destruir nada.

## Consecuencias

- Costo prácticamente cero dentro de los niveles gratuitos de Lambda, Step Functions y
  Scheduler.
- La idempotencia es **por archivo**, no por dato: landing guarda los deltas solapados tal
  cual, y la deduplicación por LEI y fecha de actualización va en silver (hito 4).
- Riesgos aceptados:
  - Si un proveedor corrigiera un archivo ya publicado sin cambiarle el nombre, no se volvería
    a bajar. Con GLEIF no pasa: cada publicación es un archivo nuevo. Si hiciera falta, se
    compararía también el tamaño o un hash.
  - La Lambda solo mira la última publicación. Si no corre por más de 24 horas, queda un hueco
    que se rellena a mano (backfill con `LastWeek` o con el historial de publicaciones).
  - Si GLEIF cambia el formato del nombre del archivo, `landing_key` falla a propósito en vez
    de inventar una fecha.
  - Si dos ejecuciones corren exactamente a la vez, las dos podrían subir el mismo archivo;
    el resultado es el mismo objeto.
