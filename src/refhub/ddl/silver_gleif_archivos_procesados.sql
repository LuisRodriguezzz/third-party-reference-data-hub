-- Registro de archivos de bronze que el job de silver ya procesó. Lo que figura acá no se
-- vuelve a procesar, salvo en un full refresh, que lo reemplaza entero. Se escribe al final de
-- cada corrida.
CREATE TABLE IF NOT EXISTS {db}.gleif_archivos_procesados (
  archivo      string    NOT NULL COMMENT 'Archivo de bronze ya procesado',
  filas        bigint    NOT NULL COMMENT 'Filas que tenía el archivo',
  rechazadas   bigint    NOT NULL COMMENT 'Cuántas de esas filas fueron a cuarentena',
  procesado_en timestamp NOT NULL COMMENT 'Cuándo se procesó (UTC)'
)
USING iceberg
TBLPROPERTIES ('format-version' = '2')
