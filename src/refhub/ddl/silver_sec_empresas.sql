-- Silver de la SEC: las empresas que cotizan en EE. UU., una fila por ticker (una empresa puede
-- tener varios: BRK-A y BRK-B), validada por el contrato (refhub.contract.sec_problem).
-- Se reemplaza entera con cada archivo nuevo: lo que no vino, ya no existe.
CREATE TABLE IF NOT EXISTS {db}.sec_empresas (
  cik                string NOT NULL COMMENT 'CIK: el identificador de la empresa en la SEC, con 10 dígitos (ceros adelante), como en EDGAR',
  name               string NOT NULL COMMENT 'Nombre de la empresa, tal cual lo publica la SEC',
  ticker             string NOT NULL COMMENT 'Ticker. Una fila por ticker',
  exchange           string          COMMENT 'Bolsa (Nasdaq, NYSE, OTC...); vacía si la SEC no la informa',
  nombre_normalizado string NOT NULL COMMENT 'name normalizado (refhub.names.normalize_name), para cruzar con GLEIF',
  _archivo           string NOT NULL COMMENT 'Linaje: archivo de la SEC del que salió la fila',
  _fecha_publicacion date   NOT NULL COMMENT 'Linaje: fecha en que la SEC actualizó ese archivo'
)
USING iceberg
TBLPROPERTIES ('format-version' = '2')
