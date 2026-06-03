"""
ETL Pipeline — Load raw data into DuckDB warehouse
Creates structured marts ready for analysis and Tableau export.

Usage: python src/etl/pipeline.py
"""

import duckdb
import pandas as pd
from pathlib import Path
from loguru import logger

RAW_DIR   = Path("data/raw")
PROC_DIR  = Path("data/processed")
DB_PATH   = Path("data/genz_economy.duckdb")

PROC_DIR.mkdir(parents=True, exist_ok=True)


def get_connection():
    return duckdb.connect(str(DB_PATH))


def create_schema(con):
    """Create DuckDB tables for the data warehouse."""
    con.execute("""
        -- ── Macro Indicators (FRED) ──────────────────────────────
        CREATE TABLE IF NOT EXISTS fred_indicators (
            date        DATE NOT NULL,
            series_id   VARCHAR NOT NULL,
            label       VARCHAR,
            value       DOUBLE,
            PRIMARY KEY (date, series_id)
        );

        -- ── Employment & Wages (BLS) ─────────────────────────────
        CREATE TABLE IF NOT EXISTS bls_indicators (
            date        DATE NOT NULL,
            series_id   VARCHAR NOT NULL,
            label       VARCHAR,
            value       DOUBLE,
            period_type CHAR(1),
            PRIMARY KEY (date, series_id)
        );

        -- ── Census Demographics ──────────────────────────────────
        CREATE TABLE IF NOT EXISTS census_national (
            year        INTEGER NOT NULL,
            geo_level   VARCHAR,
            state       VARCHAR,
            -- Key metrics (renamed)
            median_income_all                DOUBLE,
            owner_occupied_under25           DOUBLE,
            owner_occupied_25_34             DOUBLE,
            renter_occupied_under25          DOUBLE,
            rent_50plus_pct_income           DOUBLE,
            living_with_parents_18_34        DOUBLE,
            PRIMARY KEY (year, geo_level)
        );

        -- ── Housing (Zillow) ─────────────────────────────────────
        CREATE TABLE IF NOT EXISTS zillow_rent (
            date        DATE NOT NULL,
            region_name VARCHAR,
            state_name  VARCHAR,
            value       DOUBLE,
            series      VARCHAR
        );

        CREATE TABLE IF NOT EXISTS zillow_home_values (
            date        DATE NOT NULL,
            region_name VARCHAR,
            state_name  VARCHAR,
            value       DOUBLE,
            series      VARCHAR
        );

        -- ── Education (College Scorecard) ───────────────────────
        CREATE TABLE IF NOT EXISTS college_outcomes (
            school_name     VARCHAR,
            state           VARCHAR,
            in_state_tuition DOUBLE,
            median_debt     DOUBLE,
            earnings_6yr    DOUBLE,
            earnings_10yr   DOUBLE,
            completion_rate DOUBLE,
            first_gen_share DOUBLE
        );
    """)
    logger.success("Schema created/verified")


def load_fred(con):
    p = RAW_DIR / "fred/fred_indicators.parquet"
    if not p.exists():
        logger.warning("FRED parquet not found — skipping")
        return
    con.execute("DELETE FROM fred_indicators")
    con.execute(f"INSERT INTO fred_indicators SELECT date, series_id, label, value FROM read_parquet('{p}')")
    count = con.execute("SELECT COUNT(*) FROM fred_indicators").fetchone()[0]
    logger.success(f"FRED loaded: {count:,} rows")


def load_bls(con):
    p = RAW_DIR / "bls/bls_indicators.parquet"
    if not p.exists():
        logger.warning("BLS parquet not found — skipping")
        return
    con.execute("DELETE FROM bls_indicators")
    con.execute(f"INSERT INTO bls_indicators SELECT date, series_id, label, value, period_type FROM read_parquet('{p}')")
    count = con.execute("SELECT COUNT(*) FROM bls_indicators").fetchone()[0]
    logger.success(f"BLS loaded: {count:,} rows")


def load_zillow(con):
    for fname, table in [
        ("zillow_rent_index_metros.parquet", "zillow_rent"),
        ("zillow_home_value_metros.parquet", "zillow_home_values"),
    ]:
        p = RAW_DIR / f"housing/{fname}"
        if not p.exists():
            logger.warning(f"{fname} not found — skipping")
            continue
        con.execute(f"DELETE FROM {table}")
        con.execute(f"""
            INSERT INTO {table}
            SELECT date, RegionName, StateName, value, series
            FROM read_parquet('{p}')
            WHERE value IS NOT NULL
        """)
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        logger.success(f"{table} loaded: {count:,} rows")


def build_cost_burden_mart(con):
    """
    Core analytical mart: cost burden by metro.
    Combines rent (Zillow) with wage data (BLS) to compute rent-to-income ratio.

    IMPORTANT: Uses state-level wage adjustment via Census median income ratios
    rather than a single national wage figure. Applying one national wage to
    all metros makes high-cost metros look artificially burdened and low-cost
    metros look artificially affordable. We scale the national BLS median by
    each state's relative income index from Census ACS data where available.
    """
    con.execute("""
        CREATE OR REPLACE VIEW cost_burden_mart AS
        WITH
        rent AS (
            SELECT
                date,
                region_name,
                state_name,
                value AS monthly_rent
            FROM zillow_rent
            WHERE date >= '2019-01-01'
        ),
        national_wages AS (
            -- National median weekly earnings (25-34) as base
            SELECT
                date,
                value * 52.0 / 12.0 AS national_monthly_income
            FROM bls_indicators
            WHERE series_id = 'LEU0252881700'
              AND date >= '2019-01-01'
        ),
        -- State income relative to national median from Census ACS.
        -- Falls back to 1.0 (national wage) for states not in Census data.
        -- This corrects the most egregious metro-vs-national wage mismatch.
        state_income_index AS (
            SELECT
                state,
                COALESCE(
                    AVG(median_income_all) /
                    NULLIF((SELECT AVG(median_income_all) FROM census_national WHERE geo_level = 'national'), 0),
                    1.0
                ) AS income_index
            FROM census_national
            WHERE geo_level = 'state'
            GROUP BY state
        ),
        cpi AS (
            SELECT date, value AS cpi
            FROM fred_indicators
            WHERE series_id = 'CPIAUCSL'
        )
        SELECT
            r.date,
            r.region_name,
            r.state_name,
            r.monthly_rent,
            w.national_monthly_income * COALESCE(si.income_index, 1.0) AS monthly_income_median,
            si.income_index AS state_income_index,
            ROUND(r.monthly_rent / NULLIF(w.national_monthly_income * COALESCE(si.income_index, 1.0), 0) * 100, 1) AS rent_to_income_pct,
            CASE
                WHEN r.monthly_rent / NULLIF(w.national_monthly_income * COALESCE(si.income_index, 1.0), 0) > 0.50 THEN 'Severely Burdened'
                WHEN r.monthly_rent / NULLIF(w.national_monthly_income * COALESCE(si.income_index, 1.0), 0) > 0.30 THEN 'Cost Burdened'
                ELSE 'Affordable'
            END AS burden_category,
            c.cpi
        FROM rent r
        LEFT JOIN national_wages w ON DATE_TRUNC('month', r.date) = DATE_TRUNC('month', w.date)
        LEFT JOIN state_income_index si ON r.state_name = si.state
        LEFT JOIN cpi c ON DATE_TRUNC('month', r.date) = DATE_TRUNC('month', c.date)
    """)
    logger.success("cost_burden_mart view created (with state-level wage adjustment)")


def build_unemployment_mart(con):
    """Employment quality mart — unemployment + underemployment by age group."""
    con.execute("""
        CREATE OR REPLACE VIEW employment_mart AS
        SELECT
            date,
            MAX(CASE WHEN series_id = 'LNS14000036' THEN value END) AS unemployment_20_24,
            MAX(CASE WHEN series_id = 'LNS14000091' THEN value END) AS unemployment_25_34,
            MAX(CASE WHEN series_id = 'LNS14000006' THEN value END) AS unemployment_total,
            MAX(CASE WHEN series_id = 'U6RATE'       THEN value END) AS underemployment_u6,
            MAX(CASE WHEN series_id = 'LNS12300036'  THEN value END) AS emp_pop_ratio_20_24,
            MAX(CASE WHEN series_id = 'LNS12300091'  THEN value END) AS emp_pop_ratio_25_34
        FROM bls_indicators
        WHERE series_id IN (
            'LNS14000036', 'LNS14000091', 'LNS14000006',
            'U6RATE', 'LNS12300036', 'LNS12300091'
        )
        GROUP BY date
        ORDER BY date
    """)
    logger.success("employment_mart view created")


def run():
    logger.info("=== ETL Pipeline ===")
    con = get_connection()

    create_schema(con)
    load_fred(con)
    load_bls(con)
    load_zillow(con)
    build_cost_burden_mart(con)
    build_unemployment_mart(con)

    con.close()
    logger.success(f"Pipeline complete → {DB_PATH}")
    logger.info("Next: python src/analysis/survival_score.py")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    run()
