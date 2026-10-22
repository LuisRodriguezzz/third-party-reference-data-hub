-- El scorecard de las fuentes: una fila por fuente con qué tan fresca está (la última fecha
-- publicada que llegó a silver), cuántas filas tiene y qué parte de la última carga fue a
-- cuarentena. De acá salen las métricas de CloudWatch (refhub.metricas) y la alarma de "hay
-- fuentes atrasadas".

with reglas as (
    -- LA REGLA DE "ATRASADA" (de negocio): cuántos días puede pasar una fuente sin publicar
    -- nada nuevo antes de que la marquemos. Se compara contra la fecha de publicación del
    -- proveedor (event time), no contra cuándo corrió el pipeline. Si cambia la frecuencia de
    -- una fuente, se cambia acá y en el unit test de scorecard_fuentes.yml.
    select * from (
        values
            -- GLEIF publica el delta tres veces por día, todos los días: 1 día de margen cubre
            -- una corrida perdida.
            ('gleif', 1),
            -- La foto ISIN↔LEI sale una vez por día (GLEIF y ANNA): 2 días, por si un día no sale.
            ('gleif_isin_lei', 2),
            -- Las relaciones (nivel 2) salen con cada publicación del golden copy, como el delta.
            ('gleif_rr', 1),
            -- La SEC actualiza su lista de empresas sin un calendario fijo (el 12-oct el archivo
            -- tenía 5 días): una semana.
            ('sec', 7),
            -- OpenFIGI no publica: la fecha es la de la consulta, que hace cada corrida.
            ('openfigi', 1)
    ) as t (fuente, dias_tolerados)
),

ultima_corrida_gleif as (
    -- GLEIF es incremental: la cuarentena de la última carga sale del registro de archivos
    -- procesados (los archivos de la última corrida).
    select
        sum(filas - rechazadas) as filas_cargadas,
        sum(rechazadas) as filas_cuarentena
    from {{ source('silver', 'gleif_archivos_procesados') }}
    where procesado_en = (
        select max(procesado_en) from {{ source('silver', 'gleif_archivos_procesados') }}
    )
),

-- Las fotos completas (ISIN↔LEI, SEC, relaciones) tienen un solo archivo en silver: el último.
-- Su cuarentena es la de ese archivo.
isin_lei as (
    select max(_fecha_publicacion) as ultima_publicacion, count(*) as filas, max(_archivo) as archivo
    from {{ source('silver', 'gleif_isin_lei') }}
),

sec as (
    select max(_fecha_publicacion) as ultima_publicacion, count(*) as filas, max(_archivo) as archivo
    from {{ source('silver', 'sec_empresas') }}
),

relaciones as (
    select max(_fecha_publicacion) as ultima_publicacion, count(*) as filas, max(_archivo) as archivo
    from {{ source('silver', 'gleif_relaciones') }}
),

medidas as (
    select
        'gleif' as fuente,
        'gleif_lei' as tabla,
        max(_fecha_publicacion) as ultima_publicacion,
        count(*) as filas,
        (select filas_cargadas from ultima_corrida_gleif) as filas_cargadas,
        (select filas_cuarentena from ultima_corrida_gleif) as filas_cuarentena
    from {{ source('silver', 'gleif_lei') }}

    union all

    select
        'gleif_isin_lei', 'gleif_isin_lei', ultima_publicacion, filas, filas,
        (
            select count(*) from {{ source('silver', 'gleif_isin_lei_cuarentena') }} as c
            where c._archivo = isin_lei.archivo
        )
    from isin_lei

    union all

    select
        'sec', 'sec_empresas', ultima_publicacion, filas, filas,
        (
            select count(*) from {{ source('silver', 'sec_empresas_cuarentena') }} as c
            where c._archivo = sec.archivo
        )
    from sec

    union all

    select
        'gleif_rr', 'gleif_relaciones', ultima_publicacion, filas, filas,
        (
            select count(*) from {{ source('silver', 'gleif_relaciones_cuarentena') }} as c
            where c._archivo = relaciones.archivo
        )
    from relaciones

    union all

    -- OpenFIGI no tiene contrato con cuarentena: un ISIN sin resultado es una respuesta válida.
    select
        'openfigi', 'openfigi_tickers', max(_fecha_publicacion), count(*), count(*),
        cast(null as bigint)
    from {{ source('silver', 'openfigi_tickers') }}
),

con_atraso as (
    select
        medidas.*,
        reglas.dias_tolerados,
        -- fecha_scorecard es hoy; el unit test la fija para que el resultado no dependa del día.
        date_diff('day', medidas.ultima_publicacion, {{ var('fecha_scorecard', 'current_date') }})
            as dias_sin_publicar
    from medidas
    inner join reglas
        on reglas.fuente = medidas.fuente
)

select
    cast(fuente as varchar) as fuente,
    cast(tabla as varchar) as tabla,
    ultima_publicacion,
    cast(dias_tolerados as integer) as dias_tolerados,
    cast(dias_sin_publicar as integer) as dias_sin_publicar,
    cast(greatest(dias_sin_publicar - dias_tolerados, 0) as integer) as dias_atraso,
    -- Una fuente sin datos (tabla vacía, sin fecha) cuenta como atrasada: no hay nada fresco.
    coalesce(dias_sin_publicar > dias_tolerados, true) as atrasada,
    cast(filas as bigint) as filas,
    cast(filas_cuarentena as bigint) as filas_cuarentena,
    -- Qué parte de la última carga fue a cuarentena, de 0 a 100.
    cast(
        round(100.0 * filas_cuarentena / nullif(filas_cargadas + filas_cuarentena, 0), 4)
        as double
    ) as porcentaje_cuarentena
from con_atraso
