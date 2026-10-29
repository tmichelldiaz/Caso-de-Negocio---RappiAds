-- =====================================================================
-- Prueba técnica Rappi Ads - Parte 4 (consultas de análisis)
-- Se ejecuta después de solution.sql, sobre las tablas que este crea.
-- Cada consulta responde una pregunta de negocio y su resultado se
-- muestra en la pestaña Insights del dashboard.
--
-- Criterio común: las campañas CANCELLED se excluyen del análisis de
-- rendimiento porque no reflejan cómo funciona una campaña completa.
-- =====================================================================


-----------------------------------------------------------------------
-- P1. ¿Dónde se concentra el bajo rendimiento frente a la meta?
-- Se compara contra la meta y no en absoluto, porque en estos datos cada
-- país tiene un solo objetivo y las metas cambian mucho por objetivo.
-- Las metas se ponderan: ROAS por inversión, CTR por impresiones.
-----------------------------------------------------------------------
CREATE OR REPLACE TABLE INSIGHT_1_BY_COUNTRY AS
WITH by_country AS (
SELECT
COUNTRY,
STRING_AGG(DISTINCT OBJECTIVE, ', ')                                     AS OBJECTIVE,
COUNT(*)                                                                 AS CAMPAIGNS,
COUNT(*) FILTER (WHERE CAMPAIGN_HEALTH = 'AT_RISK')                      AS AT_RISK_CAMPAIGNS,
SUM(SPEND_USD)                                                           AS SPEND_USD,
SUM(CASE WHEN CAMPAIGN_HEALTH = 'AT_RISK' THEN SPEND_USD ELSE 0 END)     AS AT_RISK_SPEND_USD,
SUM(ATTRIBUTED_SALES_USD) / NULLIF(SUM(SPEND_USD), 0)                    AS ROAS,
SUM(TARGET_ROAS * SPEND_USD)
/ NULLIF(SUM(CASE WHEN TARGET_ROAS IS NOT NULL THEN SPEND_USD END), 0)   AS TARGET_ROAS,
SUM(CLICKS) / NULLIF(SUM(IMPRESSIONS), 0)                                AS CTR,
SUM(TARGET_CTR * IMPRESSIONS)
/ NULLIF(SUM(CASE WHEN TARGET_CTR IS NOT NULL THEN IMPRESSIONS END), 0)  AS TARGET_CTR
FROM CAMPAIGN_SUMMARY
WHERE STATUS <> 'CANCELLED'
GROUP BY COUNTRY
)

SELECT
COUNTRY,
OBJECTIVE,
CAMPAIGNS,
AT_RISK_CAMPAIGNS,
ROUND(SPEND_USD, 2)                                AS SPEND_USD,
ROUND(AT_RISK_SPEND_USD / NULLIF(SPEND_USD, 0), 4) AS AT_RISK_SPEND_PCT,
ROUND(ROAS, 4)                                     AS ROAS,
ROUND(TARGET_ROAS, 4)                              AS TARGET_ROAS,
ROUND(ROAS / NULLIF(TARGET_ROAS, 0), 4)            AS ROAS_VS_TARGET,
ROUND(CTR, 6)                                      AS CTR,
ROUND(TARGET_CTR, 6)                               AS TARGET_CTR,
ROUND(CTR / NULLIF(TARGET_CTR, 0), 4)              AS CTR_VS_TARGET
FROM by_country
ORDER BY ROAS_VS_TARGET;


-----------------------------------------------------------------------
-- P2. ¿El problema es de clics, de ventas o de ambos?
-- AT_RISK solo marca las campañas que fallan CTR y ROAS a la vez. Aquí se
-- separan las que fallan solo una, que la clasificación no muestra.
-- Solo campañas con días válidos y con ambas metas.
-----------------------------------------------------------------------
CREATE OR REPLACE TABLE INSIGHT_2_FAILURE_TYPE AS
WITH evaluated AS (
SELECT
OBJECTIVE,
SPEND_USD,
CASE
WHEN CTR < TARGET_CTR AND ROAS < TARGET_ROAS THEN 'Falla CTR y ROAS'
WHEN CTR < TARGET_CTR                        THEN 'Solo falla CTR'
WHEN ROAS < TARGET_ROAS                      THEN 'Solo falla ROAS'
ELSE 'Cumple ambas metas'
END AS FAILURE_TYPE
FROM CAMPAIGN_SUMMARY
WHERE STATUS <> 'CANCELLED'
AND VALID_DAYS > 0
AND TARGET_CTR IS NOT NULL
AND TARGET_ROAS IS NOT NULL
)

SELECT
FAILURE_TYPE,
COUNT(*)                                                    AS CAMPAIGNS,
ROUND(COUNT(*) / SUM(COUNT(*)) OVER (), 4)                  AS CAMPAIGNS_PCT,
ROUND(SUM(SPEND_USD), 2)                                    AS SPEND_USD,
ROUND(SUM(SPEND_USD) / SUM(SUM(SPEND_USD)) OVER (), 4)      AS SPEND_PCT,
COUNT(*) FILTER (WHERE OBJECTIVE = 'AWARENESS')             AS AWARENESS,
COUNT(*) FILTER (WHERE OBJECTIVE = 'TRAFFIC')               AS TRAFFIC,
COUNT(*) FILTER (WHERE OBJECTIVE = 'CONVERSION')            AS CONVERSION
FROM evaluated
GROUP BY FAILURE_TYPE
ORDER BY CASE FAILURE_TYPE
WHEN 'Falla CTR y ROAS' THEN 1
WHEN 'Solo falla ROAS' THEN 2
WHEN 'Solo falla CTR' THEN 3
ELSE 4
END;


-----------------------------------------------------------------------
-- P3. ¿Se ejecuta el presupuesto como se contrató?
-- Se separan las campañas terminadas (ya no hay nada que corregir) de las
-- activas vigentes (todavía se puede ajustar el ritmo de gasto).
-- PACING_INDEX promedio: 1 = gasta al ritmo esperado, < 1 = más lento.
-----------------------------------------------------------------------
CREATE OR REPLACE TABLE INSIGHT_3_BUDGET AS
SELECT
CASE
WHEN p.IS_ACTIONABLE THEN 'Activas vigentes'
WHEN s.STATUS = 'ACTIVE' THEN 'Activas vencidas'
ELSE 'Terminadas'
END                                                                   AS CAMPAIGN_GROUP,
COUNT(*)                                                              AS CAMPAIGNS,
ROUND(SUM(s.BUDGET_USD), 2)                                           AS BUDGET_USD,
ROUND(SUM(s.SPEND_USD), 2)                                            AS SPEND_USD,
ROUND(SUM(GREATEST(s.BUDGET_USD - s.SPEND_USD, 0)), 2)                AS UNSPENT_BUDGET_USD,
ROUND(SUM(s.SPEND_USD) / NULLIF(SUM(s.BUDGET_USD), 0), 4)             AS BUDGET_CONSUMED_PCT,
COUNT(*) FILTER (WHERE s.CAMPAIGN_HEALTH = 'OVER_BUDGET')             AS OVER_BUDGET_CAMPAIGNS,
ROUND(AVG(p.PACING_INDEX) FILTER (WHERE p.IS_ACTIONABLE AND s.VALID_DAYS > 0), 4) AS AVG_PACING_INDEX
FROM CAMPAIGN_SUMMARY s
JOIN CAMPAIGN_PRIORITY p
ON s.CAMPAIGN_ID = p.CAMPAIGN_ID
WHERE s.STATUS <> 'CANCELLED'
GROUP BY 1
ORDER BY 1;

-- Detalle de las campañas que se pasaron del presupuesto
CREATE OR REPLACE TABLE INSIGHT_3_OVER_BUDGET AS
SELECT
CAMPAIGN_ID,
COUNTRY,
MAKER,
STATUS,
END_DATE,
BUDGET_USD,
SPEND_USD,
BUDGET_CONSUMED_PCT,
ROUND(SPEND_USD - BUDGET_USD, 2) AS OVERSPEND_USD
FROM CAMPAIGN_SUMMARY
WHERE CAMPAIGN_HEALTH = 'OVER_BUDGET'
ORDER BY OVERSPEND_USD DESC;


-----------------------------------------------------------------------
-- P4. ¿Qué makers concentran la inversión en riesgo?
-- "Inversión en riesgo" = inversión en campañas AT_RISK u OVER_BUDGET.
-- Es el dinero donde el anunciante tiene más motivos para no renovar.
-----------------------------------------------------------------------
CREATE OR REPLACE TABLE INSIGHT_4_MAKERS AS
WITH by_maker AS (
SELECT
MAKER,
COUNT(*)                                                                  AS CAMPAIGNS,
COUNT(*) FILTER (WHERE CAMPAIGN_HEALTH IN ('AT_RISK', 'OVER_BUDGET'))     AS RISK_CAMPAIGNS,
COUNT(*) FILTER (WHERE STATUS = 'ACTIVE')                                 AS ACTIVE_CAMPAIGNS,
SUM(SPEND_USD)                                                            AS SPEND_USD,
SUM(CASE WHEN CAMPAIGN_HEALTH IN ('AT_RISK', 'OVER_BUDGET') THEN SPEND_USD ELSE 0 END) AS RISK_SPEND_USD,
SUM(ATTRIBUTED_SALES_USD) / NULLIF(SUM(SPEND_USD), 0)                     AS ROAS
FROM CAMPAIGN_SUMMARY
WHERE STATUS <> 'CANCELLED'
GROUP BY MAKER
)

SELECT
MAKER,
CAMPAIGNS,
RISK_CAMPAIGNS,
ACTIVE_CAMPAIGNS,
ROUND(SPEND_USD, 2)                                       AS SPEND_USD,
ROUND(RISK_SPEND_USD, 2)                                  AS RISK_SPEND_USD,
ROUND(RISK_SPEND_USD / NULLIF(SPEND_USD, 0), 4)           AS RISK_SPEND_PCT,
-- Participación del maker en toda la inversión en riesgo
ROUND(RISK_SPEND_USD / NULLIF(SUM(RISK_SPEND_USD) OVER (), 0), 4) AS SHARE_OF_TOTAL_RISK,
ROUND(ROAS, 4)                                            AS ROAS
FROM by_maker
ORDER BY RISK_SPEND_USD DESC;


-----------------------------------------------------------------------
-- P5. ¿Qué campañas requieren atención inmediata y por qué?
-- Campañas activas que aún no terminan, ordenadas por PRIORITY_SCORE.
-- Se excluyen las de puntaje 0 (van bien).
-----------------------------------------------------------------------
CREATE OR REPLACE TABLE INSIGHT_5_URGENT AS
SELECT
p.CAMPAIGN_ID,
p.COUNTRY,
p.MAKER,
p.OBJECTIVE,
p.CAMPAIGN_HEALTH,
p.PRIORITY_SCORE,
p.DAYS_LEFT,
s.BUDGET_USD,
s.SPEND_USD,
s.REMAINING_BUDGET_USD,
s.ROAS,
s.TARGET_ROAS,
s.CTR,
s.TARGET_CTR,
p.PACING_INDEX,
p.PRIORITY_REASON
FROM CAMPAIGN_PRIORITY p
JOIN CAMPAIGN_SUMMARY s
ON p.CAMPAIGN_ID = s.CAMPAIGN_ID
WHERE p.IS_ACTIONABLE
AND p.PRIORITY_SCORE > 0
ORDER BY p.PRIORITY_SCORE DESC, p.DAYS_LEFT
LIMIT 10;
