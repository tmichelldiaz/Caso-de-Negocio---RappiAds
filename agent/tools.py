"""
Herramientas del agente. Cada una consulta las tablas de outputs/ con DuckDB,
así el agente responde con los mismos números que muestra el dashboard.
"""
import json
import threading
from pathlib import Path
from typing import Optional

import duckdb
from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"

TABLES = [
    "CAMPAIGN_DAILY_CLEAN",
    "CAMPAIGN_SUMMARY",
    "CAMPAIGN_WEEKLY_SUMMARY",
    "CAMPAIGN_PRIORITY",
    "DATA_QUALITY_REPORT",
]

_con = None
_lock = threading.Lock()


def get_connection():
    """Carga los CSV una sola vez en una base DuckDB en memoria."""
    global _con
    with _lock:
        if _con is None:
            con = duckdb.connect()
            for table in TABLES:
                path = OUTPUTS / f"{table}.csv"
                if not path.exists():
                    raise FileNotFoundError(f"Falta {path}. Corre primero sql/run_sql.py y python/analysis.py")
                con.execute(f"CREATE TABLE {table} AS SELECT * FROM read_csv_auto('{path.as_posix()}')")
            # Resultados de sql/insights.sql (pestaña Insights)
            for path in sorted((OUTPUTS / "insights").glob("INSIGHT_*.csv")):
                con.execute(f"CREATE TABLE {path.stem} AS SELECT * FROM read_csv_auto('{path.as_posix()}')")
            _con = con
    return _con.cursor()


def query(sql, params=None):
    cur = get_connection()
    result = cur.execute(sql, params or [])
    columns = [c[0] for c in result.description]
    rows = []
    for row in result.fetchall():
        item = {}
        for col, value in zip(columns, row):
            item[col] = round(value, 4) if isinstance(value, float) else value
        rows.append(item)
    return rows


def to_json(data):
    return json.dumps(data, ensure_ascii=False, default=str)


def campaign_filter(country=None, maker=None, trademark=None, health=None, alias="s"):
    """Arma el WHERE para filtrar campañas, siempre con parámetros."""
    conditions, params = [], []
    for column, value in [("COUNTRY", country), ("MAKER", maker), ("TRADEMARK", trademark), ("CAMPAIGN_HEALTH", health)]:
        if value:
            conditions.append(f"{alias}.{column} = ?")
            params.append(value)
    return (" AND ".join(conditions) or "TRUE"), params


@tool
def resumen_campanas(
    country: Optional[str] = None,
    maker: Optional[str] = None,
    trademark: Optional[str] = None,
    health: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> str:
    """Indicadores generales (presupuesto, inversión, ventas, ROAS, CTR, CPM, % consumido) y cantidad
    de campañas por estado de salud. Acepta filtros opcionales: country (código como 'MX'), maker,
    trademark, health (ON_TRACK, AT_RISK, OVER_BUDGET, MISSING_TARGET, WITHOUT_DATA, CANCELLED)
    y rango de fechas date_from / date_to en formato YYYY-MM-DD."""
    where, params = campaign_filter(country, maker, trademark, health)
    date_from = date_from or "1900-01-01"
    date_to = date_to or "2100-01-01"

    kpis = query(f"""
        WITH selected AS (SELECT * FROM CAMPAIGN_SUMMARY s WHERE {where}),
        daily AS (
            SELECT d.* FROM CAMPAIGN_DAILY_CLEAN d
            JOIN selected s ON d.CAMPAIGN_ID = s.CAMPAIGN_ID
            WHERE d.EVENT_DATE BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        )
        SELECT
            (SELECT COUNT(*) FROM selected)               AS CAMPAIGNS,
            (SELECT SUM(BUDGET_USD) FROM selected)        AS BUDGET_USD,
            SUM(SPEND_USD)                                AS SPEND_USD,
            SUM(ATTRIBUTED_SALES_USD)                     AS SALES_USD,
            SUM(ATTRIBUTED_ORDERS)                        AS ORDERS,
            SUM(ATTRIBUTED_SALES_USD) / NULLIF(SUM(SPEND_USD), 0)          AS ROAS,
            SUM(CLICKS) / NULLIF(SUM(IMPRESSIONS), 0)                      AS CTR,
            SUM(SPEND_USD) / NULLIF(SUM(IMPRESSIONS), 0) * 1000            AS CPM,
            SUM(SPEND_USD) / NULLIF((SELECT SUM(BUDGET_USD) FROM selected), 0) AS BUDGET_CONSUMED_PCT
        FROM daily
    """, params + [date_from, date_to])

    by_health = query(f"""
        SELECT CAMPAIGN_HEALTH, COUNT(*) AS CAMPAIGNS, SUM(SPEND_USD) AS SPEND_USD
        FROM CAMPAIGN_SUMMARY s WHERE {where}
        GROUP BY CAMPAIGN_HEALTH ORDER BY CAMPAIGNS DESC
    """, params)

    return to_json({"kpis": kpis[0], "campaigns_by_health": by_health,
                    "note": "El estado de salud se calcula con toda la vida de la campaña, no con el rango de fechas."})


@tool
def campanas_prioritarias(top_n: int = 5, country: Optional[str] = None, maker: Optional[str] = None) -> str:
    """Lista de campañas ACTIVAS que todavía se pueden corregir, ordenadas por PRIORITY_SCORE (0-100).
    Incluye los motivos (brecha de ROAS, CTR, ritmo de gasto) y los días que le quedan.
    Filtros opcionales: country, maker."""
    where, params = campaign_filter(country, maker, alias="p")
    top_n = max(1, min(int(top_n), 20))
    rows = query(f"""
        SELECT p.CAMPAIGN_ID, p.COUNTRY, p.MAKER, p.TRADEMARK, p.OBJECTIVE, p.CAMPAIGN_HEALTH,
               p.PRIORITY_SCORE, p.PRIORITY_REASON, p.DAYS_LEFT, p.PACING_INDEX,
               s.BUDGET_USD, s.SPEND_USD, s.BUDGET_CONSUMED_PCT, s.ROAS, s.TARGET_ROAS, s.CTR, s.TARGET_CTR
        FROM CAMPAIGN_PRIORITY p
        JOIN CAMPAIGN_SUMMARY s ON p.CAMPAIGN_ID = s.CAMPAIGN_ID
        WHERE p.IS_ACTIONABLE AND p.PRIORITY_SCORE > 0 AND {where}
        ORDER BY p.PRIORITY_SCORE DESC
        LIMIT {top_n}
    """, params)
    return to_json({
        "campaigns": rows,
        "how_score_works": "40% brecha de ROAS + 20% brecha de CTR + 40% sobre-ritmo de gasto. "
                           "Activa sin datos = 100. PACING_INDEX < 1 significa que gasta más lento de lo previsto.",
    })


@tool
def detalle_campana(campaign_id: str) -> str:
    """Toda la información de una campaña (por ejemplo 'CMP-0046'): atributos, métricas totales,
    metas, clasificación, puntaje de prioridad con sus motivos y la evolución semanal."""
    campaign_id = campaign_id.strip().upper()
    summary = query("SELECT * FROM CAMPAIGN_SUMMARY WHERE CAMPAIGN_ID = ?", [campaign_id])
    if not summary:
        return to_json({"error": f"No existe la campaña {campaign_id}"})
    priority = query("""
        SELECT PRIORITY_SCORE, PRIORITY_REASON, IS_ACTIONABLE, STATUS_OUTDATED, DAYS_LEFT,
               TIME_ELAPSED_PCT, PACING_INDEX, AS_OF_DATE
        FROM CAMPAIGN_PRIORITY WHERE CAMPAIGN_ID = ?
    """, [campaign_id])
    weekly = query("""
        SELECT WEEK_START, SPEND_USD, ATTRIBUTED_SALES_USD, ROAS, CTR, VALID_DAYS
        FROM CAMPAIGN_WEEKLY_SUMMARY WHERE CAMPAIGN_ID = ? ORDER BY WEEK_START
    """, [campaign_id])
    return to_json({"summary": summary[0], "priority": priority[0], "weekly_trend": weekly})


@tool
def comparar_grupos(
    dimension: str = "COUNTRY",
    metric: str = "ROAS",
    country: Optional[str] = None,
    health: Optional[str] = None,
) -> str:
    """Compara grupos de campañas contra sus metas. dimension puede ser COUNTRY, MAKER, TRADEMARK u OBJECTIVE.
    metric define el orden (de peor a mejor frente a la meta): ROAS, CTR o CPM.
    Devuelve por grupo: campañas, objetivo, inversión, ventas, ROAS, CTR y CPM, cada uno con su meta
    ponderada y su relación contra la meta, y cuántas campañas están AT_RISK u OVER_BUDGET.
    Filtros opcionales: country y health."""
    dimension = dimension.strip().upper()
    metric = metric.strip().upper()
    if dimension not in {"COUNTRY", "MAKER", "TRADEMARK", "OBJECTIVE"}:
        return to_json({"error": "dimension debe ser COUNTRY, MAKER, TRADEMARK u OBJECTIVE"})
    if metric not in {"ROAS", "CTR", "CPM"}:
        return to_json({"error": "metric debe ser ROAS, CTR o CPM"})
    # En ROAS y CTR estar bajo la meta es malo; en CPM (un costo) lo malo es estar por encima
    order_by = {"ROAS": "ROAS_VS_TARGET ASC", "CTR": "CTR_VS_TARGET ASC", "CPM": "CPM_VS_TARGET DESC"}[metric]
    where, params = campaign_filter(country=country, health=health)
    rows = query(f"""
        WITH grouped AS (
            SELECT
                s.{dimension} AS GROUP_NAME,
                STRING_AGG(DISTINCT s.OBJECTIVE, ', ') AS OBJECTIVES,
                COUNT(*) AS TOTAL_CAMPAIGNS,
                COUNT(*) FILTER (WHERE s.STATUS = 'ACTIVE') AS ACTIVE_CAMPAIGNS,
                SUM(s.SPEND_USD) AS SPEND_USD,
                SUM(s.ATTRIBUTED_SALES_USD) AS SALES_USD,
                SUM(s.ATTRIBUTED_SALES_USD) / NULLIF(SUM(s.SPEND_USD), 0) AS ROAS,
                SUM(s.TARGET_ROAS * s.SPEND_USD) / NULLIF(SUM(CASE WHEN s.TARGET_ROAS IS NOT NULL THEN s.SPEND_USD END), 0) AS TARGET_ROAS_WEIGHTED,
                SUM(s.CLICKS) / NULLIF(SUM(s.IMPRESSIONS), 0) AS CTR,
                SUM(s.TARGET_CTR * s.IMPRESSIONS) / NULLIF(SUM(CASE WHEN s.TARGET_CTR IS NOT NULL THEN s.IMPRESSIONS END), 0) AS TARGET_CTR_WEIGHTED,
                SUM(s.SPEND_USD) / NULLIF(SUM(s.IMPRESSIONS), 0) * 1000 AS CPM,
                SUM(s.TARGET_CPM * s.IMPRESSIONS) / NULLIF(SUM(CASE WHEN s.TARGET_CPM IS NOT NULL THEN s.IMPRESSIONS END), 0) AS TARGET_CPM_WEIGHTED,
                COUNT(*) FILTER (WHERE s.CAMPAIGN_HEALTH = 'AT_RISK') AS AT_RISK,
                COUNT(*) FILTER (WHERE s.CAMPAIGN_HEALTH = 'OVER_BUDGET') AS OVER_BUDGET
            FROM CAMPAIGN_SUMMARY s
            WHERE {where}
            GROUP BY s.{dimension}
        )
        -- *_VS_TARGET = valor real / meta (1 = exactamente en la meta)
        SELECT
            *,
            ROAS / NULLIF(TARGET_ROAS_WEIGHTED, 0) AS ROAS_VS_TARGET,
            CTR / NULLIF(TARGET_CTR_WEIGHTED, 0)   AS CTR_VS_TARGET,
            CPM / NULLIF(TARGET_CPM_WEIGHTED, 0)   AS CPM_VS_TARGET
        FROM grouped
        ORDER BY {order_by} NULLS LAST
    """, params)
    return to_json({
        "dimension": dimension,
        "ordered_by": metric,
        "groups": rows,
        "note": "Los grupos vienen de peor a mejor frente a la meta de la métrica pedida. "
                "ROAS y CTR: VS_TARGET < 1 es malo. CPM es un costo: CPM_VS_TARGET > 1 significa que paga más de lo pactado. "
                "Un ROAS bajo en absoluto puede ser normal si el objetivo es AWARENESS.",
    })


@tool
def reporte_calidad() -> str:
    """Resultado de las validaciones de calidad de datos: tipo de problema, registros afectados,
    porcentaje y ROW_ID de ejemplo. También cuántos registros quedaron en la tabla limpia."""
    checks = query("SELECT * FROM DATA_QUALITY_REPORT")
    clean = query("SELECT COUNT(*) AS CLEAN_ROWS FROM CAMPAIGN_DAILY_CLEAN")[0]
    return to_json({"checks": checks, "raw_rows": checks[0]["TOTAL_ROWS"] if checks else None, **clean})


INSIGHT_TABLES = {
    1: ["INSIGHT_1_BY_COUNTRY"],
    2: ["INSIGHT_2_FAILURE_TYPE"],
    3: ["INSIGHT_3_BUDGET", "INSIGHT_3_OVER_BUDGET"],
    4: ["INSIGHT_4_MAKERS"],
    5: ["INSIGHT_5_URGENT"],
}


@tool
def resultados_insights(numero: int) -> str:
    """Resultados de las 5 preguntas de la pestaña Insights (numero de 1 a 5):
    1 = dónde se concentra el bajo rendimiento frente a la meta (por país);
    2 = si el problema es de clics, de ventas o de ambos;
    3 = si el presupuesto se ejecuta como se contrató (incluye detalle de sobregiros);
    4 = qué makers concentran la inversión en riesgo;
    5 = qué campañas requieren atención inmediata."""
    tables = INSIGHT_TABLES.get(int(numero))
    if not tables:
        return to_json({"error": "numero debe estar entre 1 y 5"})
    return to_json({table: query(f"SELECT * FROM {table}") for table in tables})


TOOLS = [resumen_campanas, campanas_prioritarias, detalle_campana, comparar_grupos, reporte_calidad, resultados_insights]
