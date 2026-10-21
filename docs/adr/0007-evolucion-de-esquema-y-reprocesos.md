# ADR 0007 · Evolución de esquema y reprocesos

- Estado: aceptado
- Fecha: 2026-10-21

## Contexto

En el hito 5C, `silver.gleif_lei` (que ya tenía datos) sumó la columna `nombre_normalizado`. Se
hizo con una migración numerada (`migraciones/0001_*.sql`) corrida a mano en Athena y un parche
en el job (`fill_missing_names`) que completó las filas viejas una sola vez. Funcionó, pero dejó
dos problemas:

- **Un paso manual por ambiente.** Si alguien se olvida de correr la migración, el job falla.
  Y un ambiente nuevo no la necesita: `CREATE TABLE IF NOT EXISTS` con el DDL actual ya crea la
  columna, así que el "historial de migraciones" no describe nada que haya que reproducir.
- **No había forma correcta de recalcular.** El runbook decía que reprocesar era borrar el
  archivo del registro `gleif_archivos_procesados` y correr el job. Es falso: el `MERGE` de
  silver solo pisa una fila si lo que llega es estrictamente más nuevo, así que el mismo
  archivo procesado otra vez no cambia nada. Y los jobs de foto completa (ISIN↔LEI y SEC) no
  hacen nada si el último archivo ya está en silver.

Va a hacer falta pronto: cuando se ajuste `normalize_name` (después de medir el cruce con la
SEC), hay que recalcular `nombre_normalizado` en `gleif_lei` y en `sec_empresas`.

## Decisión

- **Fuente de verdad: el DDL que viaja en el `.whl`** (`src/refhub/ddl/*.sql`, ADR 0006). Un
  ambiente nuevo nace con el esquema final; no hay historial de migraciones que reproducir.
- **Cambio aditivo** (una columna nueva, nullable): lo aplica **el job dueño de la tabla al
  arrancar**, de forma idempotente, en el mismo PR y la misma versión que el código que la
  escribe. Cada ambiente se pone al día solo y nadie corre nada a mano. El patrón:

  ```python
  # Después de create_tables(): si la tabla es anterior a la columna, se la agrega.
  if "nombre_normalizado" not in spark.table(silver).columns:
      spark.sql(f"ALTER TABLE {silver} ADD COLUMNS (nombre_normalizado string)")
  ```

  Hoy no hay ningún cambio pendiente, así que **ese código no se escribe todavía**: se agrega
  con el próximo cambio aditivo. Criterio: nada se agrega por las dudas.
- **Recalcular** (cambió una regla, o una columna nueva necesita valores en las filas viejas):
  correr el job con **`--FULL_REFRESH true`**. Los tres jobs de silver lo aceptan, con default
  `false` declarado en Terraform (Step Functions los sigue llamando sin argumentos):
  - `gleif_silver` procesa **todos** los archivos de bronze, arma la última versión de cada LEI
    con la misma regla de siempre y reemplaza silver entera en un solo commit; el registro de
    archivos procesados también se reemplaza entero.
  - `gleif_isin_lei_silver` y `sec_silver` vuelven a procesar el último archivo aunque ya esté
    en silver.

  Criterio: las tareas son funciones puras de sus entradas, y reprocesar es recalcular y
  reemplazar entero (Maxime Beauchemin, "Functional Data Engineering"); es lo que hace
  `dbt --full-refresh`. Incremental para el día a día, full refresh para los cambios de regla.
- **La cuarentena se reemplaza por archivo con `overwrite`**, no con `overwritePartitions`:
  este último solo reemplaza las particiones que vienen en el DataFrame, así que si un archivo
  reprocesado ya no tiene filas rechazadas, sus rechazos viejos quedarían. Con
  `overwrite(_archivo in (...))` se borran y escriben en un solo commit aunque no venga ninguna.
- **Cambios que rompen** (renombrar, cambiar un tipo de forma incompatible, borrar una columna,
  pasar a NOT NULL): **expand/contract**, el "parallel change" de Martin Fowler. Se agrega lo
  nuevo (cambio aditivo), se escriben las dos cosas, se migran los consumidores y lo viejo se
  borra en un PR posterior.
- **Red de seguridad: los snapshots de Iceberg.** Después de un full refresh se puede consultar
  la versión anterior o volver a ella, hasta que se expiren los snapshots (la expiración queda
  para el hito 6).

## Alternativas consideradas

- **Migraciones numeradas corridas a mano** (lo que había): un paso manual por ambiente, y si
  te lo olvidás el job falla.
- **Una herramienta como Flyway o Liquibase:** suma una herramienta y una tabla de historial
  para un cambio cada tanto, y no resuelve el recálculo.
- **Dejar que Iceberg agregue columnas al escribir** (`mergeSchema`): el esquema vuelve a
  depender del DataFrame, que es lo que el ADR 0006 descartó.
- **Scripts especiales de backfill** como `fill_missing_names`: código de una sola vez que queda
  vivo, y dos caminos distintos que escriben la misma tabla.

## Consecuencias

- La carpeta `migraciones/` y `fill_missing_names` salen: ya corrieron en el único ambiente
  (dev), y un ambiente nuevo no los necesita.
- Un full refresh de `gleif_lei` relee todo bronze: unos minutos de 2 DPU, centavos. Con
  copy-on-write el `MERGE` ya reescribía la tabla entera, así que el costo de escritura es
  parecido.
- Un full refresh da el mismo resultado que las corridas incrementales con las reglas de hoy:
  la regla de qué versión gana es la misma ventana por LEI en los dos modos.
- Los snapshots viejos ocupan espacio en S3 hasta que se expiran.
- Cambiar una regla sin correr el full refresh deja las filas viejas con la regla anterior: el
  PR que cambia la regla dice qué jobs hay que correr con `--FULL_REFRESH true`.
