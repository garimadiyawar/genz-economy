"""
Education & Housing Collectors

1. College Scorecard — student debt, earnings outcomes by field of study
   API key: https://api.data.gov/signup/ (same key works for many .gov APIs)

2. Zillow Research Data — rent index, home values (no API key required)
   Direct CSV downloads from Zillow's public research portal
"""

import os
import io
import requests
import pandas as pd
from pathlib import Path
from loguru import logger
from dotenv import load_dotenv

load_dotenv()
SCORECARD_KEY = os.getenv("COLLEGE_SCORECARD_API_KEY")

RAW_DIR = Path("data/raw")
EDU_DIR = RAW_DIR / "education"
HOUSING_DIR = RAW_DIR / "housing"
EDU_DIR.mkdir(parents=True, exist_ok=True)
HOUSING_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# COLLEGE SCORECARD
# ═══════════════════════════════════════════════════════════════

SCORECARD_BASE = "https://api.data.gov/ed/collegescorecard/v1/schools"

SCORECARD_FIELDS = ",".join([
    "school.name",
    "school.state",
    "school.school_url",
    "school.institutional_characteristics.level",
    "latest.student.size",
    "latest.cost.tuition.in_state",
    "latest.cost.tuition.out_of_state",
    "latest.aid.median_debt.completers.overall",
    "latest.aid.median_debt.noncompleters",
    "latest.repayment.3_yr_repayment.overall",
    "latest.earnings.10_yrs_after_entry.median",
    "latest.earnings.6_yrs_after_entry.median",
    "latest.completion.completion_rate_4yr_150nt",
    "latest.student.demographics.share_first_generation",
    "latest.academics.program_percentage.business_marketing",
    "latest.academics.program_percentage.computer",
    "latest.academics.program_percentage.health",
    "latest.academics.program_percentage.social_science",
    "latest.academics.program_percentage.humanities",
])


def fetch_college_scorecard(pages: int = 5) -> pd.DataFrame:
    """Fetch college data — debt vs earnings outcomes."""
    logger.info("  Fetching College Scorecard...")
    all_results = []

    for page in range(pages):
        params = {
            "api_key": SCORECARD_KEY,
            "fields": SCORECARD_FIELDS,
            "per_page": 100,
            "page": page,
            "school.degrees_awarded.predominant": "3",  # Primarily bachelor's
            "_sort": "latest.student.size:desc",
        }
        try:
            resp = requests.get(SCORECARD_BASE, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            all_results.extend(results)
            logger.info(f"    Page {page+1}: {len(results)} schools")
        except Exception as e:
            logger.error(f"    Page {page+1} failed: {e}")
            break

    if not all_results:
        return pd.DataFrame()

    df = pd.json_normalize(all_results)
    df.to_parquet(EDU_DIR / "college_scorecard.parquet", index=False)
    df.to_csv(EDU_DIR / "college_scorecard.csv", index=False)
    logger.success(f"  Scorecard: {len(df)} institutions saved")
    return df


# ═══════════════════════════════════════════════════════════════
# ZILLOW RESEARCH DATA (no API key required)
# ═══════════════════════════════════════════════════════════════

ZILLOW_DATASETS = {
    # Zillow Observed Rent Index (ZORI) — all homes, monthly
    "rent_index_metros": "https://files.zillowstatic.com/research/public_csvs/zori/Metro_zori_uc_sfrcondomfr_sm_sa_month.csv",

    # Zillow Home Value Index (ZHVI) — metro level
    "home_value_metros": "https://files.zillowstatic.com/research/public_csvs/zhvi/Metro_zhvi_uc_sfrcondo_tier_0.33_0.67_sm_sa_month.csv",

    # Days to pending (market speed indicator)
    "days_to_pending": "https://files.zillowstatic.com/research/public_csvs/med_dtp/Metro_med_dtp_uc_sfrcondo_sm_month.csv",
}


def fetch_zillow_datasets() -> dict[str, pd.DataFrame]:
    """Download Zillow research CSVs directly."""
    logger.info("  Fetching Zillow Research Data...")
    results = {}

    for name, url in ZILLOW_DATASETS.items():
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            df = pd.read_csv(io.StringIO(resp.text))

            # Melt wide format (dates as columns) to long format
            id_cols = [c for c in df.columns if not c.startswith("20") and not c.startswith("19")]
            date_cols = [c for c in df.columns if c.startswith("20") or c.startswith("19")]

            if date_cols:
                df_long = df.melt(id_vars=id_cols, value_vars=date_cols,
                                  var_name="date", value_name="value")
                df_long["date"] = pd.to_datetime(df_long["date"])
                df_long["series"] = name
                df_long = df_long.dropna(subset=["value"])
            else:
                df_long = df

            df_long.to_parquet(HOUSING_DIR / f"zillow_{name}.parquet", index=False)
            df_long.to_csv(HOUSING_DIR / f"zillow_{name}.csv", index=False)
            results[name] = df_long
            logger.success(f"  {name}: {len(df_long)} rows")

        except Exception as e:
            logger.error(f"  {name} failed: {e}")

    return results


# ═══════════════════════════════════════════════════════════════
# HUD Fair Market Rents (backup for housing)
# ═══════════════════════════════════════════════════════════════

def fetch_hud_fmr():
    """HUD Fair Market Rents — key affordability benchmark."""
    # HUD publishes annual FMR data as downloadable CSV
    # https://www.huduser.gov/portal/datasets/fmr.html
    # We'll download the most recent year

    logger.info("  Note: HUD FMR data must be manually downloaded from:")
    logger.info("  https://www.huduser.gov/portal/datasets/fmr.html")
    logger.info("  Download 'FY2024 FMR' CSV and place in data/raw/housing/")
    logger.info("  File: FY2024_4050_FMRs_rev.csv")


def run_education():
    logger.info("=== Education Collector ===")
    return fetch_college_scorecard()


def run_housing():
    logger.info("=== Housing Collector ===")
    results = fetch_zillow_datasets()
    fetch_hud_fmr()
    return results


if __name__ == "__main__":
    run_education()
    run_housing()
