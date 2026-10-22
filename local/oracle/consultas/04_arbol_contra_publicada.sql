-- La cabeza de cada préstamo según los dos enfoques, lado a lado (vista cabeza_por_prestamo):
--   arbol:     subir por la consolidación directa hasta arriba (lo que suma 03_exposicion_rollup)
--   publicada: la controlante final que declara GLEIF (gold.grupos, lo que usa
--              gold.exposicion_por_grupo, ADR 0013)
-- Montos INVENTADOS (cartera sintética, ADR 0013).
SET LINESIZE 200 PAGESIZE 100 FEEDBACK OFF
COLUMN resultado FORMAT A40
COLUMN grupo FORMAT A40 TRUNCATED
COLUMN empresa FORMAT A35 TRUNCATED
COLUMN cabeza_arbol FORMAT A35 TRUNCATED
COLUMN cabeza_publicada FORMAT A35 TRUNCATED
COLUMN monto_usd FORMAT 999,999,999,990
COLUMN monto_publicada FORMAT 999,999,999,990
COLUMN monto_arbol FORMAT 999,999,999,990

-- 1) Cuántos préstamos caen en el mismo grupo con los dos enfoques.
SELECT
  CASE
    WHEN cabeza_arbol = cabeza_publicada AND cabeza_arbol = lei THEN 'iguales: es su propio grupo'
    WHEN cabeza_arbol = cabeza_publicada THEN 'iguales: misma cabeza'
    WHEN cabeza_arbol = lei THEN 'distintos: sin controlante directa'
    WHEN cabeza_publicada = lei THEN 'distintos: GLEIF no publica final'
    ELSE 'distintos: el arbol corta antes'
  END AS resultado,
  COUNT(*) AS prestamos,
  SUM(monto_usd) AS monto_usd
FROM cabeza_por_prestamo
GROUP BY resultado
ORDER BY prestamos DESC;

-- 2) Los grupos (según GLEIF) que cambian de monto si se recorre el árbol.
SELECT NVL(e.nombre, x.cabeza_publicada) AS grupo,
       SUM(x.monto_usd) AS monto_publicada,
       SUM(CASE WHEN x.cabeza_arbol = x.cabeza_publicada THEN x.monto_usd ELSE 0 END)
         AS monto_arbol
FROM cabeza_por_prestamo x
LEFT JOIN entidades e ON e.lei = x.cabeza_publicada
GROUP BY NVL(e.nombre, x.cabeza_publicada)
HAVING COUNT(CASE WHEN x.cabeza_arbol <> x.cabeza_publicada THEN 1 END) > 0
ORDER BY monto_publicada DESC;

-- 3) Los préstamos donde los enfoques no coinciden, con nombres.
SELECT NVL(e.nombre, x.lei) AS empresa,
       NVL(a.nombre, x.cabeza_arbol) AS cabeza_arbol,
       NVL(p.nombre, x.cabeza_publicada) AS cabeza_publicada,
       x.monto_usd
FROM cabeza_por_prestamo x
LEFT JOIN entidades e ON e.lei = x.lei
LEFT JOIN entidades a ON a.lei = x.cabeza_arbol
LEFT JOIN entidades p ON p.lei = x.cabeza_publicada
WHERE x.cabeza_arbol <> x.cabeza_publicada
ORDER BY cabeza_publicada, empresa;
