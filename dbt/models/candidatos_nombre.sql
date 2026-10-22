-- Camino por nombre: el mismo nombre normalizado en la SEC y en GLEIF ("APPLE INC" y
-- "Apple Inc." dan lo mismo con refhub.names.normalize_name). Sirve cuando no hay códigos, pero
-- dos empresas pueden llamarse igual: por eso solo se usa si no hay camino por códigos, y con
-- más de un candidato hay que desempatar (lo hace empresas). Una fila por par (cik, lei).

with emisores as (
    select distinct lei
    from {{ source('silver', 'gleif_isin_lei') }}
)

select distinct
    sec.cik,
    gleif.lei
from {{ source('silver', 'sec_empresas') }} as sec
inner join {{ source('silver', 'gleif_lei') }} as gleif
    on gleif.nombre_normalizado = sec.nombre_normalizado
left join emisores
    on emisores.lei = gleif.lei
-- Los nombres en alfabetos no latinos quedan vacíos al normalizarse (135 mil LEIs de GLEIF):
-- sin este filtro, todos los vacíos "coincidirían" entre sí.
where sec.nombre_normalizado <> ''
    and gleif.nombre_normalizado <> ''
    -- Solo LEIs de EE. UU. o que emitieron títulos. La normalización saca la forma jurídica, así
    -- que "CHEVRON CORP" coincide con CHEVRON LIMITED de Malta, y si es el único candidato
    -- ganaría. Medido el 21-oct-2026: sin este filtro, 686 de los 4.591 LEIs elegidos por nombre
    -- eran extranjeros sin títulos. Una emisora extranjera que cotiza en EE. UU. (Toyota, por
    -- ejemplo) sigue entrando porque tiene ISINs. Ver ADR 0008.
    and (gleif.country = 'US' or emisores.lei is not null)
