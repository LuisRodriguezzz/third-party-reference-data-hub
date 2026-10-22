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
