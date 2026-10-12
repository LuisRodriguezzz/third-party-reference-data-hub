# Reglas para trabajar en este repo

Hub de datos de referencia de terceros (paquete `refhub`): ingesta de GLEIF a AWS, capas
landing → bronze → silver en Iceberg, infraestructura con Terraform y despliegue por PR.

## Antes de empezar

- El estado del proyecto, las decisiones y el próximo paso están en
  `../portfolio-banca/hub-guia/PROGRESO.md`. La guía por hitos está en `guia.html`, en la misma
  carpeta. Leer PROGRESO.md primero.
- Las decisiones de diseño ya tomadas están en `docs/adr/`. No se rediscuten sin un motivo nuevo.

## Cómo se trabaja

- Claude escribe el código y explica cada decisión en simple, para que el dueño del proyecto
  entienda y pueda defender lo que se hizo. Explicar el porqué, no solo el qué.
- Español rioplatense, con voseo, en las explicaciones, los comentarios y los docs.
- Cada cambio va por una rama y un pull request. El CI corre `terraform plan` en el PR y lo
  deja como comentario; al mergear a `main`, el CI aplica. Nadie corre `terraform apply` del hub
  desde su máquina. La excepción es `infra/terraform/bootstrap/`, que se aplica a mano.
- Antes de mergear un PR que cambia infraestructura en AWS: mostrar el plan y pedir un OK.

## Cómo se escribe el código

**Simple, legible por humanos, mantenible y sin sobreingeniería.** En concreto:

- **Nada de mini-frameworks propios.** Si una herramienta estándar ya lo resuelve (Iceberg hace
  cumplir el esquema, Terraform maneja la infraestructura), se usa esa.
- **Separar cuando aparece el tercer caso, no antes.** Dos jobs parecidos se dejan duplicados;
  con el tercero se evalúa un módulo o un motor genérico.
- **Cada decisión con un criterio explícito y estándar de la industria**, escrito en un ADR si
  es de diseño. Ejemplo: el esquema de una tabla se declara en el formato nativo de la
  herramienta que la crea (Spark/Iceberg → DDL en SQL; dbt → el YAML de dbt; un acuerdo con
  otro equipo → ODCS).
- **Tests solo de reglas de negocio** (el dígito verificador del LEI, las reglas del contrato,
  qué versión gana, qué archivos faltan). Nada de tests que repitan lo que dice el código.
- La lógica va en funciones puras dentro de `src/refhub/` (se prueban con pytest). Los scripts
  de `glue/` y el `handler` de la Lambda son enchufes finos que leen parámetros y llaman a esa
  lógica.
- Comentarios que explican el porqué, en español. Nombres claros.
- Antes de commitear: `uv run ruff format .`, `uv run ruff check .`, `uv run pytest`, y en
  `infra/terraform`: `terraform fmt -recursive` y `terraform plan`.

## AWS y costos

- Por defecto, solo lectura. Lo que crea recursos pasa por un PR (o por `bootstrap/`).
- Prohibido en este proyecto: NAT Gateway, Interface Endpoints, Neptune Serverless, Neptune
  Analytics, OpenSearch gestionado, EKS y claves KMS propias. Nada de sesiones interactivas de
  Glue ni crawlers.
- Logs siempre con retención. El schedule diario queda apagado salvo decisión explícita.

## Lo que no se hace

- No publicar páginas como Artifacts de claude.ai: una página visual va como HTML local en
  `../portfolio-banca/hub-guia/`.
- No referenciar otros proyectos del autor en el código, los docs o la guía de este repo.
- No instalar nada en el sistema ni disparar avisos del firewall de Windows (por ejemplo, Java
  para probar Spark) sin avisar antes.
- No poner tiempos ni fechas límite en los planes.
