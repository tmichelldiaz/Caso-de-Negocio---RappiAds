"""
Este archivo ejecuta sql/solution.sql en DuckDB y exporta las tablas finales a outputs/.

Uso (desde la carpeta raíz del proyecto):
    python sql/run_sql.py
"""
import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
SQL_FILE = ROOT / "sql" / "solution.sql"
INSIGHTS_FILE = ROOT / "sql" / "insights.sql"
OUTPUT_DIR = ROOT / "outputs"
INSIGHTS_DIR = OUTPUT_DIR / "insights"

TABLES_TO_EXPORT = [
    "CAMPAIGN_DAILY_CLEAN",
    "CAMPAIGN_SUMMARY",
    "CAMPAIGN_WEEKLY_SUMMARY",
    "CAMPAIGN_PRIORITY",
]


def export(con, table, out_file):
    con.execute(f"COPY {table} TO '{out_file.as_posix()}' (HEADER, DELIMITER ',')")
    rows = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    print(f"{table}: {rows} filas -> {out_file.relative_to(ROOT)}")


def main():
    # Las rutas de los CSV en el SQL son relativas a la raíz del proyecto
    os.chdir(ROOT)
    OUTPUT_DIR.mkdir(exist_ok=True)

    con = duckdb.connect()  # base en memoria, se reconstruye cada vez
    con.execute(SQL_FILE.read_text(encoding="utf-8"))

    for table in TABLES_TO_EXPORT:
        export(con, table, OUTPUT_DIR / f"{table}.csv")

    # Consultas de análisis (Parte 4): se exportan todas las tablas INSIGHT_*
    con.execute(INSIGHTS_FILE.read_text(encoding="utf-8"))
    INSIGHTS_DIR.mkdir(exist_ok=True)
    insight_tables = [row[0] for row in con.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'INSIGHT_%' ORDER BY table_name"
    ).fetchall()]
    for table in insight_tables:
        export(con, table, INSIGHTS_DIR / f"{table}.csv")

    con.close()


if __name__ == "__main__":
    main()
