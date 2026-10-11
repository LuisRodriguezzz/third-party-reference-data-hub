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
- **Silver:** una fila por LEI, la de actualización más nueva (fechas en UTC, no como texto),
  con `MERGE`. **Registro de archivos procesados** escrito al final.
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
- **YAML propio:** Spark no lee YAML, así que hace falta un motor propio que lo convierta en
  tablas y chequeos. Es código para mantener sin ganar nada sobre el DDL.
- **Esquema en código Python con un comparador propio:** se probó y se descartó por la misma
  razón: es un mini-framework con sus propios tests, cuando la tabla ya hace cumplir el esquema.
- **ODCS para el contrato interno:** es un acuerdo publicado por el productor para sus
  consumidores; tiene sentido en la **salida** del hub (hitos 6 y 7), no entre capas.
- **AWS Glue Data Quality, Great Expectations, Deequ:** son para la calidad del lote, no para el
  esquema; quedan como opción para el scorecard del hito 6.

## Consecuencias

- Tres niveles, cada uno con su reacción: **estructura → el job para; fila → cuarentena;
  lote → se mide y se avisa** (hito 6).
- Si se suma una regla al contrato que exige un campo, ese campo tiene que pasar a NOT NULL en el
  DDL (y al revés): las dos mitades tienen que contar la misma historia.
- Cambiar el esquema de una tabla que ya tiene datos es una migración aparte (`ALTER TABLE`).
  `CREATE TABLE IF NOT EXISTS` no toca una tabla existente: si el DDL cambió y no se migró, la
  escritura falla porque las columnas no coinciden.
- Cada corrida de un job cuesta al menos un minuto de 2 DPU; por eso el schedule sigue apagado.
- Iceberg guarda las versiones viejas de los archivos hasta que se expiran los snapshots.
- Si GLEIF cambia el formato del CSV, bronze falla a propósito.
