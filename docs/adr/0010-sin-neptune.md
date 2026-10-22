# ADR 0010 · Sin Neptune: el grafo se consulta en el mismo proceso

- Estado: aceptado
- Fecha: 2026-10-21

## Contexto

El plan original tenía una "ventana Neptune" (hito 10): cargar en Amazon Neptune el grafo RDF
del catálogo (DCAT) y de las licencias (ODRL), grabar las consultas en video y destruir el
cluster con `terraform destroy`. La idea era mostrar una base de grafos administrada, pero la
cuenta del hub está en el **plan Free** de la nueva experiencia de cuentas de AWS, y eso cambia
la cuenta.

Lo que dice la documentación oficial de AWS (consultada el 2026-10-21):

- **Neptune no está en el plan Free.** En la lista de servicios de la nueva experiencia, Amazon
  Neptune aparece entre los que se habilitan solo con el **Paid Plan**, no entre los del Free
  Tier.
  <https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html>
- **El plan Free no cobra nunca**: la cuenta se cierra cuando se acaba el crédito o a los seis
  meses, y no incluye servicios que podrían gastar el crédito rápido.
  <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html>
- **El Paid Plan sí cobra**: lo que excede el saldo de crédito, o lo que se usa en servicios
  donde el crédito no aplica, se cobra a precio normal (a la tarjeta). La cuenta ya no se
  cierra al acabarse el crédito: sigue funcionando y facturando.
  <https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html>
- **Existe un free trial de Neptune Database, pero es del Paid Plan:** 30 días desde que se crea
  el primer cluster, para quien es nuevo en Neptune, con 750 horas de una instancia
  `db.t3.medium` o `db.t4g.medium`, 10 millones de operaciones de I/O, 1 GB de almacenamiento y
  1 GB de backup. Si se pasa de eso o vence el trial, el cluster sigue corriendo y se cobra a
  precio on-demand. La página de precios no describe trial para Neptune Analytics ni para
  Neptune Serverless.
  <https://aws.amazon.com/neptune/pricing/> · <https://aws.amazon.com/free/database/>

El grafo del hub es chico: unas pocas fuentes descritas en DCAT, sus licencias en ODRL y las
aplicaciones que piden datos. Son miles de triples, no millones. El ADR 0009 ya decidió que se
consulta con SPARQL usando rdflib, dentro del mismo proceso (en pytest, en el CI y en la API de
permisos).

## Decisión

**No se usa Neptune.** El hito 10 sale del plan. El grafo RDF del catálogo y de las licencias
se guarda en archivos Turtle en el repo y se consulta con SPARQL en el mismo proceso, con
rdflib (ADR 0009).

Criterio: **una base de grafos administrada se justifica por volumen, concurrencia o cantidad
de consumidores, no por el modelo de datos.** Que los datos sean un grafo no obliga a tener un
servidor de grafos: un grafo de miles de triples entra en memoria y se carga en milisegundos.
Neptune (o cualquier triplestore con servidor) empieza a convenir cuando:

- el grafo tiene **millones de triples** o más y no entra cómodo en la memoria de un proceso;
- hay **muchas consultas concurrentes** (por ejemplo, una API con tráfico real) y hace falta
  un servidor que las atienda sin recargar el grafo cada vez;
- **varios equipos o aplicaciones** consultan y actualizan el mismo grafo, y necesitan una sola
  copia compartida, con transacciones, backups y control de acceso.

Ninguna de las tres se da en el hub. Y del otro lado está el costo: pasar al Paid Plan deja
la cuenta expuesta a cobros en la tarjeta por cualquier recurso que quede prendido, no solo por
Neptune. Es un riesgo de factura a cambio de nada que el proyecto necesite.

## Alternativas consideradas

- **Neptune provisionado dentro de la ventana del free trial:** pasar al Paid Plan, crear un
  cluster `db.t4g.medium`, grabar las consultas y destruirlo antes de los 30 días. Técnicamente
  entra en el trial, pero desde que la cuenta está en el Paid Plan cualquier recurso olvidado
  (de Neptune o de otro servicio) que exceda el crédito se cobra a la tarjeta. Y lo que se mostraría
  (SPARQL sobre un grafo chico) es lo mismo que ya se muestra con rdflib.
- **Neptune Serverless y Neptune Analytics:** prohibidos en el proyecto (CLAUDE.md, ADR 0001):
  pueden gastar el crédito en horas y no tienen free trial descrito en la página de precios.
- **Fuseki o GraphDB en local:** un triplestore con servidor HTTP y SPARQL, sin costo de AWS.
  Era el plan anterior del hito 7. Exige instalar Java (o un contenedor) y levantar un servidor
  para un grafo que entra en memoria; tampoco corre en pytest ni en el CI sin más
  infraestructura. Conviene si el grafo crece o si varios procesos lo tienen que consultar a la
  vez, y es el paso natural antes de una base administrada.

## Consecuencias

- El hito 10 desaparece del plan. La guía y la hoja de ruta se actualizan.
- La cuenta sigue en el plan Free: el hub no puede generar cobros en la tarjeta.
- Las consultas SPARQL corren en los tests y en el CI, con el mismo código que usa la API de
  permisos (ADR 0009).
- Lo que se pierde es la experiencia práctica con Neptune (carga masiva, endpoints, IAM de
  Neptune). Se compensa contando el criterio: cuándo un grafo necesita un servidor y cuándo no.
- Si el grafo creciera a millones de triples o la API tuviera tráfico concurrente real, este
  ADR se revisa: primero un triplestore local (Fuseki o GraphDB) y después, con presupuesto, uno
  administrado.
