-- La misma consulta que 01_arbol_connect_by.sql, en SQL estándar (WITH recursivo, SQL:1999).
-- Corre casi igual en PostgreSQL, SQL Server, DB2 o Trino; en PostgreSQL se escribe
-- WITH RECURSIVE.
--
--   El ancla (antes del UNION ALL)  las hijas directas de la cabeza: nivel 1.
--   La parte recursiva              se une con la tabla para bajar un nivel por vuelta, hasta
--                                   que no hay más hijas.
--   SEARCH DEPTH FIRST              el orden del árbol (cada empresa seguida de sus controladas),
--                                   lo que en CONNECT BY sale solo.
--   CYCLE                           la protección contra ciclos, lo que en CONNECT BY es NOCYCLE.
SET LINESIZE 250 PAGESIZE 100 FEEDBACK OFF
COLUMN empresa FORMAT A60 TRUNCATED
COLUMN camino FORMAT A40

WITH arbol (nivel, hija_lei, camino) AS (
  SELECT 1, hija_lei, '/' || SUBSTR(hija_lei, -6)
  FROM relaciones_directas
  WHERE controlante_lei = '815600CBA3B99EDBA070'
  UNION ALL
  SELECT a.nivel + 1, r.hija_lei, a.camino || '/' || SUBSTR(r.hija_lei, -6)
  FROM arbol a
  JOIN relaciones_directas r ON r.controlante_lei = a.hija_lei
)
SEARCH DEPTH FIRST BY hija_lei SET orden
CYCLE hija_lei SET es_ciclo TO 'S' DEFAULT 'N'
SELECT
  a.nivel,
  LPAD(' ', 2 * (a.nivel - 1)) || NVL(e.nombre, a.hija_lei) AS empresa,
  a.camino
FROM arbol a
LEFT JOIN entidades e ON e.lei = a.hija_lei
WHERE a.es_ciclo = 'N'
ORDER BY a.orden;
