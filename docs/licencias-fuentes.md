# Licencias de las fuentes

Lo que dice la licencia de cada fuente del hub, verificado en la web oficial. Es la base de las
políticas ODRL de `src/refhub/catalogo/politicas.ttl`. Resumen en mis palabras: no reemplaza a
los términos, que pueden cambiar; ante una duda real, manda el texto original.

Consultado el **2026-10-21**.

## GLEIF: datos LEI (golden copy y deltas)

- **URL:** https://www.gleif.org/en/meta/lei-data-terms-of-use
- **Qué dice:** los datos LEI que GLEIF pone a disposición se publican bajo la licencia
  **CC0** (dominio público): se pueden usar para cualquier fin, comercial incluido, y
  redistribuir, sin obligación de citar. Las condiciones aparte son sobre GLEIF y no sobre el
  dato: no reclamar propiedad intelectual sobre los datos, no dar a entender que GLEIF respalda
  un producto y pedir permiso para usar su marca o logo.
- **Cita:** "provided under the CC0 licence."
- **En ODRL:** `pol:gleif_cc0`, un permiso de cualquier uso, sin obligaciones.

## GLEIF y ANNA: relación ISIN↔LEI

- **URLs:** https://www.gleif.org/en/lei-data/lei-mapping/download-isin-to-lei-relationship-files
  y el anuncio de ANNA y GLEIF sobre la iniciativa de mapeo
  (https://mondovisione.com/media-and-resources/news/anna-and-gleif-isin-to-lei-mapping-service-jurisdiction-expansion-certified-is-20201216/).
- **Qué dice:** ANNA (las agencias de numeración que asignan los ISIN) arma la relación y GLEIF
  la publica todos los días. GLEIF y ANNA la describen como datos abiertos ("open source"),
  gratis y sin restricciones. **No se encontró un texto de licencia con nombre** para estos
  archivos (la página de descarga no lo dice), así que se modela lo que declaran: cualquier uso.
- **Cita (página de GLEIF):** "publicly available on the GLEIF website".
- **En ODRL:** `pol:isin_lei_abierto`, un permiso de cualquier uso. Si aparece una licencia
  formal, se ajusta la política.

## SEC EDGAR: `company_tickers_exchange.json`

- **URL:** https://www.sec.gov/privacy (sección sobre la difusión de la información del sitio).
- **Qué dice:** lo que está en sec.gov es información pública: se puede copiar y redistribuir
  sin pedir permiso, y la SEC **pide que se la cite como fuente**. No se pueden usar el sello ni
  los logos de la SEC, y "SEC" y "EDGAR" son marcas registradas. Aparte, el acceso automático
  exige un User-Agent con contacto y no más de 10 pedidos por segundo (eso es del acceso, no de
  la licencia: ya lo cumple `refhub.sources.sec`).
- **Cita:** "considered public information".
- **En ODRL:** `pol:sec_publica_con_cita`, un permiso de cualquier uso con la obligación
  (`odrl:duty`) de citar la fuente. La SEC lo pide y no lo exige; para un banco lo prudente es
  cumplirlo siempre, por eso va como obligación.

## OpenFIGI / FIGI

- **URLs:** https://www.openfigi.com/docs/terms-of-service y https://www.openfigi.com/about/figi
- **Qué dice:** los identificadores FIGI están dedicados al **dominio público**: se pueden
  reproducir, distribuir, modificar y usar para cualquier fin, comercial incluido, sin pedir
  atribución. Lo único restringido son las marcas "FIGI" y "OPENFIGI" (no dar a entender un
  respaldo). La página "about" describe además la licencia del estándar como de estilo MIT.
- **Cita:** "FIGI Identifiers may be freely reproduced, distributed, transmitted, used".
- **En ODRL:** `pol:figi_dominio_publico`, un permiso de cualquier uso, sin obligaciones.

## Proveedor de precios FICTICIO

No es una fuente real ni se ingiere: está para mostrar una licencia de market data, que es el
caso que las fuentes abiertas no cubren (ADR 0001: sin nombres de proveedores reales). Su
política (`pol:feed_precios_ficticio`) sigue lo típico de esas licencias: display interno
permitido solo para la aplicación suscripta, uso non-display prohibido, datos derivados solo
para uso interno y redistribución prohibida.
