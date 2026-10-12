-- Cuarentena de ISIN↔LEI: las filas que no cumplen el contrato (refhub.contract.isin_lei_problem),
-- tal cual llegaron y con el motivo. Una partición por archivo: reprocesarlo la reemplaza.
CREATE TABLE IF NOT EXISTS {db}.gleif_isin_lei_cuarentena (
  isin               string             COMMENT 'Tal cual en el archivo',
  lei                string             COMMENT 'Tal cual en el archivo',
  _archivo           string    NOT NULL COMMENT 'Linaje: archivo de GLEIF del que salió la fila',
  _fecha_publicacion date      NOT NULL COMMENT 'Linaje: fecha en que GLEIF publicó ese archivo',
  motivo             string    NOT NULL COMMENT 'Primera regla del contrato que la fila no cumplió',
  _procesado_en      timestamp NOT NULL COMMENT 'Cuándo la mandó a cuarentena el job (UTC)'
)
USING iceberg
PARTITIONED BY (_archivo)
TBLPROPERTIES ('format-version' = '2')
