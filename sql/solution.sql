-- =====================================================================
-- Prueba técnica Rappi Ads - Parte 1 (SQL)
-- Motor: DuckDB. La lógica de transformación usa sintaxis compatible
-- con Snowflake (CREATE OR REPLACE, QUALIFY, TRY_CAST, DATE_TRUNC).
-- Lo único propio de DuckDB es la carga de los CSV (read_csv); en
-- Snowflake eso se reemplaza por un COPY INTO desde un stage.
--
-- Se puede correr desde cero las veces que sea: todas las tablas
-- se recrean con CREATE OR REPLACE.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 0. Carga de archivos originales
-- Se cargan como texto para no perder registros mal formados en la
-- lectura; los tipos se asignan más abajo con TRY_CAST.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE RAW_CAMPAIGNS AS
SELECT * FROM read_csv('data/CAMPAIGNS.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE RAW_DAILY_PERFORMANCE AS
SELECT * FROM read_csv('data/DAILY_PERFORMANCE.csv', header = true, all_varchar = true);

CREATE OR REPLACE TABLE RAW_CAMPAIGN_TARGETS AS
SELECT * FROM read_csv('data/CAMPAIGN_TARGETS.csv', header = true, all_varchar = true);


-- ---------------------------------------------------------------------
-- 1. Tablas tipadas de campañas y metas
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE CAMPAIGNS AS
SELECT
TRIM(CAMPAIGN_ID)                  AS CAMPAIGN_ID,
COUNTRY,
MAKER,
TRADEMARK,
OBJECTIVE,
TRY_CAST(BUDGET_USD AS DOUBLE)     AS BUDGET_USD,
TRY_CAST(START_DATE AS DATE)       AS START_DATE,
TRY_CAST(END_DATE AS DATE)         AS END_DATE,
UPPER(TRIM(STATUS))                AS STATUS
FROM RAW_CAMPAIGNS;

CREATE OR REPLACE TABLE CAMPAIGN_TARGETS AS
SELECT
TRIM(CAMPAIGN_ID)                  AS CAMPAIGN_ID,
TRY_CAST(TARGET_CTR AS DOUBLE)     AS TARGET_CTR,
TRY_CAST(TARGET_ROAS AS DOUBLE)    AS TARGET_ROAS,
TRY_CAST(TARGET_CPM AS DOUBLE)     AS TARGET_CPM
FROM RAW_CAMPAIGN_TARGETS;


-- ---------------------------------------------------------------------
-- 2. CAMPAIGN_DAILY_CLEAN: una fila por CAMPAIGN_ID + EVENT_DATE
--
-- Orden de los pasos:
--   a) tipar las columnas
--   b) quedarse con la última versión de cada campaña-fecha
--   c) descartar las filas que no pasan las validaciones
--
-- Se deduplica ANTES de validar: la versión más reciente es la que
-- reemplaza a las anteriores. Si esa versión viene con errores, el día
-- se excluye en vez de volver a una versión vieja que ya fue corregida.
--
-- Desempate: si dos registros tienen el mismo UPDATED_AT se conserva el
-- de mayor ROW_ID (se asume que el ROW_ID es consecutivo según llegada).
-- En estos datos los empates son copias exactas, así que el criterio no
-- cambia las métricas, solo asegura que el resultado sea siempre igual.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE CAMPAIGN_DAILY_CLEAN AS
WITH typed AS (
SELECT
ROW_ID,
TRIM(CAMPAIGN_ID)                            AS CAMPAIGN_ID,
TRY_CAST(EVENT_DATE AS DATE)                 AS EVENT_DATE,
TRY_CAST(IMPRESSIONS AS DOUBLE)              AS IMPRESSIONS,
TRY_CAST(CLICKS AS DOUBLE)                   AS CLICKS,
TRY_CAST(SPEND_USD AS DOUBLE)                AS SPEND_USD,
TRY_CAST(ATTRIBUTED_ORDERS AS DOUBLE)        AS ATTRIBUTED_ORDERS,
TRY_CAST(ATTRIBUTED_SALES_USD AS DOUBLE)     AS ATTRIBUTED_SALES_USD,
TRY_CAST(UPDATED_AT AS TIMESTAMP)            AS UPDATED_AT
FROM RAW_DAILY_PERFORMANCE
),

latest_version AS (
-- Los CAMPAIGN_ID nulos quedan agrupados entre sí, pero no importa
-- porque se eliminan en el siguiente paso.
SELECT *
FROM typed
QUALIFY ROW_NUMBER() OVER (
PARTITION BY CAMPAIGN_ID, EVENT_DATE
ORDER BY UPDATED_AT DESC, ROW_ID DESC
) = 1
),

validated AS (
SELECT
l.*,
c.CAMPAIGN_ID IS NOT NULL AS has_valid_campaign,
COALESCE(
    l.IMPRESSIONS IS NOT NULL AND l.CLICKS IS NOT NULL AND l.SPEND_USD IS NOT NULL
    AND l.ATTRIBUTED_ORDERS IS NOT NULL AND l.ATTRIBUTED_SALES_USD IS NOT NULL, FALSE
) AS has_all_metrics,
COALESCE(
    l.IMPRESSIONS >= 0 AND l.CLICKS >= 0 AND l.SPEND_USD >= 0
    AND l.ATTRIBUTED_ORDERS >= 0 AND l.ATTRIBUTED_SALES_USD >= 0, FALSE
) AS has_non_negative_metrics,
COALESCE(l.CLICKS <= l.IMPRESSIONS, FALSE) AS clicks_le_impressions,
-- La vigencia incluye el día de inicio y el día de fin
COALESCE(l.EVENT_DATE BETWEEN c.START_DATE AND c.END_DATE, FALSE) AS in_campaign_dates
FROM latest_version l
LEFT JOIN CAMPAIGNS c
ON l.CAMPAIGN_ID = c.CAMPAIGN_ID
)

SELECT
ROW_ID,
CAMPAIGN_ID,
EVENT_DATE,
CAST(IMPRESSIONS AS BIGINT)        AS IMPRESSIONS,
CAST(CLICKS AS BIGINT)             AS CLICKS,
SPEND_USD,
CAST(ATTRIBUTED_ORDERS AS BIGINT)  AS ATTRIBUTED_ORDERS,
ATTRIBUTED_SALES_USD,
UPDATED_AT
FROM validated
WHERE has_valid_campaign
AND has_all_metrics
AND has_non_negative_metrics
AND clicks_le_impressions
AND in_campaign_dates
ORDER BY CAMPAIGN_ID, EVENT_DATE;


-- ---------------------------------------------------------------------
-- 3. CAMPAIGN_SUMMARY: una fila por campaña, con métricas y clasificación
--
-- Se parte de CAMPAIGNS (LEFT JOIN) para que las campañas sin días
-- válidos también aparezcan y puedan quedar como WITHOUT_DATA.
-- Las divisiones usan NULLIF para devolver NULL en vez de error cuando
-- el denominador es 0.
-- ---------------------------------------------------------------------
CREATE OR REPLACE TABLE CAMPAIGN_SUMMARY AS
WITH campaign_totals AS (
SELECT
CAMPAIGN_ID,
SUM(IMPRESSIONS)           AS IMPRESSIONS,
SUM(CLICKS)                AS CLICKS,
SUM(SPEND_USD)             AS SPEND_USD,
SUM(ATTRIBUTED_ORDERS)     AS ATTRIBUTED_ORDERS,
SUM(ATTRIBUTED_SALES_USD)  AS ATTRIBUTED_SALES_USD,
COUNT(*)                   AS VALID_DAYS,
MIN(EVENT_DATE)            AS FIRST_EVENT_DATE,
MAX(EVENT_DATE)            AS LAST_EVENT_DATE
FROM CAMPAIGN_DAILY_CLEAN
GROUP BY CAMPAIGN_ID
),

campaign_metrics AS (
SELECT
c.CAMPAIGN_ID,
c.COUNTRY,
c.MAKER,
c.TRADEMARK,
c.OBJECTIVE,
c.STATUS,
c.START_DATE,
c.END_DATE,
c.BUDGET_USD,
COALESCE(t.SPEND_USD, 0)             AS SPEND_USD,
COALESCE(t.ATTRIBUTED_SALES_USD, 0)  AS ATTRIBUTED_SALES_USD,
COALESCE(t.IMPRESSIONS, 0)           AS IMPRESSIONS,
COALESCE(t.CLICKS, 0)                AS CLICKS,
COALESCE(t.ATTRIBUTED_ORDERS, 0)     AS ATTRIBUTED_ORDERS,
COALESCE(t.VALID_DAYS, 0)            AS VALID_DAYS,
t.FIRST_EVENT_DATE,
t.LAST_EVENT_DATE,
tg.TARGET_CTR,
tg.TARGET_ROAS,
tg.TARGET_CPM
FROM CAMPAIGNS c
LEFT JOIN campaign_totals t
ON c.CAMPAIGN_ID = t.CAMPAIGN_ID
LEFT JOIN CAMPAIGN_TARGETS tg
ON c.CAMPAIGN_ID = tg.CAMPAIGN_ID
),

campaign_kpis AS (
SELECT
*,
CLICKS / NULLIF(IMPRESSIONS, 0)                AS CTR,
SPEND_USD / NULLIF(IMPRESSIONS, 0) * 1000      AS CPM,
ATTRIBUTED_SALES_USD / NULLIF(SPEND_USD, 0)    AS ROAS,
SPEND_USD / NULLIF(BUDGET_USD, 0)              AS BUDGET_CONSUMED_PCT,
-- Negativo cuando la campaña se pasó del presupuesto
BUDGET_USD - SPEND_USD                         AS REMAINING_BUDGET_USD
FROM campaign_metrics
)

-- Se redondea solo en la salida; la clasificación usa los valores sin redondear
SELECT
CAMPAIGN_ID,
COUNTRY,
MAKER,
TRADEMARK,
OBJECTIVE,
STATUS,
START_DATE,
END_DATE,
BUDGET_USD,
ROUND(SPEND_USD, 2)               AS SPEND_USD,
ROUND(ATTRIBUTED_SALES_USD, 2)    AS ATTRIBUTED_SALES_USD,
IMPRESSIONS,
CLICKS,
ATTRIBUTED_ORDERS,
VALID_DAYS,
FIRST_EVENT_DATE,
LAST_EVENT_DATE,
TARGET_CTR,
TARGET_ROAS,
TARGET_CPM,
ROUND(CTR, 6)                     AS CTR,
ROUND(CPM, 4)                     AS CPM,
ROUND(ROAS, 4)                    AS ROAS,
ROUND(BUDGET_CONSUMED_PCT, 4)     AS BUDGET_CONSUMED_PCT,
ROUND(REMAINING_BUDGET_USD, 2)    AS REMAINING_BUDGET_USD,
-- Las reglas se evalúan en el orden de prioridad del enunciado:
-- la primera que se cumple define la clasificación.
-- Si CTR o ROAS son NULL (sin impresiones o sin gasto) la comparación
-- no se cumple y la campaña no queda como AT_RISK.
CASE
WHEN STATUS = 'CANCELLED'                            THEN 'CANCELLED'
WHEN VALID_DAYS = 0                                  THEN 'WITHOUT_DATA'
WHEN TARGET_CTR IS NULL OR TARGET_ROAS IS NULL       THEN 'MISSING_TARGET'
WHEN SPEND_USD > BUDGET_USD                          THEN 'OVER_BUDGET'
WHEN CTR < TARGET_CTR AND ROAS < TARGET_ROAS         THEN 'AT_RISK'
ELSE 'ON_TRACK'
END AS CAMPAIGN_HEALTH
FROM campaign_kpis
ORDER BY CAMPAIGN_ID;


-----------------------------------------------------------------------
-- 4. CAMPAIGN_WEEKLY_SUMMARY: resumen semanal por país, maker y campaña
-- La semana empieza el lunes (comportamiento por defecto de DATE_TRUNC
-- en DuckDB y en Snowflake con WEEK_START = 0).
-----------------------------------------------------------------------
CREATE OR REPLACE TABLE CAMPAIGN_WEEKLY_SUMMARY AS
WITH weekly AS (
SELECT
c.COUNTRY,
c.MAKER,
d.CAMPAIGN_ID,
CAST(DATE_TRUNC('week', d.EVENT_DATE) AS DATE)  AS WEEK_START,
SUM(d.IMPRESSIONS)            AS IMPRESSIONS,
SUM(d.CLICKS)                 AS CLICKS,
ROUND(SUM(d.SPEND_USD), 2)              AS SPEND_USD,
SUM(d.ATTRIBUTED_ORDERS)                AS ATTRIBUTED_ORDERS,
ROUND(SUM(d.ATTRIBUTED_SALES_USD), 2)   AS ATTRIBUTED_SALES_USD,
COUNT(*)                                AS VALID_DAYS
FROM CAMPAIGN_DAILY_CLEAN d
INNER JOIN CAMPAIGNS c
ON d.CAMPAIGN_ID = c.CAMPAIGN_ID
GROUP BY c.COUNTRY, c.MAKER, d.CAMPAIGN_ID, CAST(DATE_TRUNC('week', d.EVENT_DATE) AS DATE)
)

SELECT
*,
ROUND(CLICKS / NULLIF(IMPRESSIONS, 0), 6)              AS CTR,
ROUND(SPEND_USD / NULLIF(IMPRESSIONS, 0) * 1000, 4)    AS CPM,
ROUND(ATTRIBUTED_SALES_USD / NULLIF(SPEND_USD, 0), 4)  AS ROAS
FROM weekly
ORDER BY COUNTRY, MAKER, CAMPAIGN_ID, WEEK_START;


-----------------------------------------------------------------------
-- 5. CAMPAIGN_PRIORITY (adicional, no lo pide el enunciado)
-- Ordena las campañas según qué tan urgente es actuar sobre ellas.
--
-- Fecha de corte (AS_OF_DATE): último EVENT_DATE de la tabla limpia.
-- Solo se consideran accionables las campañas ACTIVE cuya fecha de fin
-- no ha pasado; las demás ya no se pueden corregir.
--
-- PRIORITY_SCORE (0 a 100) combina tres señales:
--   40% brecha de ROAS contra la meta    (1 - ROAS / TARGET_ROAS)
--   20% brecha de CTR contra la meta     (1 - CTR / TARGET_CTR)
--   40% sobre-ritmo de gasto (pacing)    % presupuesto / % tiempo - 1
-- Cada señal se limita entre 0 y 1. Una campaña activa sin datos
-- válidos recibe 100 porque no se puede medir.
-----------------------------------------------------------------------
CREATE OR REPLACE TABLE CAMPAIGN_PRIORITY AS
WITH as_of AS (
SELECT MAX(EVENT_DATE) AS AS_OF_DATE
FROM CAMPAIGN_DAILY_CLEAN
),

base AS (
SELECT
s.CAMPAIGN_ID,
s.COUNTRY,
s.MAKER,
s.TRADEMARK,
s.OBJECTIVE,
s.STATUS,
s.CAMPAIGN_HEALTH,
s.START_DATE,
s.END_DATE,
a.AS_OF_DATE,
s.BUDGET_CONSUMED_PCT,
s.ROAS,
s.TARGET_ROAS,
s.CTR,
s.TARGET_CTR,
GREATEST(DATEDIFF('day', a.AS_OF_DATE, s.END_DATE), 0) AS DAYS_LEFT,
-- % del tiempo de la campaña transcurrido a la fecha de corte
LEAST(
GREATEST(DATEDIFF('day', s.START_DATE, a.AS_OF_DATE) + 1, 0)
/ NULLIF(DATEDIFF('day', s.START_DATE, s.END_DATE) + 1, 0),
1
) AS TIME_ELAPSED_PCT
FROM CAMPAIGN_SUMMARY s
CROSS JOIN as_of a
),

signals AS (
SELECT
*,
STATUS = 'ACTIVE' AND END_DATE > AS_OF_DATE                          AS IS_ACTIONABLE,
STATUS = 'ACTIVE' AND END_DATE <= AS_OF_DATE                         AS STATUS_OUTDATED,
BUDGET_CONSUMED_PCT / NULLIF(TIME_ELAPSED_PCT, 0)                    AS PACING_INDEX,
LEAST(GREATEST(1 - ROAS / NULLIF(TARGET_ROAS, 0), 0), 1)             AS ROAS_GAP,
LEAST(GREATEST(1 - CTR / NULLIF(TARGET_CTR, 0), 0), 1)               AS CTR_GAP
FROM base
)

SELECT
CAMPAIGN_ID,
COUNTRY,
MAKER,
TRADEMARK,
OBJECTIVE,
STATUS,
CAMPAIGN_HEALTH,
END_DATE,
AS_OF_DATE,
DAYS_LEFT,
IS_ACTIONABLE,
STATUS_OUTDATED,
ROUND(TIME_ELAPSED_PCT, 4)   AS TIME_ELAPSED_PCT,
ROUND(PACING_INDEX, 4)       AS PACING_INDEX,
ROUND(ROAS_GAP, 4)           AS ROAS_GAP,
ROUND(CTR_GAP, 4)            AS CTR_GAP,
CASE
WHEN NOT IS_ACTIONABLE THEN NULL
WHEN CAMPAIGN_HEALTH = 'WITHOUT_DATA' THEN 100
ELSE ROUND(100 * (
0.4 * COALESCE(ROAS_GAP, 0)
+ 0.2 * COALESCE(CTR_GAP, 0)
+ 0.4 * LEAST(GREATEST(COALESCE(PACING_INDEX, 0) - 1, 0), 1)
), 1)
END AS PRIORITY_SCORE,
-- Motivos en texto para mostrar en el dashboard y usar en el agente
CONCAT_WS('; ',
CASE WHEN CAMPAIGN_HEALTH = 'WITHOUT_DATA' AND STATUS = 'ACTIVE' THEN 'Activa sin datos válidos' END,
CASE WHEN CAMPAIGN_HEALTH = 'MISSING_TARGET' THEN 'Sin meta de CTR o ROAS' END,
CASE WHEN CAMPAIGN_HEALTH = 'OVER_BUDGET' THEN 'Gasto mayor al presupuesto' END,
CASE WHEN ROAS_GAP > 0 THEN 'ROAS ' || CAST(ROUND(ROAS, 2) AS VARCHAR) || ' vs meta ' || CAST(ROUND(TARGET_ROAS, 2) AS VARCHAR) END,
CASE WHEN CTR_GAP > 0 THEN 'CTR ' || CAST(ROUND(CTR * 100, 2) AS VARCHAR) || '% vs meta ' || CAST(ROUND(TARGET_CTR * 100, 2) AS VARCHAR) || '%' END,
CASE WHEN PACING_INDEX > 1.1 THEN 'Gasta más rápido de lo previsto (' || CAST(ROUND(BUDGET_CONSUMED_PCT * 100) AS VARCHAR) || '% del presupuesto con ' || CAST(ROUND(TIME_ELAPSED_PCT * 100) AS VARCHAR) || '% del tiempo)' END,
CASE WHEN STATUS_OUTDATED THEN 'Figura ACTIVE pero terminó el ' || CAST(END_DATE AS VARCHAR) END
) AS PRIORITY_REASON
FROM signals
ORDER BY PRIORITY_SCORE DESC NULLS LAST, CAMPAIGN_ID;


