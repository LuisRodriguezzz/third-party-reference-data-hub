# Infraestructura del hub (runbook)

Dos proyectos de Terraform:

- `bootstrap/`: crea solo el bucket donde vive el state. Se aplica una vez.
- esta carpeta: el hub (bucket de datos y budget). Guarda su state en el bucket de `bootstrap/`.

## Requisitos

- Terraform >= 1.10 y AWS CLI con credenciales configuradas (`aws sts get-caller-identity` responde).
- Región `us-east-1`.

## Levantar todo desde cero

1. **Bucket del state (una sola vez).**
   ```powershell
   cd infra/terraform/bootstrap
   terraform init
   terraform plan      # 5 to add
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
   terraform plan      # 15 to add: bucket de datos (4) + budget + Lambda (4) + orquestación (6)
   terraform apply
   ```
5. **Verificar.** `terraform plan` tiene que decir `No changes`.

`backend.hcl`, `terraform.tfvars` y los `terraform.tfstate` no se suben a git.

## Antes de cada apply

Leer el resumen del plan. Si aparece `-/+` o `must be replaced` sobre un bucket, no aplicar:
buscar la línea marcada con `# forces replacement`.

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
`"ENABLED"`. `terraform plan` tiene que mostrar un solo `~` sobre el schedule; después `apply`.

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
