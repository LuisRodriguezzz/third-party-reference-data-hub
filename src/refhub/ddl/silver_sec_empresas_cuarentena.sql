-- Cuarentena de la SEC: las filas que no cumplen el contrato (refhub.contract.sec_problem), tal
-- cual llegaron y con el motivo. Una partición por archivo: reprocesarlo la reemplaza.
CREATE TABLE IF NOT EXISTS {db}.sec_empresas_cuarentena (
  cik                string             COMMENT 'Tal cual en el archivo',
  name               string             COMMENT 'Tal cual en el archivo',
  ticker             string             COMMENT 'Tal cual en el archivo',
  exchange           string             COMMENT 'Tal cual en el archivo',
  _archivo           string    NOT NULL COMMENT 'Linaje: archivo de la SEC del que salió la fila',
  _fecha_publicacion date      NOT NULL COMMENT 'Linaje: fecha en que la SEC actualizó ese archivo',
  motivo             string    NOT NULL COMMENT 'Primera regla del contrato que la fila no cumplió',
  _procesado_en      timestamp NOT NULL COMMENT 'Cuándo la mandó a cuarentena el job (UTC)'
)
USING iceberg
PARTITIONED BY (_archivo)
TBLPROPERTIES ('format-version' = '2')
