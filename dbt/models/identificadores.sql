-- Las referencias cruzadas de cada empresa en formato largo: una fila por (cik, esquema, valor).
-- Es la forma estándar de un maestro de referencia: una empresa con 2.000 ISINs son 2.000 filas,
-- no una columna con una lista, y un esquema nuevo (CUSIP, por ejemplo) es más filas, no una
-- columna nueva. Para buscar "¿de quién es este ISIN?" alcanza con un where.
-- fuente dice de dónde sale el vínculo entre el CIK y el valor.

with empresas as (
    select cik, lei, camino
    from {{ ref('empresas') }}
),

-- Los ISINs y FIGIs cuelgan del LEI elegido, salga del camino que salga.
isins as (
    select
        empresas.cik,
        isin_lei.isin
    from empresas
    inner join {{ source('silver', 'gleif_isin_lei') }} as isin_lei
        on isin_lei.lei = empresas.lei
)

select cik, cast('CIK' as varchar) as esquema, cik as valor, cast('sec' as varchar) as fuente
from empresas

union all

select distinct cik, 'TICKER', ticker, 'sec'
from {{ source('silver', 'sec_empresas') }}

union all

-- El LEI no lo publica nadie junto al CIK: es lo que deduce el cruce, y se dice por qué camino.
select cik, 'LEI', lei, concat('cruce_', camino)
from empresas
where lei is not null

union all

select cik, 'ISIN', isin, 'gleif_isin_lei'
from isins

union all

select distinct isins.cik, 'FIGI', figi.figi, 'openfigi'
from isins
inner join {{ source('silver', 'openfigi_tickers') }} as figi
    on figi.isin = isins.isin
where figi.figi is not null
