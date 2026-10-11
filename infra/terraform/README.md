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
4. **Crear el hub.**
   ```powershell
   cd infra/terraform
   terraform init -backend-config="backend.hcl"
   terraform plan      # 21 to add: bucket de datos (4) + budget + Lambda (4) + orquestación (6) + Glue (6)
   terraform apply     # solo la primera vez; después aplica el CI (ver abajo)
   ```
5. **Verificar.** `terraform plan` tiene que decir `No changes`.

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

Los archivos tienen finales de línea LF (`.gitattributes`). Si no, el zip de la Lambda y la
huella de los scripts de Glue darían distinto en tu máquina que en el CI.

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
`landing/gleif/dt=<fecha de publicación>/` del bucket de datos. La ejecuta la máquina de estados
`refhub-gleif-ingest-dev`, que la reintenta si falla. El schedule `refhub-gleif-diario-dev`
(18:30 UTC) está creado pero **apagado**.

Correrla a mano (desde esta carpeta):

```powershell
$arn  = terraform output -raw gleif_state_machine_arn
$exec = aws stepfunctions start-execution --state-machine-arn $arn --query executionArn --output text
aws stepfunctions describe-execution --execution-arn $exec --query "[status,output]" --output text
```

Si dice `RUNNING`, repetir la última línea unos segundos después. Tiene que terminar en
`SUCCEEDED`, con `"status": "subido"` (archivo nuevo) o `"ya_existia"` (ya estaba).

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

Si cambia el código de `src/`, `terraform plan` muestra un `~` sobre la Lambda: es el zip
nuevo. Es normal.

Logs de la Lambda (se borran a los 14 días):

```powershell
aws logs tail /aws/lambda/refhub-gleif-ingest-dev --since 1h
```

## Bajar todo

1. En esta carpeta: `terraform destroy`. Falla si el bucket de datos tiene archivos: es a
   propósito, para no perder datos por error. Vaciarlo antes solo si de verdad se quiere borrar.
2. El bucket del state tiene `prevent_destroy`: para borrarlo hay que sacar esa traba en
   `bootstrap/main.tf` a conciencia.
