-- Una fila por LEI con su controlante final: la cabeza de su grupo económico (ADR 0013).
-- GLEIF ya publica la controlante final (IS_ULTIMATELY_CONSOLIDATED_BY), así que es un join y no
-- hace falta recorrer el árbol. Si un LEI no tiene una que cuente, es cabeza de su propio grupo.
--
-- Qué relación cuenta:
--   - solo la consolidación contable final: la gestión de fondos (IS_FUND-MANAGED_BY), los
--     subfondos, los feeders y las sucursales no arman un grupo económico (ver el ADR);
--   - solo las activas y no vencidas: una relación INACTIVE o con fecha de fin pasada ya no dice
--     quién controla hoy;
--   - con el registro PUBLISHED o LAPSED: LAPSED es que la empresa no lo renovó, no que sea
--     falso. Para sumar exposición es más prudente agrupar de más que de menos; el estado queda
--     en registro_relacion para quien quiera ser más estricto.

with relaciones_de_grupo as (
    -- Silver tiene una fila por child_lei y relationship_type: a lo sumo una por hija.
    select
        child_lei,
        parent_lei,
        registration_status
    from {{ source('silver', 'gleif_relaciones') }}
    where relationship_type = 'IS_ULTIMATELY_CONSOLIDATED_BY'
        and relationship_status = 'ACTIVE'
        and (relationship_end is null or relationship_end > current_timestamp)
        and registration_status in ('PUBLISHED', 'LAPSED')
),

con_controlante as (
    -- Una empresa que se declara controlante de sí misma (pasa 2 veces) da lo mismo que no
    -- tener ninguna: queda como cabeza de su grupo.
    select
        gleif.lei,
        gleif.legal_name,
        coalesce(relaciones.parent_lei, gleif.lei) as controlante_final_lei,
        relaciones.registration_status as registro_relacion
    from {{ source('silver', 'gleif_lei') }} as gleif
    left join relaciones_de_grupo as relaciones
        on relaciones.child_lei = gleif.lei
)

select
    con_controlante.lei,
    con_controlante.legal_name,
    con_controlante.controlante_final_lei,
    -- Nulo si la controlante no está en silver (pasa con 11 LEIs que GLEIF nombra como cabeza).
    cabeza.legal_name as controlante_final_nombre,
    con_controlante.controlante_final_lei = con_controlante.lei as es_cabeza,
    con_controlante.registro_relacion
from con_controlante
left join {{ source('silver', 'gleif_lei') }} as cabeza
    on cabeza.lei = con_controlante.controlante_final_lei
