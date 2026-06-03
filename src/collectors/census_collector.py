"""
Census ACS Collector — American Community Survey
Free API key: https://api.census.gov/data/key_signup.html

Fetches: Income by age, housing, education attainment, health insurance
Covers all 50 states + national level, Gen Z age brackets
"""

import os
import requests
import pandas as pd
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")
RAW_DIR = Path("data/raw/census")
RAW_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://api.census.gov/data/{year}/acs/acs1"

# ── ACS 1-Year Variables for Gen Z Analysis ──────────────────────────────
# Full variable list: https://api.census.gov/data/2022/acs/acs1/variables.json

ACS_VARIABLES = {
    # Income by age
    "B19037_002E": "Householder_under_25_income",
    "B19037_003E": "Householder_25_44_income",
    "B06011_001E": "Median_income_all",

    # Housing (tenure by age)
    "B25007_003E": "Owner_occupied_under25",
    "B25007_004E": "Owner_occupied_25_34",
    "B25007_012E": "Renter_occupied_under25",
    "B25007_013E": "Renter_occupied_25_34",

    # Gross rent as % of income
    "B25070_001E": "Renter_count_total",
    "B25070_007E": "Rent_30_34pct_income",
    "B25070_008E": "Rent_35_39pct_income",
    "B25070_009E": "Rent_40_49pct_income",
    "B25070_010E": "Rent_50plus_pct_income",  # Cost-burdened threshold

    # Education attainment 18-24
    "B15001_004E": "Male_18_24_less_HS",
    "B15001_005E": "Male_18_24_HS_diploma",
    "B15001_006E": "Male_18_24_some_college",
    "B15001_011E": "Female_18_24_less_HS",
    "B15001_012E": "Female_18_24_HS_diploma",
    "B15001_013E": "Female_18_24_some_college",

    # Health insurance (under 26 — key Gen Z threshold)
    "B27001_004E": "Male_under_6_insured",
    "B27001_007E": "Male_6_18_insured",
    "B27001_010E": "Male_19_25_insured",
    "B27001_013E": "Male_26_34_insured",

    # Employment status 16-24
    "B23001_008E": "Male_16_19_employed",
    "B23001_015E": "Male_20_21_employed",
    "B23001_022E": "Male_22_24_employed",
    "B23001_029E": "Male_25_29_employed",

    # Living arrangements (multigenerational — Gen Z moving back)
    "B09021_002E": "Living_with_parents_18_34",
}

YEARS = [2019, 2021, 2022, 2023]  # ACS 1-year (skip 2020 — COVID disruption)
GEO_ALL_STATES = "state:*"
GEO_NATIONAL = "us:1"


def fetch_acs(year: int, variables: list[str], geo: str) -> pd.DataFrame | None:
    """Fetch ACS data for a given year and geography."""
    var_str = "NAME," + ",".join(variables)
    url = BASE_URL.format(year=year)
    params = {
        "get": var_str,
        "for": geo,
        "key": CENSUS_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        raw = resp.json()

        # First row is headers
        headers = raw[0]
        rows = raw[1:]
        df = pd.DataFrame(rows, columns=headers)
        df["year"] = year

        # Convert numeric cols
        for col in variables:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df
    except Exception as e:
        logger.error(f"  Census {year} / {geo}: {e}")
        return None


def run():
    logger.info("=== Census ACS Collector ===")
    variables = list(ACS_VARIABLES.keys())

    national_frames = []
    state_frames = []

    for year in YEARS:
        logger.info(f"  Year {year}...")

        # National
        df_nat = fetch_acs(year, variables, GEO_NATIONAL)
        if df_nat is not None:
            df_nat["geo_level"] = "national"
            national_frames.append(df_nat)
            logger.info(f"    National: {len(df_nat)} rows")

        # All states
        df_states = fetch_acs(year, variables, GEO_ALL_STATES)
        if df_states is not None:
            df_states["geo_level"] = "state"
            state_frames.append(df_states)
            logger.info(f"    States: {len(df_states)} rows")

    # Combine and rename
    rename_map = {k: v for k, v in ACS_VARIABLES.items()}

    if national_frames:
        nat = pd.concat(national_frames).rename(columns=rename_map)
        nat.to_parquet(RAW_DIR / "acs_national.parquet", index=False)
        nat.to_csv(RAW_DIR / "acs_national.csv", index=False)
        logger.success(f"National saved: {len(nat)} rows")

    if state_frames:
        states = pd.concat(state_frames).rename(columns=rename_map)
        states.to_parquet(RAW_DIR / "acs_states.parquet", index=False)
        states.to_csv(RAW_DIR / "acs_states.csv", index=False)
        logger.success(f"States saved: {len(states)} rows")

    return nat if national_frames else None


if __name__ == "__main__":
    run()
