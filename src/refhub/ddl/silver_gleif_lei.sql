-- Silver de GLEIF: una fila por LEI, la versión más nueva, con tipos y validada por el contrato
-- (refhub.contract.row_problem). Las columnas que el contrato exige son NOT NULL.
-- {db} lo reemplaza el job por la base de silver (por ejemplo glue_catalog.refhub_silver_dev).
CREATE TABLE IF NOT EXISTS {db}.gleif_lei (
  lei                 string    NOT NULL COMMENT 'LEI (ISO 17442) con dígito verificador válido. Una fila por LEI',
  legal_name          string    NOT NULL COMMENT 'Nombre legal de la entidad',
  country             string    NOT NULL COMMENT 'País de la dirección legal (ISO 3166-1, dos letras)',
  entity_status       string    NOT NULL COMMENT 'Estado de la entidad: ACTIVE, INACTIVE o NULL (texto)',
  registration_status string    NOT NULL COMMENT 'Estado del registro en GLEIF: ISSUED, LAPSED, RETIRED...',
  last_update         timestamp NOT NULL COMMENT 'Última actualización del registro en GLEIF (UTC)',
  next_renewal        timestamp          COMMENT 'Próxima renovación (UTC); vacía si no hay',
  _archivo            string    NOT NULL COMMENT 'Linaje: archivo de GLEIF del que salió la fila',
  _fecha_publicacion  date      NOT NULL COMMENT 'Linaje: fecha en que GLEIF publicó ese archivo',
  -- Al final y sin NOT NULL porque se agregó a una tabla con datos (migraciones/0001): Iceberg
  -- no deja agregar una columna obligatoria. El job la llena siempre.
  nombre_normalizado  string             COMMENT 'legal_name normalizado (refhub.names.normalize_name), para cruzar con la SEC'
)
USING iceberg
TBLPROPERTIES ('format-version' = '2')
