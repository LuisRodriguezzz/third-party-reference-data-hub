# Gold con dbt (runbook)

Los modelos de gold: la golden copy de empresas (ADR 0008) y la exposición por grupo económico
(ADR 0013). dbt lee las tablas de silver y crea las de `refhub_gold_dev` como Iceberg, en
`s3://<bucket de datos>/gold/<tabla>/<id>`.

| Modelo | Qué es |
|---|---|
| `candidatos_codigos` | los LEIs posibles de cada CIK por ticker → OpenFIGI → ISIN → LEI |
| `candidatos_nombre` | los LEIs posibles de cada CIK por nombre normalizado |
| `empresas` | una fila por CIK con el LEI elegido, el camino, `conflicto` y `ambiguo` |
| `identificadores` | una fila por (cik, esquema, valor): CIK, LEI, ISIN, FIGI y TICKER |
| `grupos` | una fila por LEI con su controlante final (la cabeza de su grupo económico) |
| `exposicion_por_grupo` | la suma de la cartera sintética por controlante final |
| `scorecard_fuentes` | una fila por fuente: última publicación, días de atraso, `atrasada`, filas y % a cuarentena |
| `scorecard_cruce` | una fila: empresas, % con LEI, por camino, conflictos, ambiguas y sin candidatos |
| `calidad_matching` | precisión y recall del cruce contra el gold set, con su margen (abajo) |

## La cartera sintética (seed)

`seeds/cartera_sintetica.csv` es una cartera de préstamos **inventada**: LEIs reales de GLEIF con
montos, productos y préstamos **inventados**. No es la cartera de ningún banco, no lleva nombres,
y **las cifras de exposición que salen de ella no son un hallazgo ni se publican como tales**.
Existe para que `exposicion_por_grupo` tenga algo que sumar (ADR 0013).

La genera `seeds/generar_cartera.py` con semilla fija, leyendo silver y gold en Athena (solo
lectura). El CSV queda versionado: no cambia hasta que alguien vuelva a correr el script, y con
la misma foto de GLEIF sale igual.

```powershell
uv run --group dbt python dbt/seeds/generar_cartera.py
```

`dbt build` la carga como tabla (`refhub_gold_dev.cartera_sintetica`, en Parquet: dbt-athena
carga los seeds así, no como Iceberg) antes de los modelos que la usan.

En AWS, dbt corre como último paso del pipeline, en CodeBuild (`buildspec.yml`, ADR 0011; cómo
correrlo suelto: `infra/terraform/README.md`, "Gold en CodeBuild"). Desde tu máquina se corre
igual, con tus credenciales de AWS, para probar un cambio antes del PR.

## El gold set y `calidad_matching` (5F)

`scorecard_cruce` dice cuántas empresas quedaron con LEI; no dice si es el LEI correcto. Para eso
está el **gold set**: 100 CIK de la SEC con la respuesta correcta decidida por otro camino, y
`calidad_matching`, que compara esa respuesta con lo que eligió el cruce (ADR 0008, "Métrica").

**Cómo se arma:**

1. **Muestra:** 100 CIK de `gold.empresas` elegidos al azar con semilla fija (se puede volver a
   sacar la misma). Al azar entre todas las empresas, no entre las que tienen LEI: así entran
   también las que el cruce dejó sin LEI, que son las que mide el recall.
2. **Etiquetado a ciegas:** un agente de IA busca cada empresa en GLEIF y en la SEC **sin ver lo
   que eligió el cruce** y anota en la planilla el LEI correcto, `SIN_LEI` (la empresa no tiene
   LEI) o `DUDA` (no se pudo decidir), con su confianza y la evidencia. A ciegas, para que la
   respuesta del cruce no lo arrastre.
3. **Auditoría:** una persona revisa 10 casos elegidos al azar y anota si llega a la misma
   respuesta (`cik;coincide`, con sí o no). Es la medida de cuánto confiar en el agente.
4. **Seed:** `seeds/preparar_gold_set.py` lee la planilla (y la auditoría, si está) y escribe
   `seeds/gold_set.csv` con lo que la métrica necesita: `cik` (10 dígitos), `lei_correcto`,
   `confianza`, `etiquetado_por`, `auditado` y `auditoria_coincide`. Sin nombres ni evidencia:
   eso queda en la planilla. Frena con un error claro si no son 100 filas, si hay un CIK
   repetido o si una respuesta no es un LEI de 20 caracteres, `SIN_LEI` ni `DUDA`.

```powershell
uv run python dbt/seeds/preparar_gold_set.py <planilla etiquetada>.csv [<auditoría>.csv]
```

Las dos entradas son CSV de Excel: separador `;` y BOM. El CSV que sale queda versionado y
`dbt build` lo carga como `refhub_gold_dev.gold_set` (los tipos están en `dbt_project.yml`: el
CIK como texto, para no perder los ceros).

**Qué dice cada columna de `calidad_matching`** (una fila por segmento):

| Columna | Qué es |
|---|---|
| `segmento` | `codigos` o `nombre` (los casos que el cruce resolvió, o dejó ambiguos, por ese camino) o `total` |
| `casos` | CIK del gold set en el segmento, incluidos los `DUDA` |
| `duda` | casos que no se pudieron decidir: no entran en ninguna otra cifra |
| `asignados` | el cruce les asignó un LEI (denominador de la precisión) |
| `correctos` | el LEI asignado es el correcto |
| `lei_equivocado` | la empresa tiene LEI y el cruce le asignó otro |
| `asignados_sin_lei` | la empresa no tiene LEI y el cruce le asignó uno: falso positivo |
| `con_lei_real` | la empresa tiene LEI de verdad (en `total`, denominador del recall) |
| `no_encontrados` | la empresa tiene LEI y el cruce la dejó sin ninguno |
| `ambiguos` | el cruce no eligió porque había candidatos empatados |
| `auditados`, `auditoria_coincide` | casos revisados por una persona, y en cuántos coincidió con el agente |
| `precision_puntual` | `correctos / asignados` |
| `recall_puntual` | `correctos / con_lei_real`, solo en `total` |
| `*_desde`, `*_hasta` | el intervalo de confianza del 95 % de Wilson de cada una |

Siempre se cumple que `asignados = correctos + lei_equivocado + asignados_sin_lei` y que
`con_lei_real = correctos + lei_equivocado + no_encontrados`. El recall va solo en `total`: una
empresa que el cruce no encontró no tiene camino, así que por camino no hay denominador que
repartir.

Mientras `gold_set.csv` no tenga filas, `calidad_matching` sale con ceros y cifras nulas.

## Requisitos

- La base `refhub_gold_dev` creada (Terraform, `catalogo.tf`) y las cuatro tablas de silver con
  datos, incluida `openfigi_tickers`.
- AWS CLI con credenciales (`aws sts get-caller-identity` responde). dbt usa la misma cadena de
  credenciales, así que `profiles.yml` no tiene ninguna.

## Correrlo

Desde la raíz del repo, una vez:

```powershell
uv sync --group dbt
```

Cada vez (PowerShell):

```powershell
$env:REFHUB_DATA_BUCKET = terraform -chdir=infra/terraform output -raw data_bucket
cd dbt
uv run dbt debug    # la primera vez: que se conecte a Athena
uv run dbt build    # crea las tablas y corre los tests de datos y los unit tests
```

`dbt build` va en orden: cada modelo se crea, se prueban sus tests de datos y recién entonces
se sigue con el que depende de él. Los unit tests de un modelo corren antes de crearlo.

- Solo un modelo y lo que depende de él: `uv run dbt build --select empresas+`.
- Solo la regla del cruce (unit tests, datos inventados): `uv run dbt test --select test_type:unit`.
  Igual necesita conexión: dbt arma las consultas en Athena, y las tablas de entrada tienen que
  existir para saber sus tipos.
- Sin conexión, para ver que el proyecto está bien escrito: `uv run dbt parse` (con cualquier
  valor en `REFHUB_DATA_BUCKET`).

## Cosas a saber

- **La regla de "atrasada"** (cuántos días puede pasar cada fuente sin publicar) está al principio
  de `scorecard_fuentes.sql`, y su unit test fija la fecha de hoy con la variable
  `fecha_scorecard` (por defecto, `current_date`). La Lambda de métricas solo cuenta las
  atrasadas: no repite la regla.
- **Los unit tests crean una tabla temporal** en `refhub_gold_dev` (`<nombre del test>__dbt_tmp`)
  y la borran al terminar. Si un unit test se corta por un error, la tabla puede quedar y el
  siguiente falla con `TABLE_ALREADY_EXISTS`: borrarla (`aws glue delete-table --database-name
  refhub_gold_dev --name <tabla>`) y volver a correr.

- **El tope de 1 GB del workgroup corta también las consultas de dbt.** Hoy cada modelo lee unos
  140 MB.
- **El esquema de cada tabla es el YAML del modelo** (`contract: enforced`): si el SELECT no da
  esas columnas con esos tipos, dbt no crea la tabla. Athena no hace cumplir NOT NULL ni unique:
  por eso van como tests de datos.
- **Nombres en minúscula** y sin `schema` propio en los modelos: si un modelo define su schema,
  dbt lo pega a la base (`refhub_gold_dev_<schema>`), que no existe.
- **Cada build escribe en una carpeta nueva** de `gold/<tabla>/` (`s3_data_naming: table_unique`):
  dbt arma la tabla nueva al lado y recién al final la cambia por la vieja, así que la tabla
  nunca queda vacía. Iceberg en Athena lo exige: sin `unique`, dbt no compila.
- **Las tablas de gold se recalculan enteras en cada build** (`materialized: table`): es el
  mismo criterio de reproceso del ADR 0007, y con estos tamaños no hace falta incremental.
