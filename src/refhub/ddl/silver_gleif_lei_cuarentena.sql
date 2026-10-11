-- Cuarentena: las filas que no cumplieron el contrato, tal cual venían de bronze (como texto,
-- y pueden faltar datos: por algo fallaron), con el motivo. Siguen intactas en bronze.
-- Particionada por archivo: reprocesar un archivo reemplaza sus filas, no las duplica.
CREATE TABLE IF NOT EXISTS {db}.gleif_lei_cuarentena (
  lei                 string             COMMENT 'Tal cual en bronze',
  legal_name          string             COMMENT 'Tal cual en bronze',
  country             string             COMMENT 'Tal cual en bronze',
  entity_status       string             COMMENT 'Tal cual en bronze',
  registration_status string             COMMENT 'Tal cual en bronze',
  last_update         string             COMMENT 'Tal cual en bronze (texto)',
  next_renewal        string             COMMENT 'Tal cual en bronze (texto)',
  _archivo            string    NOT NULL COMMENT 'Linaje: archivo de GLEIF del que salió la fila',
  _fecha_publicacion  date      NOT NULL COMMENT 'Linaje: fecha en que GLEIF publicó ese archivo',
  motivo              string    NOT NULL COMMENT 'Primera regla del contrato que la fila no cumplió',
  _procesado_en       timestamp NOT NULL COMMENT 'Cuándo la mandó a cuarentena el job de silver (UTC)'
)
USING iceberg
PARTITIONED BY (_archivo)
TBLPROPERTIES ('format-version' = '2')
