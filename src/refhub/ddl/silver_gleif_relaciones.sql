-- Silver de las relaciones de GLEIF (nivel 2): quién consolida a quién, según la última foto
-- completa. Se reemplaza entera con cada archivo nuevo: lo que no vino, ya no existe.
-- Validada por el contrato (refhub.contract.relationship_problem); lo que exige es NOT NULL.
-- {db} lo reemplaza el job por la base de silver (por ejemplo glue_catalog.refhub_silver_dev).
CREATE TABLE IF NOT EXISTS {db}.gleif_relaciones (
  child_lei           string    NOT NULL COMMENT 'LEI de la empresa hija (StartNode). Una fila por child_lei y relationship_type',
  parent_lei          string    NOT NULL COMMENT 'LEI de la controlante, la gestora o la casa matriz (EndNode)',
  relationship_type   string    NOT NULL COMMENT 'IS_DIRECTLY_CONSOLIDATED_BY, IS_ULTIMATELY_CONSOLIDATED_BY (la cabeza del grupo), IS_FUND-MANAGED_BY...',
  relationship_status string    NOT NULL COMMENT 'Estado de la relación: ACTIVE, INACTIVE o NULL (texto)',
  relationship_start  timestamp          COMMENT 'Desde cuándo vale la relación (UTC); vacía si GLEIF no la tiene',
  relationship_end    timestamp          COMMENT 'Hasta cuándo valió (UTC); vacía si sigue vigente',
  accounting_standard string             COMMENT 'Norma con la que se consolida: IFRS, US_GAAP...; vacía si no es una consolidación o no se informó',
  registration_status string    NOT NULL COMMENT 'Estado del registro de la relación en GLEIF: PUBLISHED, LAPSED...',
  validation_sources  string             COMMENT 'Cuánto la verificó la LOU: FULLY_CORROBORATED, PARTIALLY_CORROBORATED, ENTITY_SUPPLIED_ONLY',
  last_update         timestamp NOT NULL COMMENT 'Última actualización del registro de la relación en GLEIF (UTC)',
  _archivo            string    NOT NULL COMMENT 'Linaje: archivo de GLEIF del que salió la fila',
  _fecha_publicacion  date      NOT NULL COMMENT 'Linaje: fecha en que GLEIF publicó ese archivo'
)
USING iceberg
TBLPROPERTIES ('format-version' = '2')
