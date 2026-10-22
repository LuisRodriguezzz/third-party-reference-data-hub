-- La métrica honesta del cruce CIK↔LEI (5F, ADR 0008): precisión y recall contra el gold set,
-- con su margen. scorecard_cruce dice cuántas empresas quedaron con LEI (cobertura); esto dice
-- cuántas de esas tienen el LEI correcto (acierto).
--
-- Una fila por segmento: 'codigos' y 'nombre' (los CIK del gold set que el cruce resolvió, o
-- quedaron ambiguos, por ese camino) y 'total' (todo el gold set).

with casos as (
    -- Un caso por CIK del gold set, con lo que eligió el cruce al lado de la respuesta correcta.
    -- left join: si la SEC dejó de publicar un CIK de la muestra, el caso sigue contando (el
    -- seed tiene un test que avisa).
    select
        gold_set.cik,
        gold_set.lei_correcto,
        gold_set.auditado,
        gold_set.auditoria_coincide,
        empresas.lei as lei_elegido,
        empresas.camino,
        coalesce(empresas.ambiguo, false) as ambiguo,
        -- DUDA: quien etiquetó no pudo decidir. No hay contra qué comparar, así que el caso no
        -- entra en ninguna cifra; se cuenta aparte para que se vea cuántos quedaron afuera.
        gold_set.lei_correcto = 'DUDA' as es_duda,
        gold_set.lei_correcto not in ('SIN_LEI', 'DUDA') as tiene_lei_real
    from {{ ref('gold_set') }} as gold_set
    left join {{ ref('empresas') }} as empresas
        on empresas.cik = gold_set.cik
),

clasificados as (
    -- Cada caso que no es DUDA cae en estos casilleros. Siempre se cumple que
    --   asignados    = correctos + lei_equivocado + asignados_sin_lei
    --   con_lei_real = correctos + lei_equivocado + no_encontrados
    -- (las comparaciones con un LEI nulo dan nulo, y count_if no las cuenta).
    select
        *,
        not es_duda and lei_elegido is not null as asignado,
        not es_duda and lei_elegido = lei_correcto as correcto,
        -- La empresa tiene LEI y el cruce eligió otro: cuenta en contra de la precisión (asignó
        -- mal) y del recall (no encontró el correcto).
        tiene_lei_real and lei_elegido <> lei_correcto as lei_equivocado,
        -- La empresa no tiene LEI y el cruce le asignó uno (el caso Chevron): falso positivo,
        -- cuenta en contra de la precisión. Es el error más caro: suma exposición a quien no es.
        lei_correcto = 'SIN_LEI' and lei_elegido is not null as asignado_sin_lei,
        -- La empresa tiene LEI y el cruce la dejó sin ninguno (sin candidatos o ambigua).
        tiene_lei_real and lei_elegido is null as no_encontrado
    from casos
),

segmentos as (
    select segmento
    from (values 'codigos', 'nombre', 'total') as t (segmento)
),

conteos as (
    -- Se arma desde segmentos para que las tres filas estén siempre, aunque un camino no tenga
    -- casos en la muestra: queda en cero, no desaparece.
    select
        segmentos.segmento,
        count(clasificados.cik) as casos,
        count_if(clasificados.es_duda) as duda,
        count_if(clasificados.asignado) as asignados,
        count_if(clasificados.correcto) as correctos,
        count_if(clasificados.lei_equivocado) as lei_equivocado,
        count_if(clasificados.asignado_sin_lei) as asignados_sin_lei,
        count_if(clasificados.tiene_lei_real) as con_lei_real,
        count_if(clasificados.no_encontrado) as no_encontrados,
        count_if(clasificados.ambiguo and not clasificados.es_duda) as ambiguos,
        count_if(clasificados.auditado) as auditados,
        count_if(clasificados.auditoria_coincide) as auditoria_coincide
    from segmentos
    left join clasificados
        on segmentos.segmento in ('total', clasificados.camino)
    group by segmentos.segmento
),

proporciones as (
    -- Precisión: de los CIK a los que el cruce les asignó un LEI, cuántos tienen el correcto.
    --   denominador = asignados: entran los LEIs equivocados y los asignados a una SIN_LEI.
    -- Recall: de los CIK que tienen LEI de verdad, a cuántos el cruce les encontró el correcto.
    --   denominador = con_lei_real: sin las SIN_LEI, a las que no hay nada que encontrarles.
    -- El recall va solo en 'total'. Por camino no tiene sentido: una empresa que el cruce no
    -- encontró no tiene camino, así que no hay forma de repartir el denominador entre los dos.
    -- nullif: sin casos, la proporción es nula (en Athena dividir por cero da error).
    select
        *,
        cast(correctos as double) / nullif(asignados, 0) as p_precision,
        cast(nullif(asignados, 0) as double) as n_precision,
        if(segmento = 'total', cast(correctos as double) / nullif(con_lei_real, 0)) as p_recall,
        if(segmento = 'total', cast(nullif(con_lei_real, 0) as double)) as n_recall
    from conteos
),

-- El margen es el intervalo de confianza del 95 % de Wilson (Wilson, 1927), el estándar para
-- una proporción con muestras chicas. Con p = éxitos / n y z = 1,96 (el valor de la normal que
-- deja 2,5 % en cada cola):
--
--   centro = (p + z²/2n) / (1 + z²/n)
--   radio  = z / (1 + z²/n) · √( p(1-p)/n + z²/4n² )
--   intervalo = centro ± radio
--
-- Por qué Wilson y no la aproximación normal (p ± z·√(p(1-p)/n)): con n chico y p cerca de 1,
-- que es lo esperable en precisión, la normal da intervalos que se pasan de 1, y con p = 1 da
-- margen cero, como si 30 aciertos de 30 probaran que el cruce nunca se equivoca. Wilson queda
-- siempre entre 0 y 1 y con p = 1 igual deja margen hacia abajo.
wilson as (
    select
        *,
        (p_precision + 1.96e0 * 1.96e0 / (2 * n_precision))
        / (1 + 1.96e0 * 1.96e0 / n_precision) as centro_precision,
        1.96e0 / (1 + 1.96e0 * 1.96e0 / n_precision) * sqrt(
            p_precision * (1 - p_precision) / n_precision
            + 1.96e0 * 1.96e0 / (4 * n_precision * n_precision)
        ) as radio_precision,
        (p_recall + 1.96e0 * 1.96e0 / (2 * n_recall))
        / (1 + 1.96e0 * 1.96e0 / n_recall) as centro_recall,
        1.96e0 / (1 + 1.96e0 * 1.96e0 / n_recall) * sqrt(
            p_recall * (1 - p_recall) / n_recall
            + 1.96e0 * 1.96e0 / (4 * n_recall * n_recall)
        ) as radio_recall
    from proporciones
)

-- Redondeado a 4 decimales: con 100 casos, más decimales son ruido.
select
    segmento,
    casos,
    duda,
    asignados,
    correctos,
    lei_equivocado,
    asignados_sin_lei,
    con_lei_real,
    no_encontrados,
    ambiguos,
    auditados,
    auditoria_coincide,
    round(p_precision, 4) as precision_puntual,
    round(centro_precision - radio_precision, 4) as precision_desde,
    round(centro_precision + radio_precision, 4) as precision_hasta,
    round(p_recall, 4) as recall_puntual,
    round(centro_recall - radio_recall, 4) as recall_desde,
    round(centro_recall + radio_recall, 4) as recall_hasta
from wilson
