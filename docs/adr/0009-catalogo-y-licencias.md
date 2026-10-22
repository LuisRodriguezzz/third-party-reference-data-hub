# ADR 0009 · Catálogo en DCAT y licencias en ODRL, evaluadas con rdflib

- Estado: aceptado
- Fecha: 2026-10-21

## Contexto

El banco compra y usa datos de terceros con licencias que limitan para qué se pueden usar
(ADR 0001). La pregunta que tiene que poder responder es: **¿esta aplicación puede usar este
dataset para este propósito? ¿Con qué regla se decidió y qué obligaciones tiene?** Y la pregunta
tiene que valer también para lo que el hub produce: la golden copy no es una fuente, pero está
hecha con datos de la SEC, de GLEIF y de OpenFIGI, y arrastra lo que dicen sus licencias.

Hace falta, entonces: un inventario de datasets con su linaje, las licencias escritas de forma
que una máquina las lea, y un evaluador con reglas claras para los conflictos.

## Decisión

- **Catálogo en DCAT 3 y licencias en ODRL 2.2, en RDF (Turtle).** Son los estándares del W3C
  para exactamente esto: DCAT describe datasets (publicador, licencia, periodicidad) y ODRL
  describe políticas (permisos, prohibiciones, obligaciones, restricciones por propósito). El
  linaje va con PROV-O (`prov:wasDerivedFrom`), la jerarquía de propósitos con SKOS
  (`skos:broader`) y los propósitos de cada aplicación con DPV (`dpv:hasPurpose`). Criterio: el
  esquema se declara en el formato nativo de su estándar (como el DDL para Iceberg, ADR 0006); un
  catálogo DCAT lo lee cualquier herramienta de catálogo (CKAN, data.europa.eu, los portales
  de datos abiertos) sin conocer el hub.
  - `src/refhub/catalogo/catalogo.ttl`: el catálogo, las fuentes y los productos del hub.
  - `politicas.ttl`: una política ODRL por licencia real, verificada en la web
    (`docs/licencias-fuentes.md`), más la del proveedor ficticio.
  - `aplicaciones.ttl`: las aplicaciones (sintéticas) y los propósitos.
  - `consultas/*.rq`: preguntas de gobierno de datos en SPARQL (qué no se puede redistribuir,
    de qué fuentes sale la golden copy).
  Los `.ttl` y los `.rq` viajan en el `.whl`, como los DDL: la API los va a leer desde el paquete.
- **rdflib en el mismo proceso, sin servidor.** Carga el grafo en memoria y corre SPARQL. El
  catálogo tiene cientos de triples, no millones: no hace falta una base de grafos. Corre en
  pytest y en el CI igual que en AWS.
- **Semántica del evaluador** (`refhub.licencias.evaluar`):
  - **La prohibición gana sobre el permiso (deny-overrides).** Criterio: el algoritmo
    deny-overrides de XACML y la estrategia `odrl:prohibit` de ODRL (`odrl:conflict`). Lo que un
    contrato prohíbe pesa más que lo que otra cláusula parece permitir.
  - **Sin permiso explícito, no (default deny).** Una licencia enumera lo que concede; lo que no
    dice no está concedido. Es el principio de mínimo privilegio aplicado a los datos.
  - **Los propósitos respetan la jerarquía.** Un permiso para `uso_interno` alcanza a
    `riesgo_credito`; una prohibición para `distribucion_externa` alcanza a la publicación
    externa.
  - **Un derivado hereda las restricciones de sus fuentes.** Se evalúa el dataset y todo su
    linaje hacia arriba y gana lo más restrictivo: cada nivel tiene que permitir y ninguno puede
    prohibir. Usar un derivado es ejercer `odrl:derive` sobre la fuente, así que en la fuente
    alcanza un permiso para derivar (o para cualquier uso); las prohibiciones de la fuente
    alcanzan siempre. Las obligaciones se juntan de todo el linaje: si la golden copy usa datos
    de la SEC, hay que citar a la SEC.
  - La respuesta dice la regla (su IRI), el dataset donde se decidió y las obligaciones. Si se
    niega por falta de permiso, no hay regla que citar y el motivo es `sin_permiso`.
- **Un proveedor ficticio, declarado como tal.** Las fuentes reales son abiertas y no muestran
  el caso difícil. El feed de precios ficticio (y su derivado) lleva una licencia al estilo de
  market data: display interno solo para la aplicación suscripta, non-display prohibido,
  derivados solo internos, redistribución prohibida. Está marcado como FICTICIO en el propio
  archivo y no usa nombres de proveedores reales (ADR 0001).
- **La API del hito 8 sirve la tabla compilada.** `compilar` evalúa de antemano todas las
  combinaciones aplicación × dataset × propósito; la API responde buscando una fila, sin evaluar
  el grafo en cada pedido. Es el patrón de compilar políticas a una tabla de decisiones: la
  respuesta es rápida y predecible, y la tabla se puede revisar entera antes de publicarla.
  Cuando cambia una política, se recompila.

## Alternativas consideradas

- **Una tabla de licencias en SQL** (dataset, propósito, permitido): sirve para la respuesta,
  pero es un esquema propio que nadie más entiende, sin obligaciones ni jerarquía de propósitos
  ni linaje, y no se puede intercambiar con un proveedor ni con un catálogo externo. Igual
  termina existiendo: es la tabla compilada, que sale de las políticas y no se escribe a mano.
- **Fuseki o GraphDB** (un servidor SPARQL): agregan un servicio que levantar, mantener y pagar
  (Java, un contenedor o una instancia) para un grafo que entra en memoria. En CI habría que
  levantarlo para cada test.
- **Amazon Neptune:** descartado por costo y por el plan de la cuenta; tiene su propio ADR.
- **OPA / Rego:** un buen motor de políticas, pero las políticas quedarían en un lenguaje propio
  de OPA en vez del estándar de licencias de datos, y el catálogo y el linaje tendrían que vivir
  en otro lado. ODRL es lo que publican (o van a publicar) los proveedores y los espacios de
  datos; con OPA habría que traducirlo.
- **Un razonador OWL o las reglas de un motor ODRL completo:** el subconjunto de ODRL que se usa
  (permisos, prohibiciones, deberes, propósito, asignatario) se evalúa en pocas líneas. Un motor
  completo se justifica cuando aparezcan restricciones de fechas, cantidades o territorio.

## Consecuencias

- Los IRIs usan `refhub.example.org`, un dominio reservado para ejemplos: no chocan con nada
  real. Si el catálogo se publicara, se cambia la base.
- rdflib pasa a ser dependencia del paquete. Los jobs de Glue la instalan con el `.whl` (no la
  usan); la Lambda de la API va a tener que empaquetarla.
- El evaluador solo entiende restricciones de propósito y asignatario por regla. Una licencia
  con fechas, territorio o cantidad de usuarios necesita sumar ese operando al evaluador.
- `silver.openfigi_tickers` está en el catálogo antes de existir en el pipeline (llega con el
  paso 5D), porque la golden copy depende de ella.
- La licencia de la relación ISIN↔LEI no tiene un texto con nombre: se modeló lo que declaran
  GLEIF y ANNA (abierta, sin restricciones). Si se publica una licencia formal, se ajusta la
  política y se recompila.
- Si cambia una licencia de verdad, hay que actualizar `docs/licencias-fuentes.md` y la política
  en el mismo PR: el documento es la evidencia de por qué la política dice lo que dice.
