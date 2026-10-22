-- Exposición sumada por grupo, con la cabeza que sale de recorrer el árbol de consolidación
-- directa hacia arriba (cabeza_arbol de la vista cabeza_por_prestamo, en esquema.sql).
-- Montos INVENTADOS (cartera sintética, ADR 0013): las cifras no son un hallazgo.
--
-- ROLLUP (grupo, empresa) suma por empresa, por grupo y el total, en una sola pasada. GROUPING()
-- dice qué fila es un subtotal. Se muestran los cinco grupos más expuestos entre los que tienen
-- más de una empresa con préstamos: los que una mirada préstamo por préstamo no ve.
SET LINESIZE 200 PAGESIZE 100 FEEDBACK OFF
COLUMN grupo FORMAT A40 TRUNCATED
COLUMN empresa FORMAT A40 TRUNCATED
COLUMN monto_usd FORMAT 999,999,999,990

WITH grupos_con_varias AS (
  SELECT cabeza_arbol FROM cabeza_por_prestamo
  GROUP BY cabeza_arbol HAVING COUNT(DISTINCT lei) > 1
  ORDER BY SUM(monto_usd) DESC
  FETCH FIRST 5 ROWS ONLY
),
sumas AS (
  SELECT cabeza_arbol, lei, SUM(monto_usd) AS monto_usd,
         GROUPING(cabeza_arbol) AS es_total, GROUPING(lei) AS es_subtotal
  FROM cabeza_por_prestamo
  WHERE cabeza_arbol IN (SELECT cabeza_arbol FROM grupos_con_varias)
  GROUP BY ROLLUP (cabeza_arbol, lei)
)
SELECT
  CASE WHEN s.es_total = 1 THEN '== TOTAL ==' ELSE NVL(cab.nombre, s.cabeza_arbol) END AS grupo,
  CASE WHEN s.es_subtotal = 1 AND s.es_total = 0 THEN '-- subtotal del grupo --'
       WHEN s.es_total = 0 THEN NVL(emp.nombre, s.lei) END AS empresa,
  s.monto_usd
FROM sumas s
LEFT JOIN entidades cab ON cab.lei = s.cabeza_arbol
LEFT JOIN entidades emp ON emp.lei = s.lei
-- Los grupos de mayor a menor exposición; adentro de cada uno, el subtotal al final. El total
-- general va último.
ORDER BY s.es_total,
         MAX(CASE WHEN s.es_subtotal = 1 THEN s.monto_usd END)
           OVER (PARTITION BY s.cabeza_arbol) DESC,
         s.es_subtotal, s.monto_usd DESC;
