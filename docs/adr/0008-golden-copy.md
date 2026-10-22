# ADR 0008 · Golden copy: el cruce CIK↔LEI y gold con dbt

- Estado: propuesto
- Fecha: 2026-10-21

## Contexto

Un banco anota a la misma empresa con códigos distintos según el área: el LEI en préstamos, el
ISIN de cada bono en inversiones, el FIGI o el ticker en trading y el CIK de la SEC en crédito.
Para sumar la exposición por contraparte hace falta una tabla que diga "estos códigos son la
misma empresa": la golden copy.

Tres de los vínculos los publica alguien: LEI↔ISIN (GLEIF y ANNA, `silver.gleif_isin_lei`),
ISIN→FIGI y ticker (OpenFIGI, `silver.openfigi_tickers`) y CIK↔ticker (la SEC,
`silver.sec_empresas`). El cuarto, **CIK↔LEI, no lo publica nadie**: la SEC no informa el LEI
(el campo vino vacío en 50 de 50 empresas). Hay que deducirlo, y eso es entity resolution.

## Decisión

- **Una fila por empresa de la SEC** (`gold.empresas`, una por CIK, unas 8.000) con el LEI
  elegido, su nombre legal y su estado en GLEIF, el camino que lo dio, `conflicto` y `ambiguo`.
- **Dos caminos, y códigos primero:**
  - **por códigos:** ticker de la SEC → OpenFIGI → ISIN → LEI. Cada eslabón es un dato publicado
    por una fuente; si llega a un LEI, es el emisor de las acciones de esa empresa. Solo cuentan
    las acciones (`security_type` Common Stock, Preference, ADR, REIT, etc.): los fondos y los
    warrants quedan afuera. La SEC escribe la clase con guion (`BRK-B`) y OpenFIGI con barra
    (`BRK/B`); se normaliza al formato de la SEC en un solo lugar (`candidatos_codigos`).
  - **por nombre:** el mismo `nombre_normalizado` (`refhub.names.normalize_name`) en la SEC y en
    GLEIF, sin contar los vacíos (alfabetos no latinos). Sirve cuando no hay códigos, pero dos
    empresas pueden llamarse igual. Como la normalización saca la forma jurídica ("CHEVRON CORP"
    y CHEVRON LIMITED de Malta dan lo mismo), **solo entran LEIs de EE. UU. o que emitieron
    títulos**: una emisora extranjera que cotiza en EE. UU. tiene ISINs, un homónimo cualquiera
    en otro país normalmente no.
- **Desempate**, igual en los dos caminos: primero los LEIs emisores (los que están en
  ISIN↔LEI), después los `ISSUED`, después los de EE. UU. Criterio: preferir la evidencia más
  fuerte de que es la empresa que cotiza (emitió títulos), después la de un registro vigente.
- **Conflicto:** si los dos caminos eligen LEIs distintos, gana códigos y queda
  `conflicto = true`, con el otro LEI en `lei_en_conflicto` para revisarlo.
- **Ambiguo:** si después de desempatar queda más de un candidato, **no se adivina**: la empresa
  queda sin LEI y con `ambiguo = true`. Si el camino por códigos quedó ambiguo no se recurre al de
  nombre: el camino que decide es el primero que tiene candidatos. Criterio estándar en datos de
  referencia: un vínculo falso es peor que uno faltante, porque suma exposición a quien no es.
- **Identificadores en formato largo** (`gold.identificadores`): una fila por
  (cik, esquema, valor), con esquema en CIK, LEI, ISIN, FIGI y TICKER, y la fuente del vínculo
  (`sec`, `gleif_isin_lei`, `openfigi`, y `cruce_codigos` o `cruce_nombre` para el LEI). Es la
  tabla de referencias cruzadas de un maestro de referencia: Barclays Bank tiene 39 mil ISINs,
  que son filas y no una lista en una columna, y un esquema nuevo (CUSIP) es más filas, no una
  columna nueva. Los ISINs y FIGIs cuelgan del LEI elegido.
- **Gold con dbt** (dbt-core 1.12 + dbt-athena 1.11, tablas Iceberg en `refhub_gold_<ambiente>`).
  Gold son cruces entre tablas: SQL es su idioma natural, y dbt resuelve el orden (`ref` y
  `source`), los tests y la documentación. Por el criterio del ADR 0006 (el esquema se declara en
  el formato nativo de la herramienta que crea la tabla), el esquema de cada modelo es su YAML de
  dbt con `contract: enforced`. Athena no hace cumplir NOT NULL ni unique: van como tests de
  datos. La regla del cruce se prueba con **unit tests de dbt** (datos inventados que muestran
  cada caso), que son los tests de negocio de esta capa; dbt-athena los soporta.
- **Se recalcula entero en cada corrida** (`materialized: table`), como el full refresh del
  ADR 0007. Por ahora `dbt build` corre desde la máquina del dueño; en AWS, en el hito 6.

## Alternativas consideradas

- **Solo por nombre:** cubre más empresas sin OpenFIGI, pero no tiene forma de confirmar nada.
  El experimento del 12-oct dio 85 de 100 cruces por nombre confirmados por códigos y 15 sin
  dato: el nombre sirve, pero como segundo camino.
- **Nombre contra todo GLEIF, sin el filtro de país o emisor:** medido el 21-oct sobre silver,
  da 4.591 empresas con LEI por nombre, pero 686 de esos LEIs son extranjeros sin títulos (el
  caso de Chevron, que no tiene LEI y se quedaba con el de CHEVRON LIMITED de Malta). Con el
  filtro: 3.914 empresas con LEI y Chevron sin LEI.
- **Coincidencia aproximada de nombres** (distancia de edición, embeddings): sube el recall y
  baja la precisión de una forma difícil de explicar. Se evalúa después del 5F, si el gold set
  muestra que hace falta.
- **Elegir igual entre empatados** (el más nuevo, el primero): es adivinar. Se prefiere dejarlo
  sin LEI y marcado para revisión.
- **Una columna por esquema con listas** (`isins array<string>`): no escala con empresas de
  miles de títulos y obliga a desarmar listas para buscar un código.
- **Gold en Spark (Glue)**, como silver: un job de varios minutos de 2 DPU para unos joins, y el
  esquema en DDL lejos de los tests de datos. dbt en Athena cobra solo por lo que lee.

## Métrica

Las cifras de cobertura (cuántas empresas quedaron con LEI) no dicen si el LEI es el correcto.
La métrica de acierto es `gold.calidad_matching`, contra un gold set (`dbt/README.md`).

- **Muestra:** 100 CIK de `gold.empresas` elegidos al azar con semilla fija, entre todas las
  empresas y no solo las que tienen LEI: el recall necesita también a las que el cruce dejó sin
  LEI.
- **Etiquetado a ciegas por un agente de IA:** para cada CIK, el agente decide la respuesta
  correcta buscando en GLEIF y en la SEC **sin ver lo que eligió el cruce**: un LEI, `SIN_LEI` (la
  empresa no tiene LEI) o `DUDA` (no se pudo decidir), con su confianza y la evidencia. A ciegas,
  para que la respuesta del cruce no condicione la del etiquetador. Lo etiqueta un agente y no
  una persona por costo: 100 búsquedas a mano en dos registros es mucho trabajo para un proyecto
  de una persona.
- **Auditoría humana de 10:** una persona revisa 10 casos elegidos al azar y anota si llega a la
  misma respuesta. Es lo que dice cuánto confiar en el etiquetado del agente; si la auditoría
  encuentra errores, las cifras se leen con ese descuento.
- **Definiciones:** los `DUDA` se excluyen y se cuentan aparte. **Precisión** = de los CIK a los
  que el cruce les asignó un LEI, cuántos tienen el correcto (un LEI equivocado y un LEI asignado
  a una empresa `SIN_LEI` cuentan en contra). **Recall** = de los CIK que tienen LEI de verdad, a
  cuántos el cruce les encontró el correcto (las `SIN_LEI` no están en el denominador). La
  precisión va por camino y en total; el recall, solo en total, porque una empresa que el cruce
  no encontró no tiene camino.
- **Margen:** el intervalo de confianza del 95 % de Wilson, el estándar para proporciones con
  muestras chicas. La aproximación normal (p ± 1,96·√(p(1-p)/n)) se pasa de 1 cuando la
  proporción está cerca de 1 y da margen cero si acierta todo; Wilson no. Con 100 casos el margen
  es de varios puntos: la cifra se publica con su intervalo, no sola.

**Resultado (PENDIENTE):** medido el PENDIENTE sobre la corrida PENDIENTE. Precisión total
PENDIENTE (IC 95 %: PENDIENTE a PENDIENTE), por códigos PENDIENTE y por nombre PENDIENTE. Recall
PENDIENTE (IC 95 %: PENDIENTE a PENDIENTE). Casos `DUDA`: PENDIENTE. Auditoría: PENDIENTE de 10
coinciden.

## Consecuencias

- Medido el 21-oct-2026 solo con el camino por nombre (OpenFIGI todavía sin datos): de 8.017
  CIK, 3.959 tienen candidato por nombre, 3.914 quedan con LEI, 45 ambiguos (0,6 %) y 4.058 sin
  candidato. Apple sale con `HWUPKR0MPOU8FGXBT394`. Los LEIs de las empresas elegidas suman
  434.832 ISINs para `identificadores`.
- **Limitaciones conocidas:**
  - **Empresas sin LEI** (Chevron): quedan sin LEI, que es lo correcto, pero no se distinguen de
    las que tienen LEI y no se encontró.
  - **Emisoras extranjeras** (~20 % de la SEC): su ticker en EE. UU. suele ser un ADR, cuyo ISIN
    puede estar a nombre del banco depositario y no de la empresa; y su nombre en GLEIF puede
    estar en otro idioma o alfabeto.
  - **Cambios de nombre y fusiones:** el nombre de la SEC y el de GLEIF pueden ser de épocas
    distintas.
  - **Tickers de preferidas, warrants y units** (`JPM-PC`, `-WT`, `-UN`): la SEC y OpenFIGI no los
    escriben igual más allá de la barra, así que esos no cruzan por códigos. No cambia el
    resultado si la acción común de la misma empresa cruza.
  - **LEIs dados de baja:** un candidato único con `LAPSED` o `RETIRED` gana igual; el estado
    queda en la tabla para que lo vea quien la usa.
- Cambiar `normalize_name` cambia el camino por nombre: hay que recalcular silver
  (`--FULL_REFRESH true`, ADR 0007) y después correr `dbt build`.
