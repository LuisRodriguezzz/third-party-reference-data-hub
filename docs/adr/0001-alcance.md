# ADR 0001 · Alcance del proyecto

- Estado: aceptado
- Fecha: 2026-09-27

## Contexto

En un banco, la misma empresa aparece con identificadores distintos según el área
(LEI, ISIN, CIK, FIGI). Los datos de proveedores externos llegan con licencias que
limitan cómo se pueden usar, y muchas veces no hay un inventario claro de qué datos
se compran y quién los usa. Sin resolver esto no se puede, por ejemplo, sumar la
exposición total a un grupo económico ni demostrar que un dato se usa dentro de lo
que permite su contrato.

## Decisión

Construir un hub de datos de referencia de terceros, a escala chica y con fuentes
públicas reales:

- Golden copy de empresas e instrumentos a partir de GLEIF, OpenFIGI y SEC EDGAR.
- Catálogo de datasets (DCAT) y licencias legibles por máquina (ODRL).
- Una API que responde si una aplicación puede usar un dato, y con qué regla lo decidió.
- Pipeline medallion en AWS (S3, Lambda, Glue) con la infraestructura en Terraform.

Queda afuera:

- Datos pagos y contratos con nombres reales de proveedores.
- Kubernetes y un segundo modelo de grafo (Gremlin).
- Servicios que pueden gastar el crédito en horas: NAT Gateway, OpenSearch
  gestionado, Neptune Serverless.
- Neptune en cualquiera de sus formas: el grafo RDF se consulta con SPARQL en el mismo
  proceso (ADR 0010).

## Alternativas consideradas

- **Detección de cuentas mula (AML):** los datos serían casi todos sintéticos y la
  métrica se compararía contra reglas escritas por mí mismo.
- **RAG sobre normativa bancaria:** es un proyecto muy repetido y está poco ligado
  a la ingeniería de datos.
- **Modelo de pérdida esperada IFRS 9:** es más ciencia de datos que data engineering.

## Consecuencias

- A favor: datos reales y gratuitos, problemas documentados de los equipos de
  Reference Data.
- En contra: depende de APIs externas con límites (OpenFIGI 25 req/min, SEC 10 req/s),
  la cartera de préstamos y las aplicaciones que piden datos son sintéticas (y se
  declaran así), y el presupuesto está atado al crédito del plan Free de AWS.
