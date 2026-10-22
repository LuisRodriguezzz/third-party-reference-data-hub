-- El árbol de un grupo, desde la controlante hasta la última controlada, con la sintaxis propia
-- de Oracle (CONNECT BY, anterior al estándar y la que más se encuentra en sistemas de
-- riesgo heredados). Grupo de ejemplo: FABER FIVE S.R.L. (815600CBA3B99EDBA070), con cuatro
-- niveles debajo de la cabeza.
--
--   START WITH            dónde empieza: las hijas directas de la cabeza.
--   CONNECT BY PRIOR      cómo se baja: la hija de esta fila es la controlante de la siguiente.
--   NOCYCLE               si GLEIF tuviera un ciclo (A controla a B y B a A), corta en vez de
--                         dar error.
--   LEVEL                 a qué distancia de la cabeza está cada empresa.
--   SYS_CONNECT_BY_PATH   el camino completo desde la cabeza.
--   ORDER SIBLINGS BY     ordena entre hermanas sin romper el orden del árbol.
SET LINESIZE 250 PAGESIZE 100 FEEDBACK OFF
COLUMN empresa FORMAT A60 TRUNCATED
COLUMN camino FORMAT A40

SELECT
  LEVEL AS nivel,
  LPAD(' ', 2 * (LEVEL - 1)) || NVL(e.nombre, r.hija_lei) AS empresa,
  -- Los LEIs completos no entran en pantalla: el camino usa los últimos 6 caracteres.
  SYS_CONNECT_BY_PATH(SUBSTR(r.hija_lei, -6), '/') AS camino
FROM relaciones_directas r
LEFT JOIN entidades e ON e.lei = r.hija_lei
START WITH r.controlante_lei = '815600CBA3B99EDBA070'
CONNECT BY NOCYCLE PRIOR r.hija_lei = r.controlante_lei
-- Entre hermanas, por LEI: el mismo orden que SEARCH DEPTH FIRST BY hija_lei en 02.
ORDER SIBLINGS BY r.hija_lei;
