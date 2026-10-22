-- Cuarentena de las relaciones de GLEIF: las filas que no cumplen el contrato
-- (refhub.contract.relationship_problem), tal cual llegaron y con el motivo. Una partición por
-- archivo: reprocesarlo la reemplaza.
CREATE TABLE IF NOT EXISTS {db}.gleif_relaciones_cuarentena (
  child_lei           string             COMMENT 'Tal cual en el archivo',
  parent_lei          string             COMMENT 'Tal cual en el archivo',
  relationship_type   string             COMMENT 'Tal cual en el archivo',
  relationship_status string             COMMENT 'Tal cual en el archivo',
  relationship_start  string             COMMENT 'Tal cual en el archivo (texto)',
  relationship_end    string             COMMENT 'Tal cual en el archivo (texto)',
  accounting_standard string             COMMENT 'Tal cual en el archivo',
  registration_status string             COMMENT 'Tal cual en el archivo',
  validation_sources  string             COMMENT 'Tal cual en el archivo',
  last_update         string             COMMENT 'Tal cual en el archivo (texto)',
  _archivo            string    NOT NULL COMMENT 'Linaje: archivo de GLEIF del que salió la fila',
  _fecha_publicacion  date      NOT NULL COMMENT 'Linaje: fecha en que GLEIF publicó ese archivo',
  motivo              string    NOT NULL COMMENT 'Primera regla del contrato que la fila no cumplió',
  _procesado_en       timestamp NOT NULL COMMENT 'Cuándo la mandó a cuarentena el job (UTC)'
)
USING iceberg
PARTITIONED BY (_archivo)
TBLPROPERTIES ('format-version' = '2')
