-- La exposición por grupo económico: cuánto se le prestó a cada grupo, sumando todas sus
-- empresas (ADR 0013). Es la pregunta "si este grupo quiebra, ¿cuánto perdemos?": para el
-- límite de crédito importa la suma del grupo, no cada préstamo suelto.
-- OJO: la cartera es sintética (montos inventados). Las cifras no son un hallazgo.

with prestamos as (
    -- Un LEI que no está en grupos (no está en GLEIF) es su propio grupo: no se pierde el
    -- préstamo por no saber a quién sumarlo.
    select
        cartera.prestamo_id,
        cartera.lei,
        cartera.monto_usd,
        coalesce(grupos.controlante_final_lei, cartera.lei) as controlante_final_lei,
        grupos.controlante_final_nombre
    from {{ ref('cartera_sintetica') }} as cartera
    left join {{ ref('grupos') }} as grupos
        on grupos.lei = cartera.lei
),

-- La SEC puede tener dos CIK con el mismo LEI: con distinct, el cruce no duplica grupos.
leis_sec as (
    select distinct lei
    from {{ ref('empresas') }}
    where lei is not null
)

select
    prestamos.controlante_final_lei,
    max(prestamos.controlante_final_nombre) as controlante_final_nombre,
    cast(sum(prestamos.monto_usd) as decimal(18, 2)) as monto_total_usd,
    count(distinct prestamos.lei) as empresas_con_prestamos,
    count(*) as prestamos,
    cast(max(prestamos.monto_usd) as decimal(18, 2)) as prestamo_mayor_usd,
    max(leis_sec.lei is not null) as cabeza_en_sec
from prestamos
left join leis_sec
    on leis_sec.lei = prestamos.controlante_final_lei
group by prestamos.controlante_final_lei
