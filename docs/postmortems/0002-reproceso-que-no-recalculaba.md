# Postmortem 0002 · El reproceso documentado no recalculaba nada

- Fecha del incidente: 2026-10-12 (detectado) · resuelto el 2026-10-21
- Estado: resuelto
- Formato: sin culpas. Describe qué pasó y qué se cambió en el sistema, no quién se equivocó.

## Resumen

El runbook decía que, para reprocesar silver, alcanzaba con borrar un archivo del registro
`gleif_archivos_procesados` y volver a correr el job. Era falso: el `MERGE` de silver solo pisa
una fila si lo que llega es **estrictamente más nuevo** (`>`), así que el mismo archivo procesado
otra vez no cambia nada. Se descubrió al agregar una columna (`nombre_normalizado`) a una tabla
con datos, un cambio que se resolvió con una migración corrida a mano en Athena y un parche de una
sola vez en el job (`fill_missing_names`). Se reemplazó todo por un modo de recálculo explícito,
`--FULL_REFRESH true`, y por una regla de evolución de esquema sin pasos a mano
([ADR 0007](../adr/0007-evolucion-de-esquema-y-reprocesos.md)). La prueba: un full refresh de
las tres tablas dio **0 filas distintas** contra la versión anterior, comparada con time travel de
Iceberg.

## Impacto

- **Ningún dato incorrecto llegó a silver.** El parche completó la columna nueva en las filas
  viejas (0 nulos verificados en Athena).
- El impacto fue de **procedimiento**: el camino documentado para recuperarse de un error (una
  regla mal escrita, un cambio de normalización) no funcionaba, y fallaba en silencio: el job
  terminaba en verde sin recalcular. Si se hubiera usado después de cambiar una regla, silver
  habría quedado con la regla vieja y todos convencidos de que tenía la nueva.
- Los jobs de foto completa (ISIN↔LEI y SEC) tenían el mismo problema por otro lado: si el último
  archivo ya estaba en silver, no hacían nada, y no había forma de forzarlos.
- Un cambio de esquema exigía un paso manual por ambiente: si alguien se olvidaba de la
  migración, el job fallaba.

## Línea de tiempo

| Fecha | Qué pasó |
|---|---|
| 2026-10-11 | Postmortem 0001: el reproceso por el registro funciona en ese caso puntual, porque la regla nueva vuelve "más nuevo" al completo. Queda documentado como el procedimiento general. |
| 2026-10-12 | Hito 5C (PR #14, 6ee3a48): `gleif_lei` suma `nombre_normalizado`. Se corre a mano en Athena `migraciones/0001_*.sql` (`ALTER TABLE ... ADD COLUMNS`) y el job trae `fill_missing_names`, un `MERGE` que solo completa esa columna. |
| 2026-10-12 | La corrida de `refhub-gleif-silver-dev` (126 s) dice "Nada nuevo en bronze" y después completa `nombre_normalizado`. Athena: 3.458.596 filas, 0 nulos. |
| 2026-10-12 | En la revisión surge la pregunta: ¿cómo cargó silver si el log decía que no había nada nuevo? Son dos chequeos separados. Y al responderla aparece lo importante: **reprocesar no habría servido** por el `>` estricto del `MERGE`. El runbook y la guía estaban mal. |
| 2026-10-12 | Se propone el diseño: modo full refresh, cambios aditivos aplicados por el job dueño de la tabla, expand/contract para lo que rompe, y sacar la migración y el parche. |
| 2026-10-21 | PR #15 (b72bc81): `--FULL_REFRESH true\|false` en los tres jobs de silver (default `false` en Terraform), cuarentena con `overwrite(_archivo in …)`, salen `migraciones/` y `fill_missing_names`, ADR 0007, ADR 0006 y runbook corregidos. Plan 0/7/0, apply 0/6/0. |
| 2026-10-21 | Prueba en AWS: los tres jobs con full refresh, en paralelo, SUCCEEDED (gleif_silver 300 s con los 4 archivos de bronze, ISIN↔LEI 224 s, SEC 195 s). |
| 2026-10-21 | Comparación con time travel: `EXCEPT` en los dos sentidos contra el snapshot anterior en `gleif_lei`, su cuarentena, `gleif_isin_lei` y `sec_empresas`: **0 filas distintas**. Un solo snapshot nuevo por tabla. |
| 2026-10-21 | Corrida normal después: "Nada nuevo en bronze" (165 s) y "ya está en silver: no se escribe nada" (104 s y 123 s). Ningún snapshot nuevo. |

## Causa raíz

El diseño incremental estaba bien para el día a día y mal para recalcular, y el runbook mezcló las
dos cosas:

- **El `MERGE` con `>` estricto es lo que hace idempotente la corrida diaria**: volver a procesar
  un archivo no duplica ni pisa nada. Por la misma razón, no puede recalcular: una fila de la misma
  versión nunca "gana".
- **Los jobs de foto completa saltean el archivo que ya está en silver**, otra vez a propósito,
  para no gastar una corrida en nada.
- **No existía un camino de recálculo**, y el procedimiento de reproceso del runbook no se había
  probado en el caso general. Funcionó una vez (postmortem 0001) por una razón particular.
- Ante la primera columna nueva, a falta de ese camino, apareció un script especial
  (`fill_missing_names`): código de una sola vez que queda vivo y es un segundo camino que escribe
  la misma tabla.

## Cómo se detectó

Por una pregunta en la revisión del cambio, no por una falla: el log de una corrida decía "no se
escribe nada" y después escribía. Explicar por qué llevó a leer la condición del `MERGE` y a ver
que el reproceso documentado nunca podía recalcular. Ningún test ni alarma lo podía ver: el
job terminaba bien en los dos casos.

## Qué se cambió

- **Dos modos explícitos** ([ADR 0007](../adr/0007-evolucion-de-esquema-y-reprocesos.md)):
  incremental para el día a día y `--FULL_REFRESH true` para cuando cambia una regla. En full
  refresh, `gleif_silver` relee todo bronze, arma la última versión de cada LEI con la misma regla
  y reemplaza la tabla y el registro enteros en un commit; los jobs de foto completa vuelven a
  procesar el último archivo aunque ya esté. Criterio: tareas como funciones puras de su entrada,
  y reprocesar es recalcular y reemplazar entero (Maxime Beauchemin, "Functional Data
  Engineering"); es lo que hace `dbt --full-refresh`.
- **La cuarentena se reemplaza por archivo con `overwrite`**, no con `overwritePartitions`: si un
  archivo reprocesado ya no tiene rechazos, los viejos se borran igual.
- **Evolución de esquema sin pasos a mano:** un ambiente nuevo nace con el DDL final que viaja en
  el `.whl`; un cambio aditivo lo aplica el job dueño de la tabla al arrancar, de forma
  idempotente; lo que rompe va con expand/contract. Salieron `migraciones/` y `fill_missing_names`.
- **Runbook y ADR 0006 corregidos:** borrar filas del registro ya no figura como forma de
  reprocesar.
- **La prueba de que el full refresh no cambia nada cuando las reglas no cambiaron**: `EXCEPT`
  contra el snapshot anterior con time travel de Iceberg. Es la forma de probar un refactor de un
  pipeline: mismo dato de entrada, mismo resultado, fila por fila.

## Lecciones

- **Idempotente no es lo mismo que recalculable.** Una corrida que no hace nada la segunda vez es
  justamente la que no sirve para aplicar una regla nueva. Hacen falta los dos modos, con nombre.
- **Un procedimiento de recuperación que no se probó no existe.** El runbook describía un reproceso
  que nunca se había corrido en el caso que importa.
- **Un log tiene que decir lo que pasó.** "No se escribe nada" seguido de una escritura confundió;
  fue la pista, pero no debería hacer falta.
- **Nada de scripts de una sola vez que quedan vivos.** Si hace falta un backfill, es el modo de
  recálculo normal del job, no un camino aparte.
- **Time travel como red y como prueba:** los snapshots de Iceberg permitieron comparar antes y
  después sin copiar tablas. Duran 7 días (el `VACUUM` del pipeline); lo anterior se recupera
  reprocesando desde landing.
