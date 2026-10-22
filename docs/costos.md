# Costos

Lo que gastó el hub de verdad, cuánto cuesta una corrida y qué lo mantiene barato. Cada cifra dice
si está **medida** (con fecha y de dónde sale) o **estimada** (con la cuenta). Los precios son de
`us-east-1`, de las páginas oficiales de AWS linkeadas.

Para el detalle exacto por servicio, la consola de **Billing and Cost Management** (Bills y Cost
Explorer desde la consola). No uses la API de Cost Explorer para esto: cobra por pedido.

## Lo gastado: el crédito de la cuenta

La cuenta está en el **plan Free** de la nueva experiencia de cuentas de AWS: no se cobra nunca a
una tarjeta; se gasta un crédito, y la cuenta se cierra cuando se acaba o cuando vence el plan
([documentación](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html)).
El saldo se consulta gratis con:

```bash
aws freetier get-account-plan-state
```

| Fecha | Crédito que queda (USD) | Qué había en ese momento |
|---|---:|---|
| 2026-09-27 | 177,44 | Ningún recurso del hub todavía (plan Free hasta 2027-03-05) |
| 2026-09-28 | 177,43 | Bucket del state, bucket de datos y budget |
| 2026-10-02 | 177,40 | + Lambda de ingesta y Step Functions |
| 2026-10-11 | 177,35 | + jobs de carga inicial y bronze; primera carga del completo de GLEIF |
| 2026-10-11 (noche) | 177,23 | + silver de GLEIF |
| 2026-10-12 | 177,09 | Pipeline de GLEIF por CI, varias corridas de prueba |
| 2026-10-12 (tarde) | 177,05 | + ISIN↔LEI y SEC en silver |
| **2026-10-21** | **176,78** | Todo lo de hoy: OpenFIGI, relaciones, gold con dbt, full refresh de silver, API, pipeline completo |

**Medido:** entre el 27-sep y el 21-oct-2026 el saldo bajó **0,66 USD**. Dos aclaraciones para
leerlo bien:

- El saldo es **de la cuenta**, no de un tag: es un techo de lo que gastó el hub, no una cifra
  exacta por recurso. El desglose está en la consola de Billing.
- El saldo se actualiza con demora: las corridas de las últimas horas pueden no estar reflejadas
  todavía.

Los valores de cada fecha salen de la bitácora del proyecto; el último, de la consulta de arriba
corrida el 2026-10-21.

## Cuánto cuesta una corrida del pipeline

### Precios (consultados para el ADR 0011 y este documento)

| Servicio | Precio | Fuente |
|---|---|---|
| Glue (jobs de Spark) | 0,44 USD por DPU-hora, por segundo, **mínimo 1 minuto** por corrida. Cada job usa 2 DPU (2 workers G.1X) | [AWS Glue pricing](https://aws.amazon.com/glue/pricing/) |
| CodeBuild (`general1.small`) | 0,005 USD por minuto; 100 minutos gratis por mes | [AWS CodeBuild pricing](https://aws.amazon.com/codebuild/pricing/) |
| Athena | 5 USD por TB leído (mínimo 10 MB por consulta) | [Amazon Athena pricing](https://aws.amazon.com/athena/pricing/) |
| S3 Standard | 0,023 USD por GB-mes (primeros 50 TB) | [Amazon S3 pricing](https://aws.amazon.com/s3/pricing/) |
| Lambda, Step Functions, CloudWatch (10 métricas y 10 alarmas), SNS por mail | Dentro de sus niveles gratuitos con este uso | páginas de precios de cada servicio |

### Una corrida completa, medida

La corrida `prueba-completa-20261022T021256` de `refhub-pipeline-dev` del **2026-10-21** terminó
`SUCCEEDED` de punta a punta: las cuatro fuentes, OpenFIGI, dbt, las métricas y el `VACUUM` de
las 10 tablas de silver. Duró **31 min 38 s** (23:12:56 a 23:44:35, hora de Buenos Aires). Los
tiempos salen de `aws stepfunctions get-execution-history`, `aws glue get-job-runs`,
`aws codebuild batch-get-builds` y `aws athena get-query-execution`.

**Glue** (DPU-segundos que informa Glue; 2 DPU por job):

| Job | Duración | DPU-segundos | Costo |
|---|---:|---:|---:|
| `refhub-gleif-bronze-dev` | 71 s | 142 | 0,017 USD |
| `refhub-gleif-silver-dev` | 103 s | 206 | 0,025 USD |
| `refhub-gleif-isin-lei-dev` | 145 s | 290 | 0,035 USD |
| `refhub-openfigi-dev` | 296 s | 592 | 0,072 USD |
| `refhub-sec-dev` | 89 s | 178 | 0,022 USD |
| `refhub-gleif-relaciones-dev` | 71 s | 142 | 0,017 USD |
| **Total Glue** | | **1.550** | **0,19 USD** |

Cuenta: 1.550 DPU-s / 3.600 = 0,43 DPU-hora × 0,44 USD = 0,19 USD.

**El resto, también medido:**

| Paso | Lo medido | Costo |
|---|---|---:|
| CodeBuild: `dbt build` + instalación | 2 min 34 s de build (`batch-get-builds`; la fase de `dbt build` en sí, 92 s); el paso de Step Functions, 2 min 39 s | 0,013 USD (0,015 si se cobra el minuto entero); 0 dentro de los 100 minutos gratis del mes |
| Athena: lo que lee dbt | 127 consultas, 598 MB leídos en total | < 0,01 USD (aun contando el mínimo de 10 MB por consulta) |
| Athena: métricas y mantenimiento | 22 consultas (2 de la Lambda de métricas, 10 `ALTER TABLE` y 10 `VACUUM`), 1.112 bytes leídos en total; cada una tardó menos de 4 s | ~0 |
| Lambda | 5 invocaciones (4 descargas + métricas) | 0 (nivel gratuito) |
| Step Functions | 35 estados recorridos | 0 (nivel gratuito: 4.000 transiciones por mes) |

**Una corrida completa costó unos 0,21 USD**, y el 90 % es Glue.

Para comparar: la corrida anterior del mismo día (`prueba-completa-20261022T015535`, que falló en
dbt por un error de compilación ya corregido) gastó 2.638 DPU-s de Glue, unos 0,32 USD, porque
había más para procesar (bronze cargó deltas nuevos de GLEIF y tardó 205 s en vez de 71 s). El
costo de una corrida depende de cuánto dato nuevo hay: **entre 0,20 y 0,35 USD** en lo medido.

Dónde se va el tiempo: las fuentes tardan 8 min 3 s (la rama más larga es ISIN↔LEI seguida de
OpenFIGI), dbt 2 min 39 s, las métricas 9 s y el mantenimiento de silver **20 min 47 s**. Este
último recorre las tablas de a una (`MaxConcurrency = 1`) y cada paso de Athena espera alrededor
de un minuto en Step Functions aunque la consulta termine en segundos. No cuesta más (un flujo
Standard cobra por transición, no por minuto), pero es el lugar obvio para acortar la corrida.

Una corrida sin nada nuevo igual paga el arranque de Spark: medidas entre el 11 y el 21-oct-2026,
las corridas que contestaron "nada nuevo" o "ya está en silver" tardaron entre 51 y 165 segundos,
y aun un job de 30 segundos paga el mínimo de 1 minuto de 2 DPU (0,015 USD).

### Lo que queda guardado (medido)

El bucket de datos tenía **861 objetos y 2,32 GB** el 2026-10-21 (`aws s3 ls --recursive
--summarize`): unos 0,05 USD por mes en S3 Standard.

## Por qué el schedule está apagado

El schedule diario (`refhub-pipeline-dev-diario`, 18:30 UTC) existe en Terraform pero está
`DISABLED`. Corriendo todos los días, 30 corridas de 0,20 a 0,35 USD (lo medido) son **entre 6 y
10 USD por mes** (estimado), que se come casi todo el budget de 10 USD, y gastaría el crédito en
algo que nadie consume a diario.
El pipeline se corre a mano cuando hace falta (runbook, "El pipeline"). Prenderlo es un PR que
cambia una línea, con el plan mostrando un solo `~`.

Si hiciera falta correrlo seguido, lo primero sería no pagar Spark cuando no hay nada nuevo: que
el paso de la Lambda diga si bajó algo y Step Functions saltee el job si no (un `Choice`).

## Lo que protege el presupuesto

Valores por defecto, todos en el código:

- **Budget de 10 USD por mes** (`aws_budgets_budget` en `infra/terraform/main.tf`), con aviso por
  mail al 50 % del gasto real y al 100 % del pronosticado.
- **Workgroup de Athena que cancela cualquier consulta que lea más de 1 GB**
  (`bytes_scanned_cutoff_per_query` en `catalogo.tf`): una consulta mal escrita cuesta como mucho
  medio centavo. Corta también a dbt (cada modelo lee unos 140 MB).
- **Logs siempre con retención de 14 días**: cada log group (Lambda, Glue, CodeBuild, métricas, API)
  lo crea Terraform con `retention_in_days`, en vez de dejar que el servicio lo cree con retención
  infinita.
- **Sin red privada que se cobre por hora**: ni NAT Gateway ni Interface Endpoints. Lambda, Glue y
  CodeBuild llegan a S3, Athena y las APIs por sus direcciones públicas, con TLS.
- **Servicios prohibidos en el proyecto** (pueden gastar el crédito en horas): Neptune en todas sus
  formas (ADR 0010), OpenSearch gestionado, EKS, claves KMS propias, sesiones interactivas de Glue
  y crawlers.
- **Glue sin reintentos, una corrida a la vez y con timeout** (`modules/glue_job`): un job que falla
  no se paga dos veces, y uno colgado se corta.
- **CodeBuild con tope de 30 minutos** y un build a la vez; dbt sin reintentos.
- **Ciclo de vida en S3**: `tmp/` se borra al día, los resultados de Athena a los 7 días, los
  archivos de ISIN↔LEI y de relaciones en landing a los 30 días (silver guarda la última foto), y
  las subidas incompletas al día.
- **`VACUUM` de silver al final del pipeline**: los snapshots de Iceberg de más de 7 días se
  expiran y sus archivos se borran (copy-on-write deja una copia de la tabla por cada `MERGE`).
- **Seis métricas con una sola dimensión**: cada combinación de nombre y dimensiones es una métrica
  paga; el nivel gratuito cubre diez (ADR 0011).
- **El plan Free**: aunque todo lo anterior fallara, la cuenta no puede generar cobros en una
  tarjeta (ADR 0010).
