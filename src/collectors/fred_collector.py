"""
FRED Collector — St. Louis Federal Reserve Economic Data
Free API key: https://fred.stlouisfed.org/docs/api/api_key.html

Fetches: CPI, rent index, median wage, unemployment, debt levels
"""

import os
import pandas as pd
import requests
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger
from pathlib import Path

load_dotenv()

FRED_API_KEY = os.getenv("FRED_API_KEY")
BASE_URL = "https://api.stlouisfed.org/fred/series/observations"
RAW_DIR = Path("data/raw/fred")
RAW_DIR.mkdir(parents=True, exist_ok=True)

# ── Series of interest for Gen Z analysis ──────────────────────────────────
FRED_SERIES = {
    # Cost of Living
    "CPIAUCSL":        "CPI All Urban Consumers",
    "CUSR0000SEHA":    "CPI Rent of Primary Residence",
    "CUSR0000SAH1":    "CPI Shelter",

    # Income & Wages
    "LES1252881600Q":  "Median Usual Weekly Earnings (Full-time)",
    "MEHOINUSA672N":   "Real Median Household Income",

    # Employment
    "U6RATE":          "U-6 Underemployment Rate",
    "LNS14000036":     "Unemployment Rate 20-24 years",
    "LNS14000091":     "Unemployment Rate 25-34 years",

    # Student Debt
    "SLOAS":           "Student Loans Outstanding",

    # Housing
    "HOUST":           "Housing Starts",
    "MSPUS":           "Median Sales Price of Houses",

    # Wealth / Savings
    "PSAVERT":         "Personal Saving Rate",

    # Credit stress
    "DRCCLACBS":       "Credit Card Delinquency Rate",
    "DRSFRMACBS":      "Student Loan Delinquency Rate",
}

# Gen Z era: 2010 to present covers formative economic years
START_DATE = "2010-01-01"
END_DATE   = datetime.today().strftime("%Y-%m-%d")


def fetch_series(series_id: str, label: str) -> pd.DataFrame | None:
    """Fetch a single FRED series and return as DataFrame."""
    params = {
        "series_id": series_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": START_DATE,
        "observation_end": END_DATE,
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        df = pd.DataFrame(data["observations"])[["date", "value"]]
        df["series_id"] = series_id
        df["label"] = label
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        df["date"] = pd.to_datetime(df["date"])
        df = df.dropna(subset=["value"])

        logger.info(f"  ✓ {series_id}: {len(df)} observations")
        return df

    except Exception as e:
        logger.error(f"  ✗ {series_id}: {e}")
        return None


def run():
    logger.info("=== FRED Collector ===")
    all_frames = []

    for series_id, label in FRED_SERIES.items():
        df = fetch_series(series_id, label)
        if df is not None:
            all_frames.append(df)

    if not all_frames:
        logger.error("No data collected from FRED.")
        return

    combined = pd.concat(all_frames, ignore_index=True)

    # Save raw
    out_path = RAW_DIR / "fred_indicators.parquet"
    combined.to_parquet(out_path, index=False)
    logger.success(f"Saved {len(combined)} rows → {out_path}")

    # Also save CSV for easy inspection
    combined.to_csv(RAW_DIR / "fred_indicators.csv", index=False)

    # Quick pivot for inspection
    pivot = combined.pivot_table(
        index="date", columns="series_id", values="value", aggfunc="first"
    )
    logger.info(f"\nSeries date range: {combined['date'].min()} → {combined['date'].max()}")
    logger.info(f"Series collected: {combined['series_id'].nunique()}")

    return combined


if __name__ == "__main__":
    run()
