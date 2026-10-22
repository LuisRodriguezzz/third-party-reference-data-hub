-- El scorecard del cruce CIK↔LEI (ADR 0008): una sola fila con cuántas empresas quedaron con
-- LEI, por qué camino, y cuántas quedaron en conflicto o ambiguas. Es la foto de la calidad de
-- la golden copy en cada corrida.

select
    count(*) as empresas,
    count_if(lei is not null) as con_lei,
    cast(round(100.0 * count_if(lei is not null) / nullif(count(*), 0), 2) as double)
        as porcentaje_con_lei,
    count_if(lei is not null and camino = 'codigos') as por_codigos,
    count_if(lei is not null and camino = 'nombre') as por_nombre,
    count_if(conflicto) as conflictos,
    count_if(ambiguo) as ambiguos,
    count_if(camino is null) as sin_candidatos
from {{ ref('empresas') }}
