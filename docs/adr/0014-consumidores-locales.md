# ADR 0014 · Dos consumidores locales de la golden copy

- Estado: aceptado
- Fecha: 2026-10-22

## Contexto

En un banco la golden copy no se usa sola: la consumen otros sistemas. Un buscador donde un
analista escribe el nombre de una contraparte como lo recuerda y encuentra todos sus códigos, y un
sistema de riesgo que suma la exposición por grupo económico con sus propias consultas. Mostrar
esos dos consumidores hace visible para qué sirve el hub y cómo se entrega lo que produce.

Los dos tienen una herramienta típica en la industria: un motor de búsqueda (Elasticsearch u
OpenSearch) y una base relacional de las que usan los sistemas de riesgo (Oracle es la más común
en bancos). Ninguno de los dos es parte del hub.

## Decisión

- **Corren en local, con Podman** (`local/compose.yaml`, que también sirve con `docker compose`),
  alimentados con CSV exportados de Athena con consultas de solo lectura. No en AWS:
  - **OpenSearch gestionado está prohibido en este proyecto** (ADR 0001): es un servicio que
    cobra por hora mientras está prendido y puede gastar el crédito en días. Incluso la opción
    Serverless tiene un mínimo de capacidad que cobra aunque no se use.
  - **Una base Oracle en RDS** cobra por hora y por licencia. Oracle Database Free es gratis y
    alcanza para mostrar las consultas.
  - Local cuesta cero, se prende y se apaga con un comando y no deja nada corriendo en la cuenta.
- **Los dos consumidores, y por qué estos:**
  - **OpenSearch como buscador de contrapartes.** La golden copy resuelve "estos códigos son la
    misma empresa"; el buscador resuelve "no sé el código, sé más o menos el nombre". La
    búsqueda difusa (distancia de edición sobre palabras analizadas) es justo lo que el hub
    decidió **no** hacer en el cruce (ADR 0008: un vínculo falso suma exposición a quien no es).
    En un buscador un falso positivo no hace daño, porque una persona mira el resultado y elige.
    Es OpenSearch, el fork de Elasticsearch 7.10 que mantiene la Linux Foundation, con licencia
    Apache 2.0; el Query DSL es casi el mismo.
  - **Oracle como sistema de riesgo que suma exposición por grupo.** Muestra el otro enfoque de
    jerarquías: recorrer el árbol de consolidación directa con `CONNECT BY` (la sintaxis propia de
    Oracle) o con `WITH` recursivo (SQL estándar), en lugar de usar la controlante final que
    publica GLEIF, como hace gold (ADR 0013). Las dos respuestas se comparan en
    `local/README.md`.
- **Un documento por empresa en OpenSearch**, con todas sus claves. Las reglas para juntar la
  golden copy con GLEIF están en `refhub.contrapartes` (con tests): la clave es el LEI; una
  empresa de la SEC sin LEI entra por su CIK; dos CIKs con el mismo LEI son un solo documento.
  **Alcance:** las 8.029 empresas de la golden copy y las empresas de EE. UU. de GLEIF con el
  registro `ISSUED` o `LAPSED` (unas 342 mil). Las de EE. UU. son las que un analista de un
  banco que trabaja con emisoras de la SEC va a buscar; todo GLEIF (3,46 millones) entra en el
  heap de 1 GB, pero no agrega nada al ejemplo y multiplica por diez la carga.
- **Mapping explícito y estricto** (`dynamic: strict`): un analizador para nombres (minúsculas,
  sin tildes y sin las formas legales, la misma lista que `refhub.names`), un campo `keyword` por
  esquema de código, y `identificadores`, que junta todos los códigos con `copy_to` y los compara
  en minúscula: buscar por LEI, ISIN, CIK o ticker es la misma consulta.
- **OpenSearch sin el plugin de seguridad, solo porque escucha en 127.0.0.1.** Sin el plugin no
  hay TLS ni usuarios: cualquiera que llegue al puerto lee y borra el índice. El trade-off se
  acepta porque el puerto se publica solo en la interfaz local (nada de la red llega) y los datos
  son públicos. Con el plugin habría que manejar certificados y una contraseña de admin para un
  ejemplo que no lo necesita. **Si alguna vez escucha en otra interfaz, el plugin va prendido.**
- **Oracle es un sistema consumidor, no parte del hub.** Recibe una copia; no escribe nada de
  vuelta ni es fuente de verdad. Por eso las cargas borran y recrean todo (es una copia de gold,
  no datos propios) y el esquema vive en `local/oracle/esquema.sql`, no en Terraform ni en dbt.
  La contraseña es de un contenedor local y se genera al levantarlo, en `local/.env` (ignorado
  por git).
- **La cartera es sintética** (ADR 0013): LEIs reales, montos y préstamos inventados. Las cifras
  de exposición que salen de Oracle tampoco son un hallazgo; sirven para comparar los dos
  enfoques de jerarquía.
- **Imágenes oficiales con versión fija:** `opensearchproject/opensearch:3.9.0` y
  `container-registry.oracle.com/database/free:23.26.3.0-lite` (Oracle AI Database 26ai Free; la
  variante lite es la base entera sin componentes opcionales, 0,9 GB comprimida contra 3,7 GB la
  completa). El registro de Oracle la sirve sin login ni licencia interactiva.

## Alternativas consideradas

- **OpenSearch Service o Serverless en AWS:** prohibido por costo (ADR 0001).
- **Elasticsearch en lugar de OpenSearch:** el Query DSL es casi igual, pero desde la 7.11 su
  licencia no es open source en todas las versiones, y en AWS el servicio es OpenSearch. Se
  elige el que se usaría si el buscador pasara a AWS algún día.
- **PostgreSQL en lugar de Oracle:** tiene `WITH RECURSIVE` (estándar) pero no `CONNECT BY`, que
  es lo que se encuentra en los sistemas de riesgo heredados de los bancos. Las consultas con
  `WITH` recursivo de este ejemplo corren casi iguales en PostgreSQL.
- **Recorrer el árbol en gold, con Athena:** Athena (Trino) tiene `WITH RECURSIVE` con un límite
  de profundidad, pero el ADR 0013 ya decidió usar la controlante publicada. Acá se muestra el
  recorrido como lo haría un consumidor que solo recibe las relaciones directas.
- **El plugin de seguridad prendido con la configuración de demo:** trae certificados de ejemplo
  y una contraseña conocida; da la apariencia de seguridad sin serlo.

## Consecuencias

- Hace falta Podman (o Docker) y 3,5 GB de imágenes ya descomprimidas (1,7 GB OpenSearch y
  1,82 GB Oracle). Medido el 22-oct-2026 con los datos cargados y las consultas corridas:
  1,59 GB de RAM OpenSearch y 2,29 GB Oracle; apagados, nada.
- Los datos locales son una foto: para actualizarlos se vuelve a exportar y a cargar.
- Lo que muestra el buscador no cambia el cruce de la golden copy: si la búsqueda difusa
  encuentra algo que el cruce no, es una pista para el gold set (ADR 0008), no un vínculo nuevo.
