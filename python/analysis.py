"""
Prueba técnica Rappi Ads - Parte 2 (Python)

Lee los archivos originales y genera outputs/DATA_QUALITY_REPORT.csv
con una fila por validación.

Uso (desde la carpeta raíz del proyecto):
    python python/analysis.py
"""
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_FILE = ROOT / "outputs" / "DATA_QUALITY_REPORT.csv"

METRIC_COLUMNS = [
    "IMPRESSIONS",
    "CLICKS",
    "SPEND_USD",
    "ATTRIBUTED_ORDERS",
    "ATTRIBUTED_SALES_USD",
]

REQUIRED_COLUMNS = {
    "CAMPAIGNS.csv": ["CAMPAIGN_ID", "START_DATE", "END_DATE"],
    "DAILY_PERFORMANCE.csv": ["ROW_ID", "CAMPAIGN_ID", "EVENT_DATE", "UPDATED_AT"] + METRIC_COLUMNS,
}


def load_csv(file_name):
    """Lee un CSV de data/ como texto y valida que tenga las columnas esperadas."""
    path = DATA_DIR / file_name
    try:
        df = pd.read_csv(path, dtype=str)
    except FileNotFoundError:
        raise FileNotFoundError(f"No se encontró el archivo {path}")
    except pd.errors.EmptyDataError:
        raise ValueError(f"El archivo {path} está vacío")

    missing = [col for col in REQUIRED_COLUMNS.get(file_name, []) if col not in df.columns]
    if missing:
        raise ValueError(f"{file_name} no tiene las columnas: {missing}")

    return df


def build_check(df, mask, check_name, description, examples=3):
    """Resume una validación: cuántos registros la incumplen, qué % y algunos ROW_ID."""
    affected = df.loc[mask, "ROW_ID"].sort_values()
    total = len(df)
    return {
        "CHECK_NAME": check_name,
        "DESCRIPTION": description,
        "AFFECTED_ROWS": len(affected),
        "TOTAL_ROWS": total,
        "PCT_AFFECTED": round(len(affected) / total * 100, 2) if total else 0.0,
        "EXAMPLE_ROW_IDS": ", ".join(affected.head(examples)),
    }


def prepare_daily(daily):
    """Convierte métricas y fechas. Los valores que no se pueden convertir quedan como nulos."""
    daily = daily.copy()
    daily["CAMPAIGN_ID"] = daily["CAMPAIGN_ID"].str.strip()
    for col in METRIC_COLUMNS:
        daily[col] = pd.to_numeric(daily[col], errors="coerce")
    daily["EVENT_DATE"] = pd.to_datetime(daily["EVENT_DATE"], errors="coerce")
    return daily


def run_checks(daily, campaigns):
    checks = []

    # 1. Claves repetidas (solo entre registros con campaña informada)
    has_id = daily["CAMPAIGN_ID"].notna()
    duplicated_key = has_id & daily.duplicated(["CAMPAIGN_ID", "EVENT_DATE"], keep=False)
    n_keys = daily.loc[duplicated_key, ["CAMPAIGN_ID", "EVENT_DATE"]].drop_duplicates().shape[0]
    checks.append(build_check(
        daily, duplicated_key, "DUPLICATE_KEY",
        f"Registros cuya combinación CAMPAIGN_ID + EVENT_DATE aparece más de una vez ({n_keys} claves)",
    ))

    # 2. Campaña nula o inexistente en CAMPAIGNS
    checks.append(build_check(
        daily, ~has_id, "NULL_CAMPAIGN_ID",
        "Registros sin CAMPAIGN_ID",
    ))
    unknown = has_id & ~daily["CAMPAIGN_ID"].isin(campaigns["CAMPAIGN_ID"])
    checks.append(build_check(
        daily, unknown, "UNKNOWN_CAMPAIGN",
        "CAMPAIGN_ID que no existe en CAMPAIGNS",
    ))

    # 3. Métricas nulas o negativas
    checks.append(build_check(
        daily, daily[METRIC_COLUMNS].isna().any(axis=1), "NULL_METRIC",
        "Al menos una métrica nula o no numérica",
    ))
    checks.append(build_check(
        daily, (daily[METRIC_COLUMNS] < 0).any(axis=1), "NEGATIVE_METRIC",
        "Al menos una métrica con valor negativo",
    ))

    # 4. Más clics que impresiones
    checks.append(build_check(
        daily, daily["CLICKS"] > daily["IMPRESSIONS"], "CLICKS_GT_IMPRESSIONS",
        "CLICKS mayor que IMPRESSIONS",
    ))

    # 5. Fecha fuera de la vigencia de la campaña (solo campañas que existen)
    dates = campaigns[["CAMPAIGN_ID", "START_DATE", "END_DATE"]].copy()
    dates["START_DATE"] = pd.to_datetime(dates["START_DATE"], errors="coerce")
    dates["END_DATE"] = pd.to_datetime(dates["END_DATE"], errors="coerce")
    merged = daily.merge(dates, on="CAMPAIGN_ID", how="left")
    out_of_range = merged["START_DATE"].notna() & (
        (merged["EVENT_DATE"] < merged["START_DATE"]) | (merged["EVENT_DATE"] > merged["END_DATE"])
    )
    checks.append(build_check(
        merged, out_of_range, "EVENT_DATE_OUT_OF_RANGE",
        "EVENT_DATE antes de START_DATE o después de END_DATE",
    ))

    return pd.DataFrame(checks)


def main():
    try:
        campaigns = load_csv("CAMPAIGNS.csv")
        daily = prepare_daily(load_csv("DAILY_PERFORMANCE.csv"))
    except (FileNotFoundError, ValueError) as error:
        print(f"Error al cargar los datos: {error}")
        sys.exit(1)

    campaigns["CAMPAIGN_ID"] = campaigns["CAMPAIGN_ID"].str.strip()
    report = run_checks(daily, campaigns)

    OUTPUT_FILE.parent.mkdir(exist_ok=True)
    report.to_csv(OUTPUT_FILE, index=False)

    print(report[["CHECK_NAME", "AFFECTED_ROWS", "PCT_AFFECTED"]].to_string(index=False))
    print(f"\nReporte guardado en {OUTPUT_FILE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
