# Infraestructura del hub (runbook)

Dos proyectos de Terraform:

- `bootstrap/`: el bucket donde vive el state y los dos roles con los que el CI entra a AWS.
  Lo aplicás vos, desde tu máquina.
- esta carpeta: el hub (bucket de datos, budget, Lambda, Step Functions y jobs de Glue). Guarda su
  state en el bucket de `bootstrap/` y **lo aplica el CI** al mergear a `main`.

## Requisitos

- Terraform >= 1.10 y AWS CLI con credenciales configuradas (`aws sts get-caller-identity` responde).
- Región `us-east-1`.

## Levantar todo desde cero

1. **Bucket del state (una sola vez).**
   ```powershell
   cd infra/terraform/bootstrap
   terraform init
   terraform plan      # 11 to add: bucket del state (5) + roles del CI (6)
   terraform apply
   ```
2. **Configurar el backend.** Copiar `backend.hcl.example` a `backend.hcl` y poner el número
   de cuenta (`aws sts get-caller-identity --query Account --output text`).
3. **Configurar las variables.** Crear `terraform.tfvars` con el mail de las alertas:
   ```hcl
   alert_email = "tu-mail@ejemplo.com"
   ```
4. **Crear el bucket de datos primero.** La Lambda y los jobs usan el código publicado en ese
   bucket (ver "Versiones del código"), así que el bucket tiene que existir antes.
   ```powershell
   cd infra/terraform
   terraform init -backend-config="backend.hcl"
   terraform apply -target="aws_s3_bucket.data"   # 1 to add
   ```
5. **Publicar el código a mano (solo esta vez; después lo hace el CI).** Desde la raíz del repo:
   ```powershell
   uv build --wheel
   $v = uv version --short
   $destino = "s3://refhub-data-<cuenta>-dev/artifacts/refhub/$v"
   aws s3 cp "dist/refhub-$v-py3-none-any.whl" "$destino/"
   aws s3 cp "dist/refhub-$v-py3-none-any.whl" "$destino/refhub-lambda.zip"
   aws s3 cp glue/ "$destino/glue/" --recursive --exclude "*" --include "*.py"
   ```
6. **Crear el resto del hub.**
   ```powershell
   cd infra/terraform
   terraform plan      # 28 to add: bucket de datos (3 más) + budget + Lambda (4) + orquestación (6) + Glue (14)
   terraform apply     # solo la primera vez; después aplica el CI (ver abajo)
   ```
7. **Verificar.** `terraform plan` tiene que decir `No changes`.

`backend.hcl`, `terraform.tfvars` y los `terraform.tfstate` no se suben a git.

## Cambios por pull request (CI)

Requisito: la cuenta tiene que tener registrado el proveedor OIDC de GitHub
(`token.actions.githubusercontent.com`); se crea una vez por cuenta. Para ver si está:
`aws iam list-open-id-connect-providers`. Si no está:

```powershell
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com
```

Configuración de GitHub (una vez, desde `bootstrap/`, después de aplicarlo):

```powershell
gh variable set AWS_ROLE_PLAN --body "$(terraform output -raw ci_plan_role_arn)"
gh variable set AWS_ROLE_APPLY --body "$(terraform output -raw ci_apply_role_arn)"
gh variable set TF_STATE_BUCKET --body "$(terraform output -raw state_bucket)"
gh secret set ALERT_EMAIL
```

Cada cambio:

1. `git switch main`, `git pull` y una rama nueva (`git switch -c <rama>`).
2. Probar en tu máquina: `uv run pytest` y `terraform plan` las veces que haga falta.
3. `git push -u origin <rama>` y `gh pr create --fill`.
4. El job `terraform-plan` deja el plan como comentario del PR y lo actualiza en cada push.
   Leerlo. Si aparece `-/+` o `must be replaced` sobre un bucket, no mergear: buscar la línea
   marcada con `# forces replacement`.
5. `gh pr merge <número> --squash --delete-branch`. El job `terraform-apply` aplica.
6. `git switch main`, `git pull` y `terraform plan` local: tiene que decir `No changes`.

Desde tu máquina, solo `terraform plan`. La excepción es `bootstrap/`, que el CI no puede tocar.

Si un servicio nuevo necesita permisos que el CI no tiene, se agregan al rol de apply en
`bootstrap/ci_github.tf` y se aplican desde tu máquina, antes del PR del hub.

Si el CI no puede entrar (`Not authorized to perform sts:AssumeRoleWithWebIdentity`), comparar el
`sub` de los roles con `gh api repos/<dueño>/<repo>/actions/oidc/customization/sub`.

Si un apply se cortó y dejó el candado del state, desde esta carpeta:
`terraform force-unlock <ID del candado>` (el ID sale en el mensaje de error).

Los archivos tienen finales de línea LF (`.gitattributes`): el código es el mismo en tu máquina
y en el CI, que es el que arma y publica el paquete.

## Si se pierde el state de bootstrap

El bucket sigue existiendo; solo Terraform se olvida de él. Se recupera importándolo:

```powershell
cd infra/terraform/bootstrap
terraform init
terraform import aws_s3_bucket.state refhub-tfstate-<cuenta>
terraform import aws_s3_bucket_versioning.state refhub-tfstate-<cuenta>
terraform import aws_s3_bucket_server_side_encryption_configuration.state refhub-tfstate-<cuenta>
terraform import aws_s3_bucket_public_access_block.state refhub-tfstate-<cuenta>
terraform import aws_s3_bucket_lifecycle_configuration.state refhub-tfstate-<cuenta>
terraform import aws_iam_role.ci_plan refhub-github-plan
terraform import aws_iam_role.ci_apply refhub-github-apply
terraform import aws_iam_role_policy.ci_plan refhub-github-plan:candado-del-state
terraform import aws_iam_role_policy.ci_apply refhub-github-apply:aplicar-el-hub
terraform import aws_iam_role_policy_attachment.ci_plan_lectura refhub-github-plan/arn:aws:iam::aws:policy/ReadOnlyAccess
terraform import aws_iam_role_policy_attachment.ci_apply_lectura refhub-github-apply/arn:aws:iam::aws:policy/ReadOnlyAccess
terraform plan      # No changes
```

## Ingesta de GLEIF

La Lambda `refhub-gleif-ingest-dev` baja el último delta diario de GLEIF a
`landing/gleif/dt=<fecha de publicación>/` del bucket de datos. La máquina de estados
`refhub-gleif-ingest-dev` corre la Lambda (la reintenta si falla) y después los jobs de bronze y
silver, uno detrás del otro (ver "Bronze y silver"). El schedule `refhub-gleif-diario-dev`
(18:30 UTC) está creado pero **apagado**.

Correrla a mano (desde esta carpeta):

```powershell
$arn  = terraform output -raw gleif_state_machine_arn
$exec = aws stepfunctions start-execution --state-machine-arn $arn --query executionArn --output text
aws stepfunctions describe-execution --execution-arn $exec --query "[status,output]" --output text
```

Si dice `RUNNING`, repetir la última línea unos segundos después. Tiene que terminar en
`SUCCEEDED`, con `"status": "subido"` (archivo nuevo) o `"ya_existia"` (ya estaba), y con
`"bronze"` y `"silver"` en `"estado": "SUCCEEDED"`.

Verificar que el archivo está una sola vez:

```powershell
aws s3 ls s3://refhub-data-<cuenta>-dev/landing/gleif/ --recursive
```

Varios archivos en el mismo `dt=` no son duplicados: GLEIF publica varias veces por día
(`...-0800-...`, `...-1600-...`), cada uno con su nombre.

Prender la corrida diaria: en `orquestacion_gleif.tf` cambiar `state = "DISABLED"` por
`"ENABLED"` en una rama y abrir un PR: el plan tiene que mostrar un solo `~` sobre el schedule.

Si el schedule estuvo apagado o falló más de un día, faltan publicaciones: cada delta
`LastDay` trae solo 24 horas de cambios. Para rellenar el hueco (backfill) se puede bajar el
delta `LastWeek` o buscar las publicaciones viejas en
`https://goldencopy.gleif.org/api/v2/golden-copies/publishes`.

La misma Lambda baja las otras fuentes según el evento: `{"fuente": "gleif_isin_lei"}` (el
archivo ISIN↔LEI, una foto completa por día), `{"fuente": "gleif_rr"}` (las relaciones entre
empresas de GLEIF, nivel 2: el archivo completo de cada publicación, 23 MB, a
`landing/gleif_rr/`) o `{"fuente": "sec"}` (las empresas de la SEC; usa `alert_email` como
contacto, porque la SEC lo exige). Sin evento, baja el delta de GLEIF. Los archivos de ISIN↔LEI y
de relaciones se borran de landing a los 30 días: silver guarda la última foto. A mano:

```powershell
'{"fuente": "gleif_isin_lei"}' | Out-File -Encoding ascii evento.json
aws lambda invoke --function-name refhub-gleif-ingest-dev --payload fileb://evento.json salida.json
Get-Content salida.json
```

Logs de la Lambda (se borran a los 14 días):

```powershell
aws logs tail /aws/lambda/refhub-gleif-ingest-dev --since 1h
```

## Bronze y silver

Seis jobs de Glue 5.1 (logs en `/aws-glue/refhub-dev/output` y `/error`, 14 días):

- `refhub-gleif-full-dev`: baja el archivo completo de GLEIF a `landing/` (carga inicial, a mano).
- `refhub-gleif-bronze-dev`: carga en `refhub_bronze_dev.gleif_lei` los zips de `landing/` que
  falten.
- `refhub-gleif-silver-dev`: contrato, cuarentena y `MERGE` en `refhub_silver_dev.gleif_lei`.
- `refhub-gleif-isin-lei-dev`: el último archivo ISIN↔LEI de `landing/` reemplaza
  `refhub_silver_dev.gleif_isin_lei` (foto completa, sin bronze).
- `refhub-sec-dev`: el último archivo de la SEC de `landing/` reemplaza
  `refhub_silver_dev.sec_empresas` (foto completa, sin bronze).
- `refhub-gleif-relaciones-dev`: el último archivo de relaciones de GLEIF (nivel 2) de
  `landing/` reemplaza `refhub_silver_dev.gleif_relaciones` (foto completa, sin bronze). Todavía
  no está en Step Functions: se corre a mano.

Los tres últimos no hacen nada si el archivo más nuevo ya está en silver (salvo con full refresh,
más abajo).

Cada job se arma con el módulo `modules/glue_job` (su rol, su política y el job, con la
configuración que comparten todos). Un job nuevo es un bloque `module` con su nombre, su script,
sus parámetros y sus permisos propios.

Correr un job suelto:

```powershell
aws glue start-job-run --job-name refhub-gleif-bronze-dev
```

Consultas: Athena, workgroup `refhub-dev` (corta las consultas que leen más de 1 GB).

Recalcular una tabla de silver (full refresh): cuando cambia una regla (el contrato,
`normalize_name`, qué versión gana) o una columna nueva necesita valores en las filas viejas.
Los cuatro jobs de silver aceptan `--FULL_REFRESH true`: `refhub-gleif-silver-dev` procesa todos
los archivos de bronze y reemplaza `gleif_lei` y el registro de archivos procesados enteros;
los de foto completa vuelven a procesar el último archivo aunque ya esté en silver. Cada
reemplazo es un solo commit. Borrar filas del registro **no** sirve: el `MERGE` solo pisa una
fila con algo más nuevo, así que el mismo archivo otra vez no cambia nada.

```powershell
'{"--FULL_REFRESH": "true"}' | Out-File -Encoding ascii argumentos.json
aws glue start-job-run --job-name refhub-gleif-silver-dev --arguments file://argumentos.json
```

El JSON va en un archivo porque PowerShell 5.1 les saca las comillas dobles a los argumentos de
los programas externos: escrito en la línea, a la CLI le llega `{--FULL_REFRESH: true}` y falla.
Sin `--arguments`, el job corre en su modo normal (el default `false` está en Terraform).

## Cambios de esquema

El esquema de cada tabla es su DDL en `src/refhub/ddl/`: un ambiente nuevo nace con el esquema
final y no hay migraciones a mano. Una columna nueva (nullable) la agrega el job dueño de la
tabla al arrancar, en el mismo PR que el código que la escribe; si las filas viejas necesitan
valores, después se corre un full refresh. Renombrar, cambiar un tipo o borrar una columna va en
dos pasos (expand/contract).
Detalle: [ADR 0007](../../docs/adr/0007-evolucion-de-esquema-y-reprocesos.md).

## Versiones del código

La Lambda y los jobs usan el código de `artifacts/refhub/<versión>/` del bucket de datos: el
`.whl`, `refhub-lambda.zip` (el mismo `.whl` con otro nombre) y `glue/*.py`. Lo publica el CI al
mergear, antes del apply, y **no pisa una versión ya publicada**.

Versión nueva: cambiar `src/` o `glue/`, `uv version 0.3.1` y `refhub_version = "0.3.1"` en
`variables.tf`, en el mismo PR. Si cambiás el código sin subir la versión, el CI avisa "ya
existía y no se pisa" y en AWS sigue corriendo lo anterior.

Volver atrás: un PR con la versión anterior en `refhub_version`.

Requisito en GitHub (una vez, desde esta carpeta):

```powershell
gh variable set ARTIFACTS_BUCKET --body "$(terraform output -raw data_bucket)"
```

## Bajar todo

1. En esta carpeta: `terraform destroy`. Falla si el bucket de datos tiene archivos: es a
   propósito, para no perder datos por error. Vaciarlo antes solo si de verdad se quiere borrar.
2. El bucket del state tiene `prevent_destroy`: para borrarlo hay que sacar esa traba en
   `bootstrap/main.tf` a conciencia.
