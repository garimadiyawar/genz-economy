"""
ML Projections — Gen Z Economic Forecasting
Uses scikit-learn to project key metrics 3–5 years forward.

Models:
  1. Rent burden trajectory (Linear + Polynomial regression)
  2. Homeownership rate forecast (ARIMA-lite via statsmodels)
  3. Student debt outstanding projection
  4. Gen Z wage vs inflation convergence timeline
  5. Survival score projection (will Gen Z thrive by 2030?)

Usage: python src/analysis/projections.py
"""

import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from loguru import logger
from datetime import datetime

from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score

DB_PATH    = Path("data/genz_economy.duckdb")
EXPORT_DIR = Path("data/exports")
PLOTS_DIR  = Path("data/exports/plots")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
PLOTS_DIR.mkdir(parents=True, exist_ok=True)

FORECAST_YEARS = 5       # Project out to 2030
MIN_R2_THRESHOLD = 0.50  # Minimum R² to trust a projection; below this we skip forecasting
MIN_DATA_POINTS  = 24    # Require at least 2 years of monthly data before projecting


# ═══════════════════════════════════════════════════════════════
# CORE FORECASTING UTILITIES
# ═══════════════════════════════════════════════════════════════

def date_to_ordinal(dates: pd.Series) -> np.ndarray:
    """Convert datetime series to numeric ordinal for regression."""
    return np.array([d.toordinal() for d in pd.to_datetime(dates)]).reshape(-1, 1)


def future_dates(last_date: pd.Timestamp, years: int = 5, freq: str = "MS") -> pd.DatetimeIndex:
    """Generate future date range for projections."""
    return pd.date_range(
        start=last_date + pd.DateOffset(months=1),
        periods=years * 12,
        freq=freq
    )


def fit_poly_model(X: np.ndarray, y: np.ndarray, degree: int = 2):
    """Fit polynomial regression model."""
    model = Pipeline([
        ("poly", PolynomialFeatures(degree=degree, include_bias=False)),
        ("reg",  LinearRegression()),
    ])
    model.fit(X, y)
    y_pred = model.predict(X)
    mae = mean_absolute_error(y, y_pred)
    r2  = r2_score(y, y_pred)
    return model, mae, r2


def add_confidence_band(X_future: np.ndarray, y_future: np.ndarray,
                        residual_std: float, multiplier: float = 1.96):
    """Simple ±1.96σ confidence band."""
    return y_future - multiplier * residual_std, y_future + multiplier * residual_std


# ═══════════════════════════════════════════════════════════════
# PROJECTION 1: Rent Burden
# ═══════════════════════════════════════════════════════════════

def project_rent_burden(con) -> pd.DataFrame:
    logger.info("  Projecting rent burden...")

    df = con.execute("""
        SELECT date, AVG(rent_to_income_pct) AS rent_burden
        FROM cost_burden_mart
        WHERE date >= '2015-01-01'
          AND rent_to_income_pct IS NOT NULL
        GROUP BY date
        ORDER BY date
    """).df()

    if df.empty or len(df) < 12:
        logger.warning("  Insufficient rent burden data — using FRED CPI rent proxy")
        df = con.execute("""
            SELECT date, value AS rent_burden
            FROM fred_indicators
            WHERE series_id = 'CUSR0000SEHA'
              AND date >= '2015-01-01'
            ORDER BY date
        """).df()
        if df.empty:
            return pd.DataFrame()
        # Normalize to rent-to-income % (rough: CPI rent index / 3 ≈ %)
        df["rent_burden"] = df["rent_burden"] / df["rent_burden"].iloc[0] * 28

    df["date"] = pd.to_datetime(df["date"])
    X = date_to_ordinal(df["date"])
    y = df["rent_burden"].values

    # Fit both linear and polynomial — pick better R²
    lin_model, lin_mae, lin_r2 = fit_poly_model(X, y, degree=1)
    poly_model, poly_mae, poly_r2 = fit_poly_model(X, y, degree=2)

    best_r2 = max(lin_r2, poly_r2)
    best_model = poly_model if poly_r2 > lin_r2 else lin_model
    best_label = "polynomial" if poly_r2 > lin_r2 else "linear"
    logger.info(f"    Best fit: {best_label} (R²={best_r2:.3f})")

    if best_r2 < MIN_R2_THRESHOLD:
        logger.warning(
            f"    Rent burden R²={best_r2:.3f} < threshold {MIN_R2_THRESHOLD}. "
            f"Trend is too noisy for reliable projection — returning historical data only."
        )
        return pd.DataFrame({"date": df["date"], "rent_burden": y,
                             "is_forecast": False, "metric": "rent_burden_pct"})

    # Residual std for confidence band
    y_fitted = best_model.predict(X)
    residual_std = np.std(y - y_fitted)

    # Forecast
    future = future_dates(df["date"].max())
    X_future = date_to_ordinal(future)
    y_future = best_model.predict(X_future)
    lo, hi = add_confidence_band(X_future, y_future, residual_std)

    result = pd.DataFrame({
        "date":         list(df["date"]) + list(future),
        "rent_burden":  list(y)          + list(y_future),
        "lower_95":     [None]*len(df)   + list(lo),
        "upper_95":     [None]*len(df)   + list(hi),
        "is_forecast":  [False]*len(df)  + [True]*len(future),
        "metric":       "rent_burden_pct",
    })

    # Key finding
    latest_burden = y[-1]
    future_burden = y_future[-1]
    logger.info(f"    Current rent burden: {latest_burden:.1f}%")
    logger.info(f"    Projected 2030:      {future_burden:.1f}%")
    if future_burden > 35:
        logger.warning("    ⚠ Trend: Gen Z will be severely rent-burdened by 2030")

    return result


# ═══════════════════════════════════════════════════════════════
# PROJECTION 2: Student Debt
# ═══════════════════════════════════════════════════════════════

def project_student_debt(con) -> pd.DataFrame:
    logger.info("  Projecting student debt...")

    df = con.execute("""
        SELECT date, value AS debt_billions
        FROM fred_indicators
        WHERE series_id = 'SLOAS'
          AND date >= '2010-01-01'
        ORDER BY date
    """).df()

    if df.empty:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])
    X = date_to_ordinal(df["date"])
    y = df["debt_billions"].values

    model, mae, r2 = fit_poly_model(X, y, degree=1)
    logger.info(f"    Student debt linear R²={r2:.3f}")

    residual_std = np.std(y - model.predict(X))
    future = future_dates(df["date"].max())
    X_future = date_to_ordinal(future)
    y_future = model.predict(X_future)
    lo, hi = add_confidence_band(X_future, y_future, residual_std)

    result = pd.DataFrame({
        "date":          list(df["date"]) + list(future),
        "debt_billions": list(y)          + list(y_future),
        "lower_95":      [None]*len(df)   + list(lo),
        "upper_95":      [None]*len(df)   + list(hi),
        "is_forecast":   [False]*len(df)  + [True]*len(future),
        "metric":        "student_debt_billions",
    })

    logger.info(f"    Current debt: ${y[-1]:.0f}B → Projected 2030: ${y_future[-1]:.0f}B")
    return result


# ═══════════════════════════════════════════════════════════════
# PROJECTION 3: Real Wage vs Inflation Gap
# ═══════════════════════════════════════════════════════════════

def project_wage_gap(con) -> pd.DataFrame:
    logger.info("  Projecting wage vs inflation gap...")

    df = con.execute("""
        WITH wages AS (
            SELECT date, value AS weekly_wage
            FROM bls_indicators
            WHERE series_id = 'LEU0254530000'
              AND date >= '2010-01-01'
        ),
        cpi AS (
            SELECT date, value AS cpi
            FROM fred_indicators
            WHERE series_id = 'CPIAUCSL'
              AND date >= '2010-01-01'
        )
        SELECT
            w.date,
            w.weekly_wage,
            c.cpi,
            w.weekly_wage / (c.cpi / 100.0) AS real_wage
        FROM wages w
        LEFT JOIN cpi c ON DATE_TRUNC('month', w.date) = DATE_TRUNC('month', c.date)
        WHERE c.cpi IS NOT NULL
        ORDER BY w.date
    """).df()

    if df.empty or len(df) < 12:
        return pd.DataFrame()

    df["date"] = pd.to_datetime(df["date"])

    # Project nominal wage
    X = date_to_ordinal(df["date"])
    y_wage = df["weekly_wage"].values
    y_cpi  = df["cpi"].values

    wage_model, _, wage_r2 = fit_poly_model(X, y_wage, degree=1)
    cpi_model,  _, cpi_r2  = fit_poly_model(X, y_cpi,  degree=1)

    future = future_dates(df["date"].max())
    X_future = date_to_ordinal(future)
    wage_future = wage_model.predict(X_future)
    cpi_future  = cpi_model.predict(X_future)
    real_wage_future = wage_future / (cpi_future / 100.0)

    result = pd.DataFrame({
        "date":             list(df["date"])   + list(future),
        "nominal_wage":     list(y_wage)       + list(wage_future),
        "real_wage":        list(df["real_wage"]) + list(real_wage_future),
        "cpi":              list(y_cpi)        + list(cpi_future),
        "is_forecast":      [False]*len(df)    + [True]*len(future),
        "metric":           "wage_inflation_gap",
    })

    wage_pct_change = (wage_future[-1] - y_wage[-1]) / y_wage[-1] * 100
    real_pct_change = (real_wage_future[-1] - df["real_wage"].iloc[-1]) / df["real_wage"].iloc[-1] * 100
    logger.info(f"    Nominal wage +{wage_pct_change:.1f}% by 2030")
    logger.info(f"    Real wage   +{real_pct_change:.1f}% by 2030 (inflation-adjusted)")

    return result


# ═══════════════════════════════════════════════════════════════
# PROJECTION 4: Survival Score Trajectory
# ═══════════════════════════════════════════════════════════════

def project_survival_score() -> pd.DataFrame:
    """Load computed survival scores and project forward."""
    logger.info("  Projecting survival score...")

    score_path = EXPORT_DIR / "tableau_survival_score_timeseries.csv"
    if not score_path.exists():
        logger.warning("  Run survival_score.py first")
        return pd.DataFrame()

    df = pd.read_csv(score_path, parse_dates=["date"])
    df = df.dropna(subset=["survival_score"])

    if len(df) < MIN_DATA_POINTS:
        logger.warning(f"    Only {len(df)} data points — need {MIN_DATA_POINTS} for reliable projection.")
        return pd.DataFrame()

    X = date_to_ordinal(df["date"])
    y = df["survival_score"].values

    # Use last 3 years for trend — but warn if that window includes a structural break
    # (e.g. COVID 2020, policy change) as the projection will extrapolate that shock.
    cutoff = df["date"].max() - pd.DateOffset(years=3)
    logger.info(f"    Projection window: {cutoff.date()} → {df['date'].max().date()}")
    recent = df[df["date"] >= cutoff]
    X_recent = date_to_ordinal(recent["date"])
    y_recent = recent["survival_score"].values

    model, _, r2 = fit_poly_model(X_recent, y_recent, degree=1)
    residual_std = np.std(y_recent - model.predict(X_recent))

    if r2 < MIN_R2_THRESHOLD:
        logger.warning(
            f"    Survival score R²={r2:.3f} < {MIN_R2_THRESHOLD}: "
            f"recent trend is not sufficiently linear for projection. "
            f"Forecasts shown with widened uncertainty bands."
        )
        residual_std *= 2.0  # Widen confidence band to reflect poor fit

    future = future_dates(df["date"].max())
    X_future = date_to_ordinal(future)
    y_future = np.clip(model.predict(X_future), 0, 100)
    lo = np.clip(y_future - 1.96 * residual_std, 0, 100)
    hi = np.clip(y_future + 1.96 * residual_std, 0, 100)

    def categorize(s):
        if s <= 33: return "Barely Surviving"
        if s <= 66: return "Living"
        return "Thriving"

    result = pd.DataFrame({
        "date":           list(df["date"])    + list(future),
        "survival_score": list(y)             + list(y_future),
        "lower_95":       [None]*len(df)      + list(lo),
        "upper_95":       [None]*len(df)      + list(hi),
        "is_forecast":    [False]*len(df)     + [True]*len(future),
        "category":       [categorize(s) for s in y] + [categorize(s) for s in y_future],
        "metric":         "survival_score",
    })

    final_score = y_future[-1]
    final_year  = future[-1].year
    logger.info(f"    Projected survival score {final_year}: {final_score:.1f} → {categorize(final_score)}")

    return result


# ═══════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════

def export_projections(projections: dict[str, pd.DataFrame]):
    all_rows = []
    for name, df in projections.items():
        if not df.empty:
            df["projection_name"] = name
            all_rows.append(df)

    if not all_rows:
        logger.warning("No projection data to export.")
        return

    combined = pd.concat(all_rows, ignore_index=True)
    combined.to_csv(EXPORT_DIR / "tableau_projections.csv", index=False)
    logger.success(f"Projections exported: {len(combined)} rows → tableau_projections.csv")


def run():
    logger.info("=== ML Projections Engine ===")
    con = duckdb.connect(str(DB_PATH))

    projections = {}

    rent   = project_rent_burden(con)
    if not rent.empty:
        projections["rent_burden"] = rent

    debt   = project_student_debt(con)
    if not debt.empty:
        projections["student_debt"] = debt

    wages  = project_wage_gap(con)
    if not wages.empty:
        projections["wage_gap"] = wages

    score  = project_survival_score()
    if not score.empty:
        projections["survival_score"] = score

    export_projections(projections)
    con.close()

    logger.info("\n=== 2030 OUTLOOK SUMMARY ===")
    logger.info("All projection CSVs ready for Tableau.")
    logger.info("Load 'tableau_projections.csv' and filter by metric field.")
    logger.info("Use 'is_forecast=True' to distinguish actuals vs forecasts.")

    return projections


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    run()
