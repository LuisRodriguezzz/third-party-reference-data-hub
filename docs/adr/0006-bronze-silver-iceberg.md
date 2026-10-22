# ADR 0006 · Bronze y silver en Iceberg, con contrato y esquema declarado

- Estado: aceptado
- Fecha: 2026-10-11

## Contexto

Landing tiene los zips de GLEIF tal cual: el archivo completo y deltas que se solapan. Hacen
falta tablas que se consulten con SQL, datos validados sin perder los inválidos, y que repetir
una corrida no duplique nada. Además, el esquema de silver no puede depender de lo que traiga
el primer DataFrame que se escriba: si alguien saca un `to_timestamp`, la tabla nacería con la
fecha como texto y nada lo frenaría.

## Decisión

- **Glue 5.1 (Spark 3.5, Python 3.11) con Iceberg** en el Glue Data Catalog; **Athena** para
  consultar, con un workgroup que corta las consultas que leen más de 1 GB.
- **Bronze:** todas las columnas como texto, más linaje (`_archivo`, `_fecha_publicacion`,
  `_cargado_en`). Particionado por archivo y escrito con `overwritePartitions`: recargar un
  archivo reemplaza sus filas, no las duplica.
- **El contrato de silver tiene dos mitades:**
  - **estructura**: el DDL de cada tabla en SQL (`src/refhub/ddl/*.sql`: tipos, NOT NULL y
    descripción). Viaja dentro del `.whl` y el job lo ejecuta al arrancar
    (`CREATE TABLE IF NOT EXISTS`). Iceberg rechaza cualquier escritura que no lo respete, y el
    `SELECT` final de cada escritura nombra las columnas y castea los tipos. Si no coincide,
    **el job para**: es un error del pipeline.
  - **validez** (`row_problem`): las reglas por fila. Si una fila no cumple, **va a la
    cuarentena** con su motivo y el job sigue: es un dato malo de la fuente. La misma función
    corre en pytest y en Spark como UDF.
- **Criterio para dónde declarar un esquema:** en el formato nativo de la herramienta que crea
  la tabla. Tablas creadas por Spark/Iceberg → DDL en SQL. Modelos de dbt (hito 5) → el YAML de
  dbt con `contract: enforced`. Un acuerdo con otro equipo → ODCS.
- **Silver:** una fila por LEI, con `MERGE`. **Gana lo que GLEIF publicó último**: la fila del
  archivo más nuevo (el nombre empieza con la fecha y hora de publicación); dentro de un mismo
  archivo, la de actualización más nueva (fechas en UTC, no como texto). Criterio: para quedarse
  con la última versión de cada clave se ordena por la secuencia de la fuente, no por un campo
  que la fuente no garantiza que crezca (es lo que hacen las herramientas de CDC con su columna
  de secuencia). **Registro de archivos procesados** escrito al final.
- **El código se publica por versión, desde el CI.** Al mergear, el CI arma el `.whl` una vez y
  publica en `artifacts/refhub/<versión>/` el `.whl`, el zip de la Lambda (el mismo `.whl`) y
  los scripts de `glue/`; recién después aplica Terraform, que solo dice qué versión usar
  (`refhub_version`). Una versión publicada no se pisa (`put-object --if-none-match '*'`).
  Entra con el rol de apply del ADR 0005. Criterio: armar una vez y desplegar el mismo
  artefacto en todos lados, con una versión que dice de qué commit salió.
- **El contrato es interno, no ODCS.** Un contrato de datos en sentido estricto (ODCS) es un
  acuerdo publicado por el productor para sus consumidores, con dueños y SLA. Entre bronze y
  silver alcanza con la mitad técnica: esquema declarado y reglas por fila.

## Alternativas consideradas

- **Lambda para todo:** no entra el procesamiento del completo (3,4 M de filas, 5 GB de CSV).
- **Glue Python shell:** trae Python 3.9 y el paquete exige 3.11.
- **Parquet sin Iceberg:** sin commits atómicos ni `MERGE`.
- **Esquema deducido del DataFrame** (como estaba al principio): la tabla nace con lo que traiga
  la primera corrida, y Iceberg no permite pasar después una columna a NOT NULL.
- **Tabla definida en Terraform** (`aws_glue_catalog_table` de Iceberg): el esquema queda lejos
  del código que escribe y la tabla tendría dos dueños (Terraform y Spark).
- **YAML propio + motor genérico:** Spark no lee YAML, así que hace falta un motor propio que lo
  lea y aplique (casteos, rechazos, deduplicación). Ese motor se paga solo cuando **varias
  tablas siguen el mismo patrón**: cada tabla nueva es un YAML más. Con una sola tabla y una
  regla que no entra en YAML (el dígito verificador MOD 97), es código para mantener sin ganar
  nada. **Se revisa en el hito 5, al llegar la tercera tabla de silver**: si comparten el
  patrón, se pasa a YAML + motor genérico (los `.sql` se convierten de forma mecánica).
- **Esquema en código Python con un comparador propio:** se probó y se descartó por la misma
  razón: es un mini-framework con sus propios tests, cuando la tabla ya hace cumplir el esquema.
- **ODCS para el contrato interno:** es un acuerdo publicado por el productor para sus
  consumidores; tiene sentido en la **salida** del hub (hitos 6 y 7), no entre capas.
- **AWS Glue Data Quality, Great Expectations, Deequ:** son para la calidad del lote, no para el
  esquema; quedan como opción para el scorecard del hito 6.
- **Scripts subidos por Terraform y `.whl` armado a mano** (como estuvo hasta el 4D): el script
  y el paquete podían quedar de versiones distintas, y lo que corría en AWS no era
  necesariamente lo que probó el CI.
- **Gana la fecha de actualización más nueva** (la primera versión de la regla): la fecha la pone
  cada LOU y puede ir para atrás. En la primera corrida en AWS, el LEI `74370055WK4U9VLVZH47`
  venía en el delta del 2-oct como `PENDING_TRANSFER` (otra LOU pidió la transferencia) y en el
  completo del 10-oct como `ISSUED`, de vuelta en la LOU original con su registro del 28-sep.
  Ganó el delta, y silver quedó con una versión que GLEIF ya no publicaba. Con esa regla, ni
  siquiera un completo nuevo la corrige.

## Consecuencias

- Tres niveles, cada uno con su reacción: **estructura → el job para; fila → cuarentena;
  lote → se mide y se avisa** (hito 6).
- Si se suma una regla al contrato que exige un campo, ese campo tiene que pasar a NOT NULL en el
  DDL (y al revés): las dos mitades tienen que contar la misma historia.
- `CREATE TABLE IF NOT EXISTS` no toca una tabla existente: si el DDL cambió y la tabla no, la
  escritura falla porque las columnas no coinciden. Cómo se cambia una tabla con datos: ADR 0007.
- Un completo nuevo de GLEIF realinea silver con la fuente: lo que publica el completo pisa lo
  que venía de deltas anteriores.
- Cambiar la regla de qué versión gana no corrige lo que ya está en silver: hay que recalcular
  con `--FULL_REFRESH true` (ADR 0007). Lo que decía antes (borrar los archivos del registro y
  volver a correr el job) no alcanza: el `MERGE` solo pisa una fila con algo más nuevo, así que
  el mismo archivo otra vez no cambia nada.
- Cambiar `src/` o `glue/` sin subir la versión no publica nada: el CI avisa y en AWS sigue
  corriendo lo anterior. Volver atrás es un PR con la versión anterior.
- Levantar el hub desde cero exige crear el bucket de datos y publicar el código antes del
  primer apply completo (pasos en el runbook).
- Cada corrida de un job cuesta al menos un minuto de 2 DPU; por eso el schedule sigue apagado.
- Iceberg guarda las versiones viejas de los archivos hasta que se expiran los snapshots.
- Si GLEIF cambia el formato del CSV, bronze falla a propósito.

## Revisión en el hito 5C: la tercera tabla de silver

Con `sec_empresas` ya hay tres tablas en silver. Se revisó si conviene pasar a YAML + motor
genérico, como estaba previsto:

| Tabla | Entrada | Cómo se escribe | Reglas |
|---|---|---|---|
| `gleif_lei` | deltas que se solapan, vía bronze | `MERGE` con la regla de qué versión gana | dígito verificador del LEI (MOD 97), estados, fechas |
| `gleif_isin_lei` | CSV dentro de un zip, 9,3 M de filas | reemplazo total (foto completa) | dígito verificador del ISIN (Luhn) y del LEI |
| `sec_empresas` | JSON compacto, 10 mil filas | reemplazo total (foto completa) | CIK, nombre, ticker; una fila por ticker |

- **No comparten el patrón.** Hay tres formatos de entrada y dos formas de escribir, y las reglas
  que importan (los dígitos verificadores, el nombre normalizado) son código: no se escriben en
  YAML. Un motor genérico necesitaría un caso especial para cada tabla.
- **Lo que se repite es poco:** crear las tablas desde su DDL, buscar el último archivo de
  landing y escribir la cuarentena. Son pocas líneas por job, y duplicadas se leen mejor que
  detrás de una abstracción.
- **Decisión:** se sigue con DDL en SQL + reglas en Python. Los dos jobs de foto completa
  (ISIN↔LEI y SEC) quedan duplicados a propósito; si llega una tercera foto completa con el
  mismo patrón, se evalúa una función común en `refhub`.
- **Hito 9, la tercera foto completa (`gleif_relaciones`):** llegó, con el mismo patrón. Se
  sacaron a `refhub/silver.py` las cuatro cosas que eran idénticas en los tres jobs
  (`full_refresh_flag`, `create_tables`, `latest_landing_key` y `already_in_silver`), como
  funciones sueltas que reciben `spark` y `s3` por parámetro (sin clases y sin importar pyspark:
  la Lambda importa `refhub`). Lo que cambia de una fuente a otra (cómo se lee, el contrato,
  qué columnas se escriben) sigue en cada job, que se lee de arriba abajo. Criterio: la regla
  del tercer caso; con tres copias, un arreglo en una (por ejemplo, el chequeo de
  `--FULL_REFRESH`) había que acordarse de repetirlo en las otras dos. Un motor genérico sigue
  sin convenir: las tres fuentes se leen distinto (CSV en Spark, JSON y CSV en el driver).
- **Migraciones** (reemplazada por el ADR 0007: sin pasos a mano; el job agrega las columnas
  nuevas y `--FULL_REFRESH` recalcula): el primer cambio a una tabla con datos
  (`nombre_normalizado` en `gleif_lei`) va como `migraciones/0001_*.sql`, numerado y en el
  repo, y se corre una vez en Athena antes de correr el job. Criterio: migraciones versionadas,
  como en Flyway o Liquibase, pero sin la herramienta: con un cambio cada tanto no se justifica
  sumarla.
