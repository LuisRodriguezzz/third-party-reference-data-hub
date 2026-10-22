# ADR 0011 · dbt en el pipeline: CodeBuild llamado por Step Functions

- Estado: aceptado
- Fecha: 2026-10-21

## Contexto

Gold se arma con `dbt build` (ADR 0008), y hasta el hito 5E corría desde la máquina del dueño.
Para que el pipeline sea uno solo (fuentes → silver → gold, sin pasos a mano), dbt tiene que
correr en AWS como un paso más de Step Functions.

Lo que dbt necesita: Python ≥ 3.10 (dbt-core 1.12), salida a internet una vez para instalar los
paquetes, credenciales de AWS para Athena, y unos 4 minutos por corrida (2 de `dbt build`, que
lee unos 140 MB por modelo, más la instalación). No guarda nada en disco: el resultado son
tablas de gold.

Criterio, en este orden:

1. **Sin servidores prendidos ni red privada.** Nada que cobre por hora estando quieto, y nada
   que obligue a una VPC con NAT Gateway o Interface Endpoints (prohibidos en este proyecto).
2. **Disponible en el plan Free** de la nueva experiencia de cuentas, donde vive la cuenta del
   hub.
3. **Integración `.sync` con Step Functions**: el paso espera a que dbt termine y falla si dbt
   falla, sin código propio que pregunte "¿ya terminó?".
4. **Nada que mantener aparte**: ni una imagen de contenedor, ni un paquete armado a mano.
5. Costo por corrida.

## Decisión

- **dbt corre en AWS CodeBuild**, en un proyecto (`refhub-dbt-<ambiente>`, `infra/terraform/dbt.tf`)
  que Step Functions arranca con `codebuild:startBuild.sync` después de que terminaron todas las
  fuentes.
- **Imagen estándar de AWS** (`aws/codebuild/amazonlinux-x86_64-standard:5.0`, Python 3.12) en
  la máquina más chica (`BUILD_GENERAL1_SMALL`: 2 vCPU, 3 GB). No hay imagen propia: el
  `buildspec.yml` (en `dbt/`) instala dbt y corre `dbt build`.
- **Versiones fijas, las mismas que en la máquina del dueño:** el CI arma `requirements.txt` con
  `uv export --only-group dbt --locked` desde `uv.lock`, con hashes, y pip instala con
  `--require-hashes`. Si PyPI sirviera otra cosa que lo que se probó, la instalación falla.
- **El proyecto dbt llega a AWS por el mismo camino que el resto del código** (ADR 0004 y 0005):
  el CI lo publica al mergear en `artifacts/refhub/<versión>/refhub-dbt.zip`, sin pisar una
  versión ya publicada, y CodeBuild lo toma de ahí (`source` de tipo S3). Versión nueva = otra
  clave; volver atrás = la versión anterior en `refhub_version`. No se baja de GitHub en caliente:
  lo que corre en AWS es exactamente lo que se mergeó y se versionó.
- **Sin VPC**: CodeBuild sale a internet (PyPI) y llega a Athena y S3 por sus direcciones
  públicas, con TLS, igual que la Lambda.
- **Permisos mínimos** del rol de CodeBuild: sus logs; leer el zip; Athena solo en el workgroup
  `refhub-dev` (que corta a 1 GB por consulta); leer silver (S3 y catálogo); escribir gold (S3 y
  catálogo) y `athena-results/`.
- **Logs con 14 días de retención** (`/aws/codebuild/refhub-dbt-<ambiente>`), un build a la vez
  (`concurrent_build_limit = 1`), 30 minutos de tope.
- **Sin reintentos** en Step Functions: si dbt falla casi siempre es un test de datos, y repetir
  no lo arregla.

### Disponibilidad y costo (documentación oficial, consultada el 2026-10-21)

- **AWS CodeBuild está en el Free Tier de la nueva experiencia de cuentas**, en la lista de
  servicios incluidos (junto con Step Functions, Lambda, Glue, Athena, ECS y ECR).
  <https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html>
- **Precio:** `general1.small` cuesta 0,005 USD por minuto de build, y el free tier de CodeBuild
  incluye 100 minutos por mes en `general1.small` o `arm1.small`.
  <https://aws.amazon.com/codebuild/pricing/>
- Una corrida de unos 4 minutos son 0,02 USD (o nada, dentro de los 100 minutos: unas 25
  corridas por mes). Lo que lee dbt en Athena (menos de 1 GB por corrida) son menos de
  0,005 USD.

## Alternativas consideradas

- **Lambda con dbt empaquetado.** Sin servidor y barata, pero hay que armar y mantener un paquete
  (o una capa) con dbt-core, el adaptador y sus dependencias, cerca del límite de 250 MB
  descomprimido; dbt escribe `target/` y `logs/`, que en Lambda solo pueden ir a `/tmp`; y el
  tope de 15 minutos queda justo si gold crece. Es un mini-build propio para algo que CodeBuild ya
  resuelve.
- **ECS Fargate con una imagen en ECR.** Está en el plan Free y tiene integración `.sync`
  (`ecs:runTask.sync`), pero suma una imagen que construir, publicar y actualizar, un repositorio
  de ECR y una red: Fargate corre dentro de una VPC, y sin NAT necesita subred pública con IP
  pública. Más piezas para el mismo resultado.
- **Un job de Glue.** Python shell trae Python 3.9 y dbt-core 1.12 pide ≥ 3.10, así que no
  sirve. Un job de Spark (Glue 5.1, Python 3.11) podría instalar dbt, pero son 2 DPU (un cluster
  de Spark) para correr un programa que solo manda SQL a Athena: unas tres veces el costo de
  CodeBuild por corrida, y un uso raro de la herramienta.
- **CodeBuild con cómputo Lambda** (`lambda.arm.1GB`, arranca más rápido y es más barato).
  Solo se puede escribir en `/tmp` y no acepta un timeout propio; la máquina chica de EC2 no
  tiene esas restricciones y el costo es igual de despreciable. Se puede revisar si el tiempo
  de arranque llegara a importar.
- **Bajar el proyecto dbt de GitHub en cada build** (fuente GitHub de CodeBuild). Más simple de
  configurar, pero lo que corre dependería de lo que haya en la rama en ese momento y no de la
  versión publicada; y obligaría a conectar CodeBuild con GitHub.
- **Seguir corriendo dbt a mano.** El pipeline no estaría completo: silver se actualizaría solo
  y gold quedaría atrasado hasta que alguien se acuerde.

## Consecuencias

- El pipeline es uno solo: `refhub-pipeline-<ambiente>` corre las fuentes en paralelo y después
  dbt. Si una fuente falla, gold no se arma con datos a medias.
- Cada build instala dbt de cero (unos 30 a 60 segundos de los 4 minutos). Es el precio de no
  tener una imagen propia; con estos volúmenes no vale la pena un caché.
- dbt sigue corriendo igual desde la máquina del dueño, para probar un cambio antes del PR.
- Riesgos aceptados:
  - Si PyPI no responde, el build falla y la ejecución también. Se vuelve a correr.
  - Los permisos de Glue que pide dbt-athena se armaron leyendo su código (crear, cambiar y
    borrar tablas y versiones de tabla, solo en gold). Si falta alguno, el build falla con
    `AccessDenied` y se agrega en un PR.

## Adenda (hito 6B): métricas, alertas y mantenimiento

- **Las métricas salen del scorecard de gold** (`scorecard_fuentes`, `scorecard_cruce`, en dbt
  con contrato y tests) y las publica una Lambda chica al final del pipeline, con **Embedded
  Metric Format**: un JSON en el log que CloudWatch convierte en métrica, sin `PutMetricData` ni
  permisos de CloudWatch. **Seis métricas agregadas con una sola dimensión** (`ambiente`): cada
  combinación de nombre y dimensiones es una métrica paga, y el free tier cubre diez. El detalle
  por fuente queda en la tabla, no en CloudWatch.
- **La regla de "atrasada" vive en dbt** (los días tolerados por fuente, al principio de
  `scorecard_fuentes.sql`, con su unit test), no en Python: la Lambda solo cuenta.
- **Alertas por mail con SNS**, dos alarmas: `ExecutionsFailed` de Step Functions (gratis) y
  `fuentes_atrasadas > 0`. El tema no se cifra con una clave propia (prohibidas) y con la
  administrada `aws/sns` CloudWatch no puede publicar.
- **`VACUUM` de silver al final del mismo pipeline**, no en una máquina semanal aparte: es lo
  más simple (sin otra máquina, otro rol ni otro schedule), corre siempre después de que
  cambió silver y cuesta unos centavos de requests a S3. **Retención de 7 días**
  (`vacuum_max_snapshot_age_seconds`, que Athena lee de la tabla y el pipeline fija antes de
  cada `VACUUM`, porque las tablas las crea Spark): una semana de time travel; lo anterior se
  recupera desde landing (ADR 0007).
