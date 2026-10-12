-- Silver de ISIN↔LEI: qué títulos (ISIN) emitió cada empresa (LEI), según la última foto de
-- GLEIF y ANNA. Se reemplaza entera con cada archivo nuevo: lo que no vino, ya no existe.
-- {db} lo reemplaza el job por la base de silver (por ejemplo glue_catalog.refhub_silver_dev).
CREATE TABLE IF NOT EXISTS {db}.gleif_isin_lei (
  isin               string NOT NULL COMMENT 'ISIN (ISO 6166) con dígito verificador válido. Una fila por ISIN',
  lei                string NOT NULL COMMENT 'LEI (ISO 17442) de la empresa que emitió el título',
  _archivo           string NOT NULL COMMENT 'Linaje: archivo de GLEIF del que salió la fila',
  _fecha_publicacion date   NOT NULL COMMENT 'Linaje: fecha en que GLEIF publicó ese archivo'
)
USING iceberg
TBLPROPERTIES ('format-version' = '2')
