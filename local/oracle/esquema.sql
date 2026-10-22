-- El esquema del sistema de riesgo (consumidor de la golden copy, ADR 0014), en el usuario RIESGO.
-- cargar_oracle.py lo corre entero en cada carga: borra y recrea, porque es una copia de lo que
-- publica el hub, no datos propios del sistema.

DROP TABLE IF EXISTS relaciones_directas;
DROP TABLE IF EXISTS controlante_publicada;
DROP TABLE IF EXISTS cartera_sintetica;
DROP TABLE IF EXISTS entidades;

-- Los nombres de las empresas del árbol y de la cartera (silver.gleif_lei).
CREATE TABLE entidades (
  lei    VARCHAR2(20)   PRIMARY KEY,
  nombre VARCHAR2(1000) NOT NULL,
  pais   VARCHAR2(2)    NOT NULL
);

-- Quién consolida directamente a quién (IS_DIRECTLY_CONSOLIDATED_BY vigente). La clave es la
-- hija: cada empresa declara UNA controlante directa, así que el conjunto es un bosque de árboles.
CREATE TABLE relaciones_directas (
  hija_lei        VARCHAR2(20) PRIMARY KEY,
  controlante_lei VARCHAR2(20) NOT NULL
);
-- Para bajar por el árbol (de la controlante a sus hijas) hace falta buscar por controlante.
CREATE INDEX relaciones_directas_controlante ON relaciones_directas (controlante_lei);

CREATE TABLE cartera_sintetica (
  prestamo_id VARCHAR2(10)  PRIMARY KEY,
  lei         VARCHAR2(20)  NOT NULL,
  monto_usd   NUMBER(18, 2) NOT NULL,
  producto    VARCHAR2(40)  NOT NULL
);
COMMENT ON TABLE cartera_sintetica IS
  'Cartera INVENTADA (ADR 0013): LEIs reales, montos y préstamos inventados. Sus cifras no son un hallazgo.';

-- La controlante final que publica GLEIF para cada empresa de la cartera (gold.grupos), para
-- comparar con la que sale de recorrer el árbol.
CREATE TABLE controlante_publicada (
  lei                   VARCHAR2(20) PRIMARY KEY,
  controlante_final_lei VARCHAR2(20) NOT NULL
);

-- Cada préstamo con la cabeza de su grupo según los dos enfoques. La usan las consultas 03 y 04.
--   cabeza_arbol:     se sube de hija a controlante directa hasta que no hay más (CONNECT BY
--                     hacia arriba). CONNECT_BY_ROOT es la empresa de la que se partió, y la fila
--                     hoja (CONNECT_BY_ISLEAF = 1) trae en controlante_lei la última controlante.
--   cabeza_publicada: la controlante final que declara GLEIF (lo que usa gold, ADR 0013).
-- Una empresa sin controlante es la cabeza de su propio grupo, en los dos enfoques.
CREATE OR REPLACE VIEW cabeza_por_prestamo AS
WITH subida AS (
  SELECT CONNECT_BY_ROOT hija_lei AS lei, controlante_lei AS cabeza_lei
  FROM relaciones_directas
  WHERE CONNECT_BY_ISLEAF = 1
  START WITH hija_lei IN (SELECT lei FROM cartera_sintetica)
  CONNECT BY NOCYCLE hija_lei = PRIOR controlante_lei
)
SELECT c.prestamo_id, c.lei, c.monto_usd,
       COALESCE(s.cabeza_lei, c.lei) AS cabeza_arbol,
       COALESCE(p.controlante_final_lei, c.lei) AS cabeza_publicada
FROM cartera_sintetica c
LEFT JOIN subida s ON s.lei = c.lei
LEFT JOIN controlante_publicada p ON p.lei = c.lei
