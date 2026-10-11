# ADR 0005 · Cambios por pull request: plan en el PR, apply desde el CI

- Estado: aceptado
- Fecha: 2026-10-10

## Contexto

Hasta el hito 4A, la infraestructura se aplicaba con `terraform apply` desde una sola máquina,
con un usuario con permisos amplios. Así no queda registro de quién aplicó qué, el plan no lo
revisa nadie antes de tocar AWS y el resultado depende de lo que haya en esa carpeta. En un
equipo, los cambios entran por pull request y los aplica un proceso automático.

## Decisión

- **Todo cambio del hub entra por pull request.** El CI corre `terraform plan` en cada PR y lo
  publica como comentario (se actualiza en cada push). Al mergear a `main`, el CI corre
  `terraform apply`. Desde una máquina, solo `terraform plan` para iterar.
- **OIDC, sin claves guardadas.** GitHub Actions pide un token firmado y AWS lo cambia por
  credenciales que vencen en una hora. El proveedor OIDC de GitHub es un requisito de la cuenta:
  el hub lo lee, no lo crea.
- **Dos roles.**
  - `refhub-github-plan`: solo desde un `pull_request` del repo. Lectura (`ReadOnlyAccess`) más
    el candado del state. El código de un PR todavía no se revisó, así que no puede escribir.
  - `refhub-github-apply`: solo desde `main`. Crea y cambia recursos `refhub-*`.
  - Ninguno de los dos puede leer el contenido de los datos en S3 (solo el state y `artifacts/`).
- **Los roles viven en `bootstrap/`** y se aplican a mano. Si estuvieran en el hub, el CI se
  aplicaría a sí mismo: podría sacarse permisos (y quedar sin poder entrar) o sumárselos. El rol
  de apply además tiene un Deny explícito sobre `refhub-github-*`.
- **Finales de línea LF en todo el repo** (`.gitattributes`). Si no, el zip de la Lambda y la
  huella de los scripts de Glue dan distinto en Windows que en el runner Linux del CI.
- **Un apply a la vez** (`concurrency` en el workflow) y el candado del state (`use_lockfile`).

## Alternativas consideradas

- **Seguir aplicando desde la máquina:** más simple, pero sin revisión, sin registro y con
  permisos de administrador.
- **Claves de acceso guardadas como secretos de GitHub:** no vencen solas y sirven desde
  cualquier lado si se filtran.
- **Un solo rol para plan y apply:** el código de un PR sin revisar podría escribir en AWS.
- **Atlantis o HCP Terraform:** resuelven lo mismo, pero suman un servicio que mantener.

## Consecuencias

- Cada cambio deja un PR con su plan y una corrida del CI con su log.
- El punto débil es IAM: el rol de apply puede crear roles `refhub-*` con políticas propias y
  pasárselos a Lambda o Glue, lo que permitiría escalar privilegios desde un PR malicioso. La
  defensa es revisar el plan antes de mergear; la mejora sería un permissions boundary.
- Con el repo privado en el plan gratuito de GitHub no se puede obligar a que todo pase por PR
  (protección de rama): depende de la disciplina. Al pasar a público (hito 6) se puede activar.
- Si un servicio nuevo necesita permisos, primero se amplía el rol de apply en `bootstrap/`
  (desde la máquina) y después va el PR del hub.
