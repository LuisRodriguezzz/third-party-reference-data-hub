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
archivo ISIN↔LEI, una foto completa por día) o `{"fuente": "sec"}` (las empresas de la SEC; usa
`alert_email` como contacto, porque la SEC lo exige). Sin evento, baja el delta de GLEIF. A mano:

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

Tres jobs de Glue 5.1 (logs en `/aws-glue/refhub-dev/output` y `/error`, 14 días):

- `refhub-gleif-full-dev`: baja el archivo completo de GLEIF a `landing/` (carga inicial, a mano).
- `refhub-gleif-bronze-dev`: carga en `refhub_bronze_dev.gleif_lei` los zips de `landing/` que
  falten.
- `refhub-gleif-silver-dev`: contrato, cuarentena y `MERGE` en `refhub_silver_dev`.

Correr un job suelto:

```powershell
aws glue start-job-run --job-name refhub-gleif-bronze-dev
```

Consultas: Athena, workgroup `refhub-dev` (corta las consultas que leen más de 1 GB).

Reprocesar un archivo en silver (por ejemplo, después de cambiar una regla): borrar su fila de
`refhub_silver_dev.gleif_archivos_procesados` en Athena y correr el job de silver. Lo vuelve a
procesar entero sin duplicar.

## Versiones del código

La Lambda y los tres jobs usan el código de `artifacts/refhub/<versión>/` del bucket de datos: el
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
