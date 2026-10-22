-- Silver de OpenFIGI: para cada ISIN de acciones de EE. UU. de gleif_isin_lei, su ticker y su
-- FIGI en EE. UU. Es el eslabón del cruce por códigos: ticker de la SEC -> ISIN -> LEI.
-- Una fila por ISIN mandado, haya o no resultado (sin resultado, motivo dice por qué).
-- Se reemplaza entera en cada corrida: es la foto de lo que respondió OpenFIGI ese día.
CREATE TABLE IF NOT EXISTS {db}.openfigi_tickers (
  isin               string NOT NULL COMMENT 'El ISIN que se mandó a OpenFIGI. Una fila por ISIN',
  figi               string          COMMENT 'FIGI del listado en EE. UU.; nulo si no hubo resultado',
  composite_figi     string          COMMENT 'FIGI compuesto (todas las bolsas de EE. UU. juntas)',
  ticker             string          COMMENT 'Ticker como lo escribe OpenFIGI (BRK/B, no BRK-B como la SEC)',
  name               string          COMMENT 'Nombre del instrumento según OpenFIGI',
  security_type      string          COMMENT 'securityType2 de OpenFIGI (Common Stock, Depositary Receipt, ...)',
  market_sector      string          COMMENT 'marketSector de OpenFIGI (Equity, ...)',
  resultados         int    NOT NULL COMMENT 'Cuántas filas devolvió OpenFIGI para el ISIN (0 si ninguna); con varias, se guarda la compuesta',
  motivo             string          COMMENT 'Nulo si hubo resultado; si no, el warning o el error de OpenFIGI',
  _archivo           string NOT NULL COMMENT 'Linaje: archivo crudo de landing/openfigi/ de esta corrida',
  _fecha_publicacion date   NOT NULL COMMENT 'Linaje: fecha de la consulta a OpenFIGI (UTC)'
)
USING iceberg
TBLPROPERTIES ('format-version' = '2')
