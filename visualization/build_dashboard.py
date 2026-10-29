"""
Genera visualization/dashboard.html a partir de los CSV de outputs/.

Los datos se incrustan como JSON dentro del HTML para que el archivo
se pueda abrir con doble clic, sin servidor.

Uso (desde la carpeta raíz del proyecto, después de correr sql/run_sql.py
y python/analysis.py):
    python visualization/build_dashboard.py
"""
import base64
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
OUTPUTS = ROOT / "outputs"
INSIGHTS_DIR = OUTPUTS / "insights"
TEMPLATE = ROOT / "visualization" / "dashboard_template.html"
DASHBOARD = ROOT / "visualization" / "dashboard.html"
ASSETS = ROOT / "visualization" / "assets"
CHARTJS_CDN = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
LOGO_TYPES = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}

CAMPAIGN_COLUMNS = [
    "CAMPAIGN_ID", "COUNTRY", "MAKER", "TRADEMARK", "OBJECTIVE", "STATUS",
    "START_DATE", "END_DATE", "BUDGET_USD", "TARGET_CTR", "TARGET_ROAS", "TARGET_CPM", "CAMPAIGN_HEALTH",
]
PRIORITY_COLUMNS = ["CAMPAIGN_ID", "IS_ACTIONABLE", "DAYS_LEFT", "PRIORITY_SCORE", "PRIORITY_REASON"]


def read_output(name):
    path = OUTPUTS / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"Falta {path}. Corre primero sql/run_sql.py y python/analysis.py")
    return pd.read_csv(path)


def to_records(df):
    # NaN no es JSON válido; se reemplaza por None (null)
    return json.loads(df.to_json(orient="records"))


def read_insights():
    """Resultados de sql/insights.sql: un CSV por tabla INSIGHT_*."""
    files = sorted(INSIGHTS_DIR.glob("INSIGHT_*.csv"))
    if not files:
        raise FileNotFoundError(f"No hay resultados en {INSIGHTS_DIR}. Corre primero sql/run_sql.py")
    return {f.stem: to_records(pd.read_csv(f)) for f in files}


def main():
    summary = read_output("CAMPAIGN_SUMMARY")
    priority = read_output("CAMPAIGN_PRIORITY")
    daily = read_output("CAMPAIGN_DAILY_CLEAN")
    raw_rows = len(pd.read_csv(ROOT / "data" / "DAILY_PERFORMANCE.csv"))

    campaigns = summary[CAMPAIGN_COLUMNS].merge(priority[PRIORITY_COLUMNS], on="CAMPAIGN_ID", how="left")
    campaigns = campaigns.sort_values("CAMPAIGN_ID").reset_index(drop=True)

    # El detalle diario va como arreglos compactos para que el HTML pese menos:
    # [índice de campaña, índice de fecha, impresiones, clics, gasto, órdenes, ventas]
    campaign_index = {cid: i for i, cid in enumerate(campaigns["CAMPAIGN_ID"])}
    dates = sorted(daily["EVENT_DATE"].unique())
    date_index = {d: i for i, d in enumerate(dates)}
    daily_rows = [
        [
            campaign_index[r.CAMPAIGN_ID], date_index[r.EVENT_DATE], int(r.IMPRESSIONS), int(r.CLICKS),
            round(r.SPEND_USD, 2), int(r.ATTRIBUTED_ORDERS), round(r.ATTRIBUTED_SALES_USD, 2),
        ]
        for r in daily.itertuples()
    ]

    payload = {
        "meta": {
            "max_updated_at": daily["UPDATED_AT"].max(),
            "as_of_date": priority["AS_OF_DATE"].iloc[0],
            "raw_rows": raw_rows,
            "clean_rows": len(daily),
        },
        "campaigns": to_records(campaigns),
        "dates": dates,
        "daily": daily_rows,
        "insights": read_insights(),
    }

    html = TEMPLATE.read_text(encoding="utf-8")
    if "/*__DATA__*/null" not in html:
        raise ValueError("La plantilla no tiene el marcador /*__DATA__*/null")
    html = html.replace("/*__DATA__*/null", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    # El logo se incrusta en base64 para que el HTML siga siendo un solo archivo.
    # Si no está, el encabezado muestra el nombre en texto.
    logo = next((ASSETS / f"rappi_ads_logo{ext}" for ext in LOGO_TYPES if (ASSETS / f"rappi_ads_logo{ext}").exists()), None)
    if logo:
        logo_uri = f"data:{LOGO_TYPES[logo.suffix]};base64," + base64.b64encode(logo.read_bytes()).decode()
        html = html.replace("__LOGO_SRC__", logo_uri)
    else:
        print("Aviso: no se encontró visualization/assets/rappi_ads_logo.*, se usa el nombre en texto")
        html = html.replace("__LOGO_SRC__", "")
    # Chart.js también va incrustado para que el dashboard funcione sin internet.
    # Si no está la copia local, se usa el CDN.
    chartjs = ASSETS / "chart.umd.min.js"
    if chartjs.exists():
        html = html.replace("<!--__CHARTJS__-->", "<script>" + chartjs.read_text(encoding="utf-8") + "</script>")
    else:
        html = html.replace("<!--__CHARTJS__-->", f'<script src="{CHARTJS_CDN}"></script>')

    DASHBOARD.write_text(html, encoding="utf-8")
    print(f"Dashboard generado: {DASHBOARD.relative_to(ROOT)} ({DASHBOARD.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
