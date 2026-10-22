# Postmortem 0001 · Silver se quedó con una versión que GLEIF ya no publicaba

- Fecha del incidente: 2026-10-11
- Estado: resuelto el mismo día
- Formato: sin culpas. Describe qué pasó y qué se cambió en el sistema, no quién se equivocó.

## Resumen

En la primera corrida de silver en AWS, la tabla `refhub_silver_dev.gleif_lei` quedó con una
fila que no coincidía con lo que GLEIF publicaba: el LEI `74370055WK4U9VLVZH47` figuraba como
`PENDING_TRANSFER` (de un delta del 2-oct) cuando el archivo completo del 10-oct, más nuevo, lo
traía como `ISSUED`. La regla para elegir la versión vigente de cada LEI era "gana la
`last_update` más nueva", y esa fecha la pone cada LOU (la entidad que registra el LEI) y puede
ir para atrás. Se cambió la regla a "gana el archivo publicado más nuevo; la fecha solo desempata
dentro de un archivo" ([ADR 0006](../adr/0006-bronze-silver-iceberg.md)) y se reprocesó.

## Impacto

- **1 fila de 3.458.376** en silver con una versión vieja: estado `PENDING_TRANSFER` y otra LOU
  como gestora, en vez de `ISSUED` con su LOU original.
- No había consumidores todavía: gold no existía. Nadie usó el dato.
- El problema de fondo era más grande que la fila: con esa regla, **ni siquiera un archivo
  completo nuevo lo corregía**, porque la versión con la fecha más nueva seguía ganando. Cualquier
  vuelta atrás de una LOU iba a dejar el mismo tipo de error, sin aviso.

## Línea de tiempo

Las fechas de los datos son las de publicación de GLEIF; las de las acciones, las de la bitácora
del proyecto.

| Fecha | Qué pasó |
|---|---|
| 2026-09-28 | Última actualización del registro del LEI en su LOU original (`743700OO…`), estado `ISSUED`. |
| 2026-10-02 | Otra LOU (`485100001PLJJ09NZT59`) pide la transferencia. El delta `20261002-1600` trae el LEI en `PENDING_TRANSFER`, con `last_update` del 2-oct. |
| 2026-10-10 | La transferencia no se concreta. El completo `20261010-1600` trae el LEI de vuelta en la LOU original, con su registro del 28-sep (`ISSUED`). |
| 2026-10-11 | Primera corrida de `refhub-gleif-silver-dev` (PR #5): 140 s, SUCCEEDED. Delta del 2-oct: 15.957 filas, 0 a cuarentena; completo del 10-oct: 3.458.632 filas, 256 a cuarentena. |
| 2026-10-11 | Revisión en Athena: `count = count distinct lei = 3.458.376`, cuarentena 256. Al mirar de qué archivo salió cada fila, **1 sola** sale del delta y no del completo. |
| 2026-10-11 | Se baja a la fila, se comparan las columnas de las dos versiones y se confirma con la API de GLEIF: hoy el LEI está `ISSUED`. |
| 2026-10-11 | PR #7 (rama `silver-version-por-publicacion`): la regla nueva, el caso real como test (36 tests), ADR 0006 actualizado. Plan 0/3/0. |
| 2026-10-11 | Merge (1c62620), apply del CI 0/2/0. Se borra del registro de procesados la fila del completo y se corre el job: 166 s, SUCCEEDED, reprocesa solo el completo. |
| 2026-10-11 | Verificación: el LEI en `ISSUED` desde el completo; silver 3.458.376 = distinct, **0 filas del delta**; cuarentena 256. |

## Causa raíz

La regla de deduplicación ordenaba las versiones de un LEI por `LastUpdateDate`, suponiendo que
esa fecha solo crece. No es así: la pone cada LOU, y cuando una transferencia se cae, la LOU
original vuelve a publicar su registro con su fecha anterior. La versión del 2-oct tenía la fecha
más nueva, pero ya no era lo que GLEIF publicaba.

El dato que sí crece siempre es el **orden de publicación**: el nombre de cada archivo de GLEIF
empieza con la fecha y hora en que se publicó. Lo último que publicó la fuente es lo vigente.

## Cómo se detectó

Por una revisión manual después de la primera corrida, no por una alarma. La cuenta esperada era
que todas las filas salieran del completo del 10-oct (más nuevo que el delta del 2-oct). Un "1"
que no cerraba llevó al método: desconfiar del número raro, bajar a la fila, comparar columnas y
confirmar contra la fuente.

## Qué se cambió

- **La regla** (PR #7): gana la fila del archivo más nuevo; dentro de un mismo archivo, la de
  `last_update` más nueva (en UTC, no como texto). Se aplica igual en la ventana por LEI dentro de
  la corrida y en el `MERGE` contra lo que ya estaba en silver.
- **El criterio quedó escrito** en el [ADR 0006](../adr/0006-bronze-silver-iceberg.md): para
  quedarse con la última versión de cada clave se ordena por la secuencia de la fuente, no por un
  campo que la fuente no garantiza que crezca. Es lo que hacen las herramientas de CDC con su
  columna de secuencia.
- **El caso real es un test** en `tests/test_contract.py`: si alguien vuelve a la regla vieja, el
  test falla.
- **El reproceso**: esta vez alcanzó con borrar del registro la fila del completo, porque con la
  regla nueva el completo es "más nuevo" que el delta y el `MERGE` lo pisa. En general no alcanza
  (ver el [postmortem 0002](0002-reproceso-que-no-recalculaba.md)); hoy el camino es
  `--FULL_REFRESH true` ([ADR 0007](../adr/0007-evolucion-de-esquema-y-reprocesos.md)).

## Lecciones

- **Un campo de fecha de la fuente no es una secuencia.** Antes de usar un campo para ordenar
  versiones, preguntarse quién lo escribe y si puede ir para atrás. Si no hay garantía, ordenar por
  algo que la controle uno (el orden de llegada o de publicación).
- **Un número que no cierra por uno es una pista, no ruido.** La revisión de linaje (de qué archivo
  vino cada fila) encontró el error con 1 caso en 3,4 millones.
- **Los casos reales van a los tests.** El test con el LEI de la transferencia documenta la regla
  mejor que un ejemplo inventado.
- **Pendiente:** esta revisión fue manual. El scorecard del hito 6 mide atrasos y cuarentena, pero
  no "filas de silver que no vienen del último completo"; sería un buen chequeo automático después
  de cada completo.
