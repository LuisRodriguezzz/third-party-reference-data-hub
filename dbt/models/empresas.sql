-- La golden copy: una fila por empresa de la SEC (CIK) con su LEI, elegido con la regla del
-- ADR 0008:
--   1. por códigos, si hay candidatos;
--   2. si no, por nombre;
--      en los dos caminos se desempata igual: primero los LEIs emisores (los que tienen títulos
--      en ISIN↔LEI), después los ISSUED, después los de EE. UU.;
--   3. si los dos caminos dan LEIs distintos, gana códigos y queda conflicto = true;
--   4. si después de desempatar sigue habiendo más de un candidato, no se adivina: queda sin
--      LEI y con ambiguo = true.

with empresas_sec as (
    -- La SEC repite la empresa en cada ticker (BRK-A y BRK-B); el nombre es el mismo.
    select
        cik,
        min(name) as nombre_sec
    from {{ source('silver', 'sec_empresas') }}
    group by cik
),

emisores as (
    select distinct lei
    from {{ source('silver', 'gleif_isin_lei') }}
),

candidatos as (
    select cik, lei, 'codigos' as camino from {{ ref('candidatos_codigos') }}
    union all
    select cik, lei, 'nombre' as camino from {{ ref('candidatos_nombre') }}
),

puntuados as (
    -- rank() deja en el mismo puesto a los empatados: si dos LEIs quedan primeros, los dos
    -- tienen puesto = 1 y eso es lo que después marca la ambigüedad.
    select
        candidatos.cik,
        candidatos.camino,
        candidatos.lei,
        rank() over (
            partition by candidatos.cik, candidatos.camino
            order by
                case when emisores.lei is not null then 0 else 1 end,
                case when gleif.registration_status = 'ISSUED' then 0 else 1 end,
                case when gleif.country = 'US' then 0 else 1 end
        ) as puesto
    from candidatos
    left join emisores
        on emisores.lei = candidatos.lei
    left join {{ source('silver', 'gleif_lei') }} as gleif
        on gleif.lei = candidatos.lei
),

ganador_por_camino as (
    -- Para cada CIK y camino: el LEI si quedó uno solo arriba; si quedaron varios, ninguno.
    select
        cik,
        camino,
        if(count(*) = 1, max(lei)) as lei,
        count(*) > 1 as ambiguo
    from puntuados
    where puesto = 1
    group by cik, camino
),

caminos as (
    -- Una fila por CIK con lo que dio cada camino, lado a lado.
    select
        cik,
        bool_or(camino = 'codigos') as hay_codigos,
        max(if(camino = 'codigos', lei)) as lei_codigos,
        bool_or(camino = 'codigos' and ambiguo) as ambiguo_codigos,
        bool_or(camino = 'nombre') as hay_nombre,
        max(if(camino = 'nombre', lei)) as lei_nombre,
        bool_or(camino = 'nombre' and ambiguo) as ambiguo_nombre
    from ganador_por_camino
    group by cik
),

elegido as (
    select
        cik,
        if(hay_codigos, lei_codigos, lei_nombre) as lei,
        case
            when hay_codigos then 'codigos'
            when hay_nombre then 'nombre'
        end as camino,
        coalesce(if(hay_codigos, ambiguo_codigos, ambiguo_nombre), false) as ambiguo,
        -- Conflicto: los dos caminos eligieron un LEI y no es el mismo. Gana códigos, pero el
        -- otro LEI queda a la vista para revisarlo (gold set, 5F).
        coalesce(lei_codigos <> lei_nombre, false) as conflicto,
        if(lei_codigos <> lei_nombre, lei_nombre) as lei_en_conflicto
    from caminos
)

select
    empresas_sec.cik,
    empresas_sec.nombre_sec,
    elegido.lei,
    gleif.legal_name,
    gleif.country,
    gleif.entity_status,
    gleif.registration_status,
    cast(elegido.camino as varchar) as camino,
    coalesce(elegido.conflicto, false) as conflicto,
    elegido.lei_en_conflicto,
    coalesce(elegido.ambiguo, false) as ambiguo
from empresas_sec
-- left join: las empresas sin ningún candidato también van, con LEI nulo.
left join elegido
    on elegido.cik = empresas_sec.cik
left join {{ source('silver', 'gleif_lei') }} as gleif
    on gleif.lei = elegido.lei
