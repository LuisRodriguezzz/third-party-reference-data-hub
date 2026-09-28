# ADR 0003 · State remoto en S3, lock con archivo y un solo ambiente

- Estado: aceptado
- Fecha: 2026-09-28

## Contexto

Terraform guarda en el state la lista de todo lo que creó. Si el state vive en un solo disco,
se puede perder, y el CI no puede usarlo. Si dos procesos aplican a la vez sobre el mismo state,
lo pueden dejar inconsistente. Además, el bucket donde se guardaría el state también lo tiene
que crear Terraform.

## Decisión

- **State remoto en S3**, en un bucket con versionado, cifrado AES256, acceso público bloqueado
  y `prevent_destroy`. Las versiones viejas del state se borran a los 30 días.
- **Bootstrap separado:** un proyecto chico (`infra/terraform/bootstrap/`) crea solo ese bucket,
  con state local, y se aplica una vez. Así se resuelve el problema de quién crea el lugar del
  state.
- **Lock con archivo en S3** (`use_lockfile = true`, Terraform >= 1.10): mientras un proceso
  aplica, deja un archivo candado en el bucket y otro proceso espera.
- **Configuración parcial del backend:** `bucket` y `key` van en `backend.hcl`, fuera de git,
  porque dependen de la cuenta y del ambiente. En el repo queda `backend.hcl.example`.
- **Un solo ambiente (`dev`), preparado para más:** la variable `environment` arma los nombres
  y los tags, y cada ambiente tendría su propio `backend.hcl` con su `key`.

## Alternativas consideradas

- **State local:** se pierde si se rompe la máquina y el CI no lo ve.
- **Lock con una tabla de DynamoDB:** era la forma clásica. Suma un recurso más y quedó
  deprecada desde que el backend S3 soporta el lock con archivo.
- **HCP Terraform:** resuelve state y lock, pero el state quedaría fuera de la cuenta de AWS.
- **Un ambiente `prod` real:** duplica recursos y costo, y no demuestra nada nuevo mientras no
  haya un flujo de promoción de dev a prod.
- **Workspaces de Terraform para separar ambientes:** comparten backend y credenciales; el
  aislamiento es menor que con un backend por ambiente.

## Consecuencias

- El state de `bootstrap/` queda en un solo disco. Si se pierde, el bucket se recupera con
  `terraform import` (pasos en `infra/terraform/README.md`).
- Cada `terraform init` necesita `-backend-config="backend.hcl"`.
- En un banco, cada ambiente iría además en su propia cuenta de AWS (AWS Organizations), para
  que un error en dev no pueda tocar prod. Acá queda fuera de alcance.
- Costo: centavos por mes (dos buckets casi vacíos; el budget no se cobra).
