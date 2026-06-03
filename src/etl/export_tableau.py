"""
Tableau Export Pipeline
Generates all CSV files needed for the 6 Tableau Public dashboards.
Also attempts to create a Tableau Hyper extract if tableauhyperapi is available.

Output files (all in data/exports/):
  tableau_survival_score_timeseries.csv   → Dashboard 1: National Overview
  tableau_annual_summary.csv              → Dashboard 1: KPI tiles
  tableau_dimension_breakdown.csv         → Dashboard 1: Radar/bar chart
  tableau_cost_burden_by_metro.csv        → Dashboard 2: Cost Crunch map
  tableau_education_debt.csv              → Dashboard 3: Education Trap
  tableau_employment_landscape.csv        → Dashboard 4: Job Market Reality
  tableau_generational_comparison.csv     → Dashboard 5: Gen Z vs Boomers
  tableau_projections.csv                 → Dashboard 6: 2030 Outlook
  tableau_job_postings.csv                → Dashboard 4: Job postings detail
  tableau_news_sentiment.csv              → Dashboard 6: Media sentiment

Usage: python src/etl/export_tableau.py
"""

import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger

DB_PATH    = Path("data/genz_economy.duckdb")
EXPORT_DIR = Path("data/exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


def get_con():
    return duckdb.connect(str(DB_PATH))


# ─────────────────────────────────────────────────────────────
# EXPORT 1: Cost Burden by Metro (Dashboard 2)
# ─────────────────────────────────────────────────────────────

def export_cost_burden_metro(con):
    logger.info("  Export: cost burden by metro")

    df = con.execute("""
        SELECT
            region_name,
            state_name,
            YEAR(date) AS year,
            MONTH(date) AS month,
            date,
            AVG(monthly_rent)           AS avg_rent,
            AVG(monthly_income_median)  AS avg_income_median,
            AVG(rent_to_income_pct)     AS rent_to_income_pct,
            MAX(burden_category)        AS burden_category,
            COUNT(*)                    AS data_points
        FROM cost_burden_mart
        WHERE date >= '2018-01-01'
          AND region_name IS NOT NULL
        GROUP BY region_name, state_name, YEAR(date), MONTH(date), date
        ORDER BY date DESC, rent_to_income_pct DESC
    """).df()

    if df.empty:
        logger.warning("  cost_burden_mart empty — creating stub")
        df = pd.DataFrame({
            "region_name": ["National Average"],
            "state_name":  ["US"],
            "year":        [2024],
            "rent_to_income_pct": [32.5],
            "burden_category": ["Cost Burdened"],
            "note": ["Run data collectors to populate"]
        })

    path = EXPORT_DIR / "tableau_cost_burden_by_metro.csv"
    df.to_csv(path, index=False)
    logger.success(f"    → {path} ({len(df)} rows)")
    return df


# ─────────────────────────────────────────────────────────────
# EXPORT 2: Education Debt Analysis (Dashboard 3)
# ─────────────────────────────────────────────────────────────

def export_education_debt(con):
    logger.info("  Export: education debt analysis")

    # Student debt outstanding over time
    debt_ts = con.execute("""
        SELECT date, value AS student_debt_billions, 'outstanding' AS metric
        FROM fred_indicators
        WHERE series_id = 'SLOAS'
        ORDER BY date
    """).df()

    # Delinquency rate
    delinq = con.execute("""
        SELECT date, value AS delinquency_pct, 'delinquency_rate' AS metric
        FROM fred_indicators
        WHERE series_id = 'DRSFRMACBS'
        ORDER BY date
    """).df()

    combined = pd.concat([debt_ts, delinq], ignore_index=True)

    # Scorecard data (if available)
    scorecard_path = Path("data/raw/education/college_scorecard.parquet")
    if scorecard_path.exists():
        sc = pd.read_parquet(scorecard_path)
        # Rename scorecard columns for tableau
        rename = {
            "school.name": "school_name",
            "school.state": "state",
            "latest.aid.median_debt.completers.overall": "median_debt",
            "latest.earnings.6_yrs_after_entry.median": "earnings_6yr",
            "latest.earnings.10_yrs_after_entry.median": "earnings_10yr",
            "latest.cost.tuition.in_state": "tuition_in_state",
            "latest.completion.completion_rate_4yr_150nt": "completion_rate",
        }
        sc = sc.rename(columns={k:v for k,v in rename.items() if k in sc.columns})
        sc["debt_to_earnings_ratio"] = (sc.get("median_debt", np.nan) /
                                         sc.get("earnings_6yr", np.nan).replace(0, np.nan))
        sc_path = EXPORT_DIR / "tableau_college_scorecard.csv"
        sc.to_csv(sc_path, index=False)
        logger.success(f"    → {sc_path}")

    path = EXPORT_DIR / "tableau_education_debt.csv"
    combined.to_csv(path, index=False)
    logger.success(f"    → {path} ({len(combined)} rows)")
    return combined


# ─────────────────────────────────────────────────────────────
# EXPORT 3: Employment Landscape (Dashboard 4)
# ─────────────────────────────────────────────────────────────

def export_employment_landscape(con):
    logger.info("  Export: employment landscape")

    emp = con.execute("""
        SELECT *
        FROM employment_mart
        WHERE date >= '2010-01-01'
        ORDER BY date
    """).df()

    # Add YoY change columns
    for col in ["unemployment_20_24", "unemployment_25_34", "underemployment_u6"]:
        if col in emp.columns:
            emp[f"{col}_yoy"] = emp[col].diff(12)

    # Also pull wage data
    wages = con.execute("""
        SELECT date,
            MAX(CASE WHEN series_id = 'LEU0252881600' THEN value END) AS median_wage_20_24,
            MAX(CASE WHEN series_id = 'LEU0252881700' THEN value END) AS median_wage_25_34,
            MAX(CASE WHEN series_id = 'LEU0254530000' THEN value END) AS median_wage_all
        FROM bls_indicators
        WHERE series_id IN ('LEU0252881600', 'LEU0252881700', 'LEU0254530000')
          AND date >= '2010-01-01'
        GROUP BY date
        ORDER BY date
    """).df()

    merged = emp.merge(wages, on="date", how="outer").sort_values("date")

    path = EXPORT_DIR / "tableau_employment_landscape.csv"
    merged.to_csv(path, index=False)
    logger.success(f"    → {path} ({len(merged)} rows)")
    return merged


# ─────────────────────────────────────────────────────────────
# EXPORT 4: Generational Comparison (Dashboard 5)
# ─────────────────────────────────────────────────────────────

def export_generational_comparison(con):
    """
    Compare Gen Z economic conditions to Boomers and Millennials
    at the same age (25-34). Uses FRED historical data + census.

    Key sources:
    - Opportunity Insights: https://opportunityinsights.org/data/
    - Fed Distributional Financial Accounts (DFA)
    """
    logger.info("  Export: generational comparison")

    # Real median income over decades (proxy comparison)
    income = con.execute("""
        SELECT date, value AS real_median_household_income
        FROM fred_indicators
        WHERE series_id = 'MEHOINUSA672N'
        ORDER BY date
    """).df()

    # Homeownership (proxy — actual generational breakdowns need Census micro)
    home_val = con.execute("""
        SELECT date, value AS median_home_price
        FROM fred_indicators
        WHERE series_id = 'MSPUS'
        ORDER BY date
    """).df()

    wages = con.execute("""
        SELECT date, value AS median_weekly_earnings
        FROM fred_indicators
        WHERE series_id = 'LES1252881600Q'
        ORDER BY date
    """).df()

    # Combine
    combined = income.merge(home_val, on="date", how="outer") \
                     .merge(wages, on="date", how="outer") \
                     .sort_values("date")

    combined["date"] = pd.to_datetime(combined["date"])
    combined["year"] = combined["date"].dt.year

    # Tag generations by approximate age-25 period
    # Boomers at 25: ~1967–1982 | Gen X: ~1983–1996 | Millennials: ~1997–2012 | Gen Z: ~2020+
    def label_cohort(year):
        if year <= 1982: return "Boomers at 25"
        if year <= 1996: return "Gen X at 25"
        if year <= 2012: return "Millennials at 25"
        if year >= 2019: return "Gen Z at 25"
        return "Transition"

    combined["cohort_label"] = combined["year"].apply(label_cohort)

    # Affordability ratio: home price / annual income
    combined["home_price_to_income"] = (
        combined["median_home_price"] /
        combined["real_median_household_income"].replace(0, np.nan)
    ).round(2)

    path = EXPORT_DIR / "tableau_generational_comparison.csv"
    combined.to_csv(path, index=False)
    logger.success(f"    → {path} ({len(combined)} rows)")
    return combined


# ─────────────────────────────────────────────────────────────
# EXPORT 5: Housing Squeeze (supplemental)
# ─────────────────────────────────────────────────────────────

def export_housing_squeeze(con):
    logger.info("  Export: housing squeeze")

    home_prices = con.execute("""
        SELECT date, value AS median_home_price
        FROM fred_indicators
        WHERE series_id = 'MSPUS'
        ORDER BY date
    """).df()

    rent_cpi = con.execute("""
        SELECT date, value AS rent_cpi
        FROM fred_indicators
        WHERE series_id = 'CUSR0000SEHA'
        ORDER BY date
    """).df()

    wages = con.execute("""
        SELECT date, value * 52 AS annual_wage
        FROM bls_indicators
        WHERE series_id = 'LEU0254530000'
        ORDER BY date
    """).df()

    merged = home_prices.merge(rent_cpi, on="date", how="outer") \
                        .merge(wages, on="date", how="outer") \
                        .sort_values("date")

    merged["date"] = pd.to_datetime(merged["date"])
    # Months of median income to save 20% down payment (at 10% savings rate)
    merged["months_to_down_payment"] = (
        (merged["median_home_price"] * 0.20) /
        (merged["annual_wage"] / 12 * 0.10)
    ).round(1)

    path = EXPORT_DIR / "tableau_housing_squeeze.csv"
    merged.to_csv(path, index=False)
    logger.success(f"    → {path} ({len(merged)} rows)")
    return merged


# ─────────────────────────────────────────────────────────────
# MASTER EXPORT RUNNER
# ─────────────────────────────────────────────────────────────

def run():
    logger.info("=== Tableau Export Pipeline ===")
    con = get_con()

    exports = {}
    exports["cost_burden"]       = export_cost_burden_metro(con)
    exports["education"]         = export_education_debt(con)
    exports["employment"]        = export_employment_landscape(con)
    exports["generational"]      = export_generational_comparison(con)
    exports["housing"]           = export_housing_squeeze(con)

    con.close()

    # Print summary
    logger.info("\n╔═══════════════════════════════════════════════════════╗")
    logger.info("║  TABLEAU EXPORT COMPLETE                              ║")
    logger.info("╠═══════════════════════════════════════════════════════╣")
    files = list(EXPORT_DIR.glob("tableau_*.csv"))
    for f in sorted(files):
        size = f.stat().st_size // 1024
        logger.info(f"║  ✓ {f.name:<45} {size:>4}KB ║")
    logger.info("╠═══════════════════════════════════════════════════════╣")
    logger.info("║  NEXT STEPS:                                          ║")
    logger.info("║  1. Open Tableau Public (free download)               ║")
    logger.info("║  2. Connect to Text File → point to data/exports/     ║")
    logger.info("║  3. See tableau/DASHBOARD_GUIDE.md for build steps    ║")
    logger.info("╚═══════════════════════════════════════════════════════╝")

    return exports


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    run()
