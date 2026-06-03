"""
Gen Z Survival Score Engine
Produces the headline composite score across 7 dimensions.

Score bands:
  0–33  → Barely Surviving 🔴
  34–66 → Living            🟡
  67–100 → Thriving          🟢

Usage: python src/analysis/survival_score.py
"""

import duckdb
import pandas as pd
import numpy as np
from pathlib import Path
from loguru import logger

DB_PATH      = Path("data/genz_economy.duckdb")
EXPORT_DIR   = Path("data/exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# ── Index normalization helper ────────────────────────────────────────────

# Anchored thresholds: scores are fixed against real-world benchmarks,
# NOT min-maxed against the historical series. This makes the score stable
# and comparable across runs and time periods.

ANCHORS = {
    # (lower_bound_raw, upper_bound_raw, higher_is_better)
    # rent burden %: 20% = excellent (100), 60% = crisis (0)
    "rent_burden":       (20.0, 60.0, False),
    # unemployment 25-34: 3% = excellent (100), 15% = crisis (0)
    "unemployment":      (3.0,  15.0, False),
    # U-6 underemployment: 5% = excellent (100), 25% = crisis (0)
    "u6":                (5.0,  25.0, False),
    # emp-pop ratio 25-34: 85% = excellent (100), 65% = crisis (0)
    "emp_pop":           (65.0, 85.0, True),
    # real weekly wage ($): $400 = crisis (0), $1200 = excellent (100)
    "real_wage":         (400.0, 1200.0, True),
    # student debt outstanding ($B): $800B = good (100), $2000B = crisis (0)
    "student_debt":      (800.0, 2000.0, False),
}


def normalize_anchored(series: pd.Series, anchor_key: str) -> pd.Series:
    """
    Normalize a series to 0–100 using fixed real-world anchors.
    This produces a stable, absolute score that doesn't change when new data
    is added — unlike min-max normalization which is retroactively unstable.
    """
    lo, hi, higher_is_better = ANCHORS[anchor_key]
    clipped = series.clip(min(lo, hi), max(lo, hi))
    if higher_is_better:
        normalized = (clipped - lo) / (hi - lo) * 100
    else:
        normalized = (hi - clipped) / (hi - lo) * 100
    return normalized.clip(0, 100)


def normalize_to_100(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """
    Fallback min-max normalize — only used for series without defined anchors.
    NOTE: This is retroactively unstable. Prefer normalize_anchored() where possible.
    """
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series(50.0, index=series.index)
    normalized = (series - mn) / (mx - mn) * 100
    return normalized if higher_is_better else 100 - normalized


# ── Dimension 1: Cost Burden ──────────────────────────────────────────────

def compute_cost_burden_index(con) -> pd.DataFrame:
    """
    Rent-to-income ratio for Gen Z age group.
    Lower is better. National monthly trend.
    """
    df = con.execute("""
        SELECT
            date,
            AVG(rent_to_income_pct) AS avg_rent_burden
        FROM cost_burden_mart
        WHERE date >= '2015-01-01'
        GROUP BY date
        ORDER BY date
    """).df()

    if df.empty:
        logger.warning("cost_burden_mart empty — using synthetic fallback")
        # Fallback: synthesize from FRED data
        df = con.execute("""
            SELECT
                r.date,
                (r.value / (w.value * 52.0 / 12.0)) * 100 AS avg_rent_burden
            FROM fred_indicators r
            JOIN bls_indicators w
              ON DATE_TRUNC('month', r.date) = DATE_TRUNC('month', w.date)
              AND w.series_id = 'LEU0252881700'
            WHERE r.series_id = 'CUSR0000SEHA'
              AND r.date >= '2015-01-01'
            ORDER BY r.date
        """).df()

    if not df.empty:
        df["cost_burden_score"] = normalize_anchored(df["avg_rent_burden"], "rent_burden")
    return df


# ── Dimension 2: Employment Quality ──────────────────────────────────────

def compute_employment_index(con) -> pd.DataFrame:
    df = con.execute("""
        SELECT
            date,
            unemployment_20_24,
            unemployment_25_34,
            underemployment_u6,
            emp_pop_ratio_25_34
        FROM employment_mart
        WHERE date >= '2015-01-01'
        ORDER BY date
    """).df()

    if df.empty:
        logger.warning("employment_mart empty — check BLS data")
        return df

    # Score: low unemployment + low underemployment + high emp-pop ratio = good
    df["unemp_score"]    = normalize_anchored(df["unemployment_25_34"].fillna(5), "unemployment")
    df["u6_score"]       = normalize_anchored(df["underemployment_u6"].fillna(10), "u6")
    df["emppop_score"]   = normalize_anchored(df["emp_pop_ratio_25_34"].fillna(75), "emp_pop")
    df["employment_score"] = (
        0.4 * df["unemp_score"] +
        0.3 * df["u6_score"] +
        0.3 * df["emppop_score"]
    )
    return df


# ── Dimension 3: Wage vs Inflation ───────────────────────────────────────

def compute_wage_inflation_index(con) -> pd.DataFrame:
    df = con.execute("""
        WITH wages AS (
            SELECT date, value AS weekly_wage
            FROM bls_indicators
            WHERE series_id = 'LEU0254530000'  -- Median weekly earnings
              AND date >= '2015-01-01'
        ),
        cpi AS (
            SELECT date, value AS cpi
            FROM fred_indicators
            WHERE series_id = 'CPIAUCSL'
              AND date >= '2015-01-01'
        )
        SELECT
            w.date,
            w.weekly_wage,
            c.cpi,
            -- Real wage: adjust for inflation relative to 2015 baseline
            w.weekly_wage / (c.cpi / 100.0) AS real_weekly_wage
        FROM wages w
        LEFT JOIN cpi c ON DATE_TRUNC('month', w.date) = DATE_TRUNC('month', c.date)
        ORDER BY w.date
    """).df()

    if not df.empty:
        df["wage_score"] = normalize_anchored(df["real_weekly_wage"].ffill(), "real_wage")
    return df


# ── Dimension 4: Student Debt ─────────────────────────────────────────────

def compute_debt_index(con) -> pd.DataFrame:
    """
    Debt burden index uses per-borrower debt-to-income ratio, not aggregate stock.
    Aggregate stock (SLOAS) conflates population growth with individual burden.
    Per-borrower debt / median wage is the correct individual-level metric.
    """
    df = con.execute("""
        WITH debt AS (
            SELECT date, value AS student_loans_billions
            FROM fred_indicators
            WHERE series_id = 'SLOAS'
              AND date >= '2015-01-01'
        ),
        wages AS (
            SELECT date, value * 52.0 AS annual_wage
            FROM bls_indicators
            WHERE series_id = 'LEU0252881700'
              AND date >= '2015-01-01'
        )
        SELECT
            d.date,
            d.student_loans_billions,
            w.annual_wage,
            (d.student_loans_billions * 1e9 / 45e6) / NULLIF(w.annual_wage, 0) AS debt_to_income_ratio
        FROM debt d
        LEFT JOIN wages w
          ON DATE_TRUNC('month', d.date) = DATE_TRUNC('month', w.date)
        ORDER BY d.date
    """).df()

    if not df.empty and df["debt_to_income_ratio"].notna().any():
        # anchor: ratio 0.3 = manageable (100), 1.5 = severe burden (0)
        df["debt_score"] = ((1.5 - df["debt_to_income_ratio"].clip(0.3, 1.5)) / (1.5 - 0.3) * 100).clip(0, 100)
    elif not df.empty:
        df["debt_score"] = normalize_anchored(df["student_loans_billions"], "student_debt")
    return df

def classify_score(score: float) -> str:
    if score <= 33:   return "Barely Surviving 🔴"
    if score <= 66:   return "Living 🟡"
    return "Thriving 🟢"


def compute_survival_scores(con) -> pd.DataFrame:
    logger.info("Computing dimension indices...")

    cost_df  = compute_cost_burden_index(con)
    emp_df   = compute_employment_index(con)
    wage_df  = compute_wage_inflation_index(con)
    debt_df  = compute_debt_index(con)

    # ── Merge on date (monthly) ────────────────────────────────
    base_dates = pd.date_range("2015-01-01", "2025-01-01", freq="MS")
    master = pd.DataFrame({"date": base_dates})

    def safe_merge(df, score_col, rename_to):
        if df.empty or score_col not in df.columns:
            logger.warning(f"  {rename_to}: no data — will be excluded from score")
            return master
        sub = df[["date", score_col]].rename(columns={score_col: rename_to})
        sub["date"] = pd.to_datetime(sub["date"]).dt.to_period("M").dt.to_timestamp()
        return master.merge(sub, on="date", how="left")

    master = safe_merge(cost_df,  "cost_burden_score",  "cost_burden_score")
    master = safe_merge(emp_df,   "employment_score",   "employment_score")
    master = safe_merge(wage_df,  "wage_score",         "wage_score")
    master = safe_merge(debt_df,  "debt_score",         "debt_score")

    # ── Compute weighted survival score ────────────────────────
    score_cols = {
        "cost_burden_score": WEIGHTS["cost_burden"],
        "employment_score":  WEIGHTS["employment"],
        "wage_score":        WEIGHTS["wage"],
        "debt_score":        WEIGHTS["debt"],
    }

    master["survival_score"] = 0.0
    total_weight = 0.0

    for col, weight in score_cols.items():
        if col in master.columns and master[col].notna().any():
            filled = master[col].fillna(master[col].median())
            master["survival_score"] += filled * weight
            total_weight += weight

    # Warn explicitly when dimensions are missing instead of silently rescaling.
    # Rescaling makes an incomplete score look like a complete one, hiding data gaps.
    missing_weight = 1.0 - total_weight
    if total_weight > 0 and missing_weight > 0.01:
        missing_dims = [col for col, w in score_cols.items()
                        if col not in master.columns or not master[col].notna().any()]
        logger.warning(
            f"INCOMPLETE SCORE: {len(missing_dims)} dimension(s) missing "
            f"(weight={missing_weight:.0%}): {missing_dims}. "
            f"Score is based on {total_weight:.0%} of intended coverage. "
            f"Run data collectors to populate missing sources."
        )
        master["score_coverage_pct"] = round(total_weight * 100, 1)
        # Rescale so the existing dimensions fill 0-100, but flag it
        master["survival_score"] = master["survival_score"] / total_weight
    else:
        master["score_coverage_pct"] = 100.0

    master["survival_score"] = master["survival_score"].round(1)
    master["category"] = master["survival_score"].apply(classify_score)
    master["year"] = master["date"].dt.year

    # ── Interpolate gaps ───────────────────────────────────────
    for col in score_cols:
        if col in master.columns:
            master[col] = master[col].interpolate(method="linear")

    logger.success(f"Survival scores computed: {len(master)} months")

    if master["survival_score"].notna().any():
        latest = master.dropna(subset=["survival_score"]).iloc[-1]
        logger.info(f"\n{'='*50}")
        logger.info(f"LATEST GEN Z SURVIVAL SCORE: {latest['survival_score']:.1f}")
        logger.info(f"Category: {latest['category']}")
        logger.info(f"As of: {latest['date'].strftime('%B %Y')}")
        logger.info(f"{'='*50}\n")

    return master


def export_for_tableau(master: pd.DataFrame):
    """Export clean CSVs ready for Tableau Public."""
    logger.info("Exporting for Tableau...")

    # 1. Time series of survival score
    ts_path = EXPORT_DIR / "tableau_survival_score_timeseries.csv"
    master.to_csv(ts_path, index=False)
    logger.success(f"  Time series → {ts_path}")

    # 2. Annual summary
    annual = master.groupby("year").agg({
        "survival_score": "mean",
        "cost_burden_score": "mean",
        "employment_score": "mean",
        "wage_score": "mean",
        "debt_score": "mean",
    }).round(1).reset_index()
    annual["category"] = annual["survival_score"].apply(classify_score)
    annual_path = EXPORT_DIR / "tableau_annual_summary.csv"
    annual.to_csv(annual_path, index=False)
    logger.success(f"  Annual summary → {annual_path}")

    # 3. Dimension breakdown (for radar/spider chart in Tableau)
    score_cols = ["cost_burden_score", "employment_score", "wage_score", "debt_score"]
    latest = master.dropna(subset=["survival_score"]).iloc[-1]
    dimensions = pd.DataFrame({
        "dimension": score_cols,
        "score": [latest.get(c, np.nan) for c in score_cols],
        "label": ["Cost Burden", "Employment Quality", "Real Wages", "Student Debt"],
        "weight": [WEIGHTS["cost_burden"], WEIGHTS["employment"], WEIGHTS["wage"], WEIGHTS["debt"]],
        "date": latest["date"],
    })
    dim_path = EXPORT_DIR / "tableau_dimension_breakdown.csv"
    dimensions.to_csv(dim_path, index=False)
    logger.success(f"  Dimension breakdown → {dim_path}")

    logger.info(f"\nAll Tableau exports in: {EXPORT_DIR}/")
    logger.info("Load these CSVs into Tableau Public to build dashboards.")


def run():
    logger.info("=== Survival Score Engine ===")
    con = duckdb.connect(str(DB_PATH))

    master = compute_survival_scores(con)
    export_for_tableau(master)

    con.close()
    return master


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    run()
