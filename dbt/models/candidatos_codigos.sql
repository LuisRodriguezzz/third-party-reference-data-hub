-- Camino por códigos: CIK → tickers de la SEC → OpenFIGI (por ticker) → ISIN → LEI.
-- Cada eslabón es un dato publicado por una fuente, nada se deduce: por eso es el camino que
-- manda (ADR 0008). Una fila por cada par (cik, lei) posible; quién gana lo decide empresas.

with tickers_sec as (
    select distinct
        cik,
        ticker
    from {{ source('silver', 'sec_empresas') }}
),

tickers_openfigi as (
    select
        isin,
        -- La SEC escribe la clase de la acción con guion (BRK-B) y OpenFIGI con barra (BRK/B).
        -- Se pasa al formato de la SEC acá y en ningún otro lado.
        replace(ticker, '/', '-') as ticker
    from {{ source('silver', 'openfigi_tickers') }}
    where ticker is not null -- los ISIN que OpenFIGI no encontró no sirven para cruzar
        -- Solo acciones de la empresa. La regla que elige los ISIN de acciones (número de
        -- emisión 10-88) deja pasar fondos: en una muestra de 301 ISIN, 75 de los 137 con
        -- resultado eran 'Mutual Fund'. Quedan afuera los fondos (Mutual Fund, Open-End Fund,
        -- Closed-End Fund, ETP, Unit Inv Tst), cuyo LEI es el del fondo y no el de una empresa,
        -- y los warrants, derechos y units, que no agregan nada: la acción común de la misma
        -- empresa ya da su LEI. Los valores son los de OpenFIGI (/v3/mapping/values/securityType).
        and security_type in (
            'Common Stock', 'Preference', 'Preferred',      -- ordinarias y preferidas
            'ADR', 'GDR', 'NY Reg Shrs',                    -- acciones extranjeras en EE. UU.
            'REIT', 'Ltd Part', 'MLP', 'Royalty Trst',      -- vehículos que cotizan como acciones
            'Tracking Stk', 'Stapled Security'
        )
)

select distinct
    sec.cik,
    isin_lei.lei
from tickers_sec as sec
inner join tickers_openfigi as figi
    on figi.ticker = sec.ticker
inner join {{ source('silver', 'gleif_isin_lei') }} as isin_lei
    on isin_lei.isin = figi.isin
