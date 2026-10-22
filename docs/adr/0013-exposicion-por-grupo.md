# ADR 0013 · Exposición por grupo económico

- Estado: aceptado
- Fecha: 2026-10-21

## Contexto

La pregunta de negocio del hub (ADR 0001): "si un grupo económico quiebra, ¿cuánto perdemos?".
Un banco le presta a empresas sueltas, pero el límite de crédito se mide contra el **grupo**: la
controlante final y todas sus controladas. Diez préstamos chicos a diez subsidiarias pueden sumar
más que el préstamo más grande de la cartera, y mirando préstamo por préstamo no se ve.

GLEIF publica las relaciones entre LEIs (nivel 2, `silver.gleif_relaciones`, 491.407 filas):
quién consolida a quién, quién gestiona qué fondo, qué es sucursal de qué. Y publica directamente
la **controlante final** de cada empresa (`IS_ULTIMATELY_CONSOLIDATED_BY`).

## Decisión

- **`gold.grupos`: una fila por LEI con su controlante final.** Si no tiene una que cuente, la
  empresa es la cabeza de su propio grupo.
- **Solo arma grupo la consolidación contable final** (`IS_ULTIMATELY_CONSOLIDATED_BY`). Criterio:
  un grupo económico, para riesgo de crédito, son las empresas que consolidan sus estados
  contables en una misma controlante; si la controlante cae, arrastra a las controladas.
  - **La gestión de fondos no** (`IS_FUND-MANAGED_BY`, 152.593 relaciones): una gestora no es
    dueña de los fondos que administra; el patrimonio del fondo es de sus inversores, y si la
    gestora quiebra el fondo cambia de gestora. Sumarlos al grupo de la gestora inflaría su
    exposición con riesgo que no es suyo.
  - **Tampoco subfondos, feeders ni sucursales** (`IS_SUBFUND_OF`, `IS_FEEDER_TO`,
    `IS_INTERNATIONAL_BRANCH_OF`): son vínculos entre fondos o la misma persona jurídica en otro
    país, no control societario. Se pueden sumar más adelante con un criterio propio.
  - **La consolidación directa** (`IS_DIRECTLY_CONSOLIDATED_BY`) no hace falta: la final ya es la
    cabeza.
- **Solo relaciones vigentes:** `relationship_status = ACTIVE` y sin fecha de fin pasada. Una
  relación `INACTIVE` (37 de consolidación final) o vencida (11 con fecha de fin, 7 de ellas
  ACTIVE) ya no dice quién controla hoy.
- **El registro `LAPSED` cuenta.** LAPSED es que la empresa no renovó el registro de la relación
  en GLEIF, no que sea falsa (38.741 de las 133.216 que quedan). Para sumar exposición es más
  prudente agrupar de más que de menos: un grupo partido en dos esconde riesgo. El estado queda en
  `registro_relacion`, para quien quiera ser más estricto.
- **Controlante final publicada, sin recorrer el árbol.** Es un join, no una consulta recursiva:
  la cabeza la declara la propia empresa ante su LOU, que la valida. Recorrer las relaciones
  directas para reconstruirla sería repetir (peor) lo que GLEIF ya publica.
- **Casos raros, medidos sobre silver el 21-oct-2026:**
  - 2 empresas se declaran controlante final de sí mismas (una SRL italiana y un holding de las
    Islas Caimán, ambas LAPSED): da lo mismo que no tener ninguna, quedan como cabeza de su grupo.
  - 3.245 fondos gestionados por sí mismos (`IS_FUND-MANAGED_BY` con padre = hijo): son fondos
    autogestionados, algo que existe. No afectan porque la gestión de fondos no arma grupo.
  - 316 controlantes finales que a su vez declaran otra controlante final (GLEIF no es
    consistente entre LOUs que actualizan en momentos distintos). Se toma la publicada, sin
    seguir la cadena: seguirla es recursión para corregir el dato de otro, y se ve después si
    hace falta.
  - 11 controlantes finales no están en `silver.gleif_lei` (6 cabezas en `grupos`): quedan con su
    LEI y sin nombre.
- **`gold.exposicion_por_grupo`: la suma por controlante final** de una cartera de préstamos:
  monto total, cuántas empresas del grupo tienen préstamos, cuántos préstamos, el préstamo más
  grande, y si la cabeza está en la golden copy de la SEC (`gold.empresas`, ADR 0008). Un LEI de
  la cartera que no está en GLEIF es su propio grupo: el préstamo no se pierde por no saber a
  quién sumarlo.
- **La cartera es sintética y se declara como tal.** Un banco no publica su cartera, y el hub
  trabaja con fuentes públicas (ADR 0001). `dbt/seeds/cartera_sintetica.csv` lo genera
  `dbt/seeds/generar_cartera.py` con semilla fija: **LEIs reales, montos, productos y préstamos
  inventados**. No lleva nombres: solo LEI, monto y producto. **Las cifras de exposición que salen
  de esta cartera no son un hallazgo y no se publican como tales**; sirven para probar que la suma
  por grupo funciona. Está armada para que la pregunta tenga sentido: 20 grupos reales (12 con la
  cabeza en la SEC) con préstamos chicos a 4 a 10 de sus controladas, y 150 empresas al azar con
  préstamos de cualquier tamaño.
- **Las reglas se prueban con unit tests de dbt** (datos inventados): una subsidiaria suma a su
  controlante final, una empresa sin controlante es su propio grupo, una relación inactiva o
  vencida no cuenta y la gestión de fondos no arma grupo.

## Alternativas consideradas

- **Recorrer el árbol con las relaciones directas** (CTE recursiva o iteraciones en Spark): sirve
  si la fuente solo publica el padre directo. GLEIF publica la cabeza; reconstruirla agrega
  código y costo para un resultado que no es mejor que el declarado.
- **Usar la controlante directa cuando no hay final** (7.483 empresas tienen directa activa y no
  final): las sumaría a un grupo, pero en 422 casos esa directa tiene a su vez otra controlante
  final, así que el "grupo" sería un pedazo de otro. Queda afuera por ahora; es la primera mejora
  si un banco necesita más cobertura.
- **Contar la gestión de fondos como grupo:** es lo que haría la consulta sin filtro. Junta en un
  "grupo" miles de fondos de terceros con su gestora, y eso no es riesgo de crédito de la
  gestora.
- **Excluir las relaciones LAPSED:** más estricto, pero parte grupos reales porque una filial no
  renovó un trámite. Se deja la columna para filtrarlas.
- **Una cartera "realista" con nombres o montos tomados de algún lado:** daría la impresión de
  ser un dato. Se prefiere una claramente inventada y reproducible.

## Métrica

Medido el 21-oct-2026 con el SQL compilado de los modelos, en consultas de solo lectura:

- `grupos`: 3.458.596 LEIs, 133.216 con controlante final (3,9 %), 3.325.558 grupos (la gran
  mayoría, empresas sueltas). El grupo con más empresas: Morgan Stanley, 1.019 LEIs.
- `exposicion_por_grupo` sobre la cartera sintética (296 préstamos a 281 LEIs): 170 grupos con
  préstamos, 20 con más de una empresa con préstamos (los 20 armados así), 12 con la cabeza en la
  SEC, hasta 10 empresas en un mismo grupo, y 18 grupos cuya suma supera al préstamo individual
  más grande de la cartera. Estas cifras describen la cartera inventada, no un riesgo real.

## Consecuencias

- Queda afuera:
  - **Porcentajes de participación:** GLEIF nivel 2 dice quién consolida, no con qué porcentaje.
    Un grupo es todo o nada; prorratear por participación necesitaría otra fuente.
  - **Grupos sin LEI:** si la controlante no tiene LEI o es una persona física, GLEIF lo publica
    como "excepción de reporte" (otro archivo, no cargado). Esas empresas quedan como cabeza de su
    propio grupo, aunque en la realidad tengan dueño.
  - **Grupos que GLEIF no ve:** una empresa que no reportó su controlante queda suelta; no hay
    forma de distinguirla de una que no tiene.
  - **La cadena de controlantes inconsistentes** (los 316 casos de arriba).
- `grupos` sale de la foto completa de silver: si GLEIF cambia la controlante de una empresa, el
  próximo `dbt build` la mueve de grupo sin dejar historia. La historia (quién era la cabeza en
  tal fecha) queda para cuando haga falta, con los snapshots de Iceberg o un snapshot de dbt.
- Para cambiar la cartera hay que volver a correr el script y versionar el CSV nuevo.
