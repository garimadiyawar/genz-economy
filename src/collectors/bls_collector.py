"""
BLS Collector — Bureau of Labor Statistics
Free data, no API key required for basic access.
Docs: https://www.bls.gov/developers/

Fetches: Employment by age group, wages, gig economy indicators
"""

import json
import time
import requests
import pandas as pd
from pathlib import Path
from loguru import logger

RAW_DIR = Path("data/raw/bls")
RAW_DIR.mkdir(parents=True, exist_ok=True)

BLS_API_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# ── BLS Series IDs relevant to Gen Z ─────────────────────────────────────
# Format: LNS14000XXX = unemployment by age
# CES = Current Employment Statistics (payroll)
# ECI = Employment Cost Index

BLS_SERIES = {
    # Unemployment by age (seasonally adjusted)
    "LNS14000012": "Unemployment_16-19",
    "LNS14000036": "Unemployment_20-24",
    "LNS14000091": "Unemployment_25-34",
    "LNS14000006": "Unemployment_Total",

    # Labor force participation
    "LNS11300036": "LFPR_20-24",
    "LNS11300091": "LFPR_25-34",

    # Employment-population ratio
    "LNS12300036": "Emp_Pop_Ratio_20-24",
    "LNS12300091": "Emp_Pop_Ratio_25-34",

    # Median weekly earnings (quarterly)
    "LEU0254530000": "Median_Weekly_Earnings_Full_Time",
    "LEU0252881600": "Median_Weekly_Earnings_20-24",
    "LEU0252881700": "Median_Weekly_Earnings_25-34",

    # CPI components
    "CUSR0000SA0":  "CPI_All_Items",
    "CUSR0000SEHA": "CPI_Rent",
    "CUUR0000SAF1": "CPI_Food",
    "CUUR0000SETB01": "CPI_Gasoline",
}

START_YEAR = 2010
from datetime import datetime as _dt
END_YEAR   = _dt.today().year

HEADERS = {"Content-type": "application/json"}


def fetch_batch(series_ids: list[str], start: int, end: int) -> list[dict]:
    """BLS API accepts up to 50 series per request (v2)."""
    payload = json.dumps({
        "seriesid": series_ids,
        "startyear": str(start),
        "endyear": str(end),
    })
    resp = requests.post(BLS_API_URL, data=payload, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("Results", {}).get("series", [])


def parse_series(series_list: list[dict], label_map: dict) -> pd.DataFrame:
    """Parse BLS API response into tidy DataFrame."""
    rows = []
    for s in series_list:
        sid = s["seriesID"]
        label = label_map.get(sid, sid)
        for obs in s.get("data", []):
            # BLS uses 'M01'-'M12' for months, 'Q01'-'Q04' for quarters, 'A01' for annual
            period = obs["period"]
            year = int(obs["year"])

            if period.startswith("M"):
                month = int(period[1:])
                date = pd.Timestamp(year=year, month=month, day=1)
            elif period.startswith("Q"):
                quarter = int(period[1:])
                month = (quarter - 1) * 3 + 1
                date = pd.Timestamp(year=year, month=month, day=1)
            elif period == "A01":
                date = pd.Timestamp(year=year, month=1, day=1)
            else:
                continue

            try:
                value = float(obs["value"])
            except (ValueError, TypeError):
                continue

            rows.append({
                "date": date,
                "series_id": sid,
                "label": label,
                "value": value,
                "period_type": period[0],  # M, Q, or A
            })
    return pd.DataFrame(rows)


def run():
    logger.info("=== BLS Collector ===")
    all_frames = []
    series_list = list(BLS_SERIES.keys())

    # BLS API allows max 50 series per call; chunk them
    chunk_size = 25
    for i in range(0, len(series_list), chunk_size):
        chunk = series_list[i:i + chunk_size]
        logger.info(f"  Fetching batch {i//chunk_size + 1}: {len(chunk)} series")

        try:
            raw = fetch_batch(chunk, START_YEAR, END_YEAR)
            df = parse_series(raw, BLS_SERIES)
            all_frames.append(df)
            logger.info(f"    → {len(df)} observations")
        except Exception as e:
            logger.error(f"  Batch failed: {e}")

        time.sleep(1)  # Be polite to BLS

    if not all_frames:
        logger.error("No BLS data collected.")
        return

    combined = pd.concat(all_frames, ignore_index=True)
    combined = combined.sort_values(["series_id", "date"])

    out_path = RAW_DIR / "bls_indicators.parquet"
    combined.to_parquet(out_path, index=False)
    combined.to_csv(RAW_DIR / "bls_indicators.csv", index=False)

    logger.success(f"Saved {len(combined)} rows → {out_path}")
    logger.info(f"Series: {combined['series_id'].nunique()}")
    logger.info(f"Date range: {combined['date'].min()} → {combined['date'].max()}")

    return combined


if __name__ == "__main__":
    run()
