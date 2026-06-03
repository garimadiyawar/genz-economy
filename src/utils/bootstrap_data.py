"""
Data Bootstrap — Real data with offline fallback.

Run modes:
  python src/utils/bootstrap_data.py --mode real     # requires API keys + internet
  python src/utils/bootstrap_data.py --mode dev      # synthetic realistic data, works offline
  python src/utils/bootstrap_data.py --mode github   # pulls from free GitHub raw sources

For development and testing, --mode dev generates statistically realistic
data that mirrors actual BLS/FRED trends so the full pipeline runs cleanly.
"""

import io
import os
import sys
import numpy as np
import pandas as pd
import requests
from pathlib import Path
from datetime import datetime
from loguru import logger

# Single master seed — change this value to regenerate different but internally
# consistent synthetic data. All generators derive their seed from this.
DEV_SEED = 42

RAW_DIR = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)
for sub in ["fred", "bls", "census", "housing", "education", "news", "jobs"]:
    (RAW_DIR / sub).mkdir(exist_ok=True)

DATES_MONTHLY = pd.date_range("2010-01-01", "2025-12-01", freq="MS")
DATES_QUARTERLY = pd.date_range("2010-01-01", "2025-12-01", freq="QS")
DATES_ANNUAL = pd.date_range("2010-01-01", "2025-01-01", freq="YS")


# ═══════════════════════════════════════════════════════════════
# MODE 1: GITHUB — Free data, no API key needed
# ═══════════════════════════════════════════════════════════════

def fetch_github_sources() -> dict:
    """Pull real data from publicly accessible GitHub raw URLs."""
    results = {}

    sources = {
        "cpi": "https://raw.githubusercontent.com/datasets/cpi-us/master/data/cpiai.csv",
        "gdp": "https://raw.githubusercontent.com/datasets/gdp/main/data/gdp.csv",
    }

    for name, url in sources.items():
        try:
            r = requests.get(url, timeout=15)
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            results[name] = df
            logger.success(f"  ✓ {name}: {df.shape}")
        except Exception as e:
            logger.warning(f"  ✗ {name}: {e}")

    return results


# ═══════════════════════════════════════════════════════════════
# MODE 2: DEV — Synthetic realistic data (works 100% offline)
# ═══════════════════════════════════════════════════════════════

def make_fred_data() -> pd.DataFrame:
    np.random.seed(DEV_SEED)
    """
    Generate synthetic FRED-like time series that mirror actual trends:
    - CPI: steady rise 2010→2022, spike 2021-2023, normalizing 2024+
    - Rent CPI: consistently outpaces headline CPI
    - Wages: growth lagging rent, real wage compression post-2021
    - Student debt: linear growth $900B → $1.77T
    - Savings rate: high 2020 (stimulus), declining otherwise
    """
    n = len(DATES_MONTHLY)
    t = np.arange(n)

    # CPI All Items (base 1982=100, current ~315)
    cpi_base = 215
    cpi_trend = cpi_base + t * 0.42
    covid_spike = np.where((DATES_MONTHLY.year == 2021) | (DATES_MONTHLY.year == 2022),
                           (DATES_MONTHLY.year - 2020) * 4.5, 0)
    cpi = cpi_trend + covid_spike + np.random.normal(0, 0.3, n)

    # Rent CPI (rises ~1.5x faster than headline)
    rent_cpi = 230 + t * 0.68 + np.random.normal(0, 0.5, n)

    # Median weekly earnings (25-34): $650 → $1100
    wage = 650 + t * 1.65 + np.random.normal(0, 3, n)
    # Post-2020 bump from tight labor market
    wage += np.where(DATES_MONTHLY.year >= 2021, 45, 0)

    # Student loans outstanding ($B): $900B → $1.77T
    student_debt = 900 + t * (870 / n) + np.random.normal(0, 2, n)
    # Slight plateau 2020-2022 (COVID forbearance)
    student_debt -= np.where((DATES_MONTHLY.year >= 2020) & (DATES_MONTHLY.year <= 2022), 30, 0)

    # Savings rate: mean ~7%, spike to 33% in April 2020, decay back
    savings = 7 + np.random.normal(0, 0.8, n)
    savings[np.where(DATES_MONTHLY == '2020-04-01')[0][0]] = 33.0
    savings[np.where(DATES_MONTHLY.year == 2020)[0]] += 8

    # Median household income ($): $49K → $80K
    income = 49000 + t * (31000 / n) + np.random.normal(0, 200, n)

    # Home prices ($K → real): $173K → $420K
    home_price = 173000 + t * (247000 / n)
    home_price += np.where(DATES_MONTHLY.year >= 2020, 50000, 0)
    home_price += np.random.normal(0, 1000, n)

    # Build tidy long-format DataFrame matching fred_collector.py schema
    rows = []
    series_map = {
        "CPIAUCSL":        ("CPI All Urban Consumers", cpi),
        "CUSR0000SEHA":    ("CPI Rent of Primary Residence", rent_cpi),
        "LES1252881600Q":  ("Median Usual Weekly Earnings (Full-time)", wage),
        "MEHOINUSA672N":   ("Real Median Household Income", income),
        "SLOAS":           ("Student Loans Outstanding", student_debt),
        "PSAVERT":         ("Personal Saving Rate", savings),
        "MSPUS":           ("Median Sales Price of Houses", home_price),
    }
    for sid, (label, values) in series_map.items():
        for date, val in zip(DATES_MONTHLY, values):
            rows.append({"date": date, "series_id": sid, "label": label, "value": round(float(val), 2)})

    df = pd.DataFrame(rows)
    df.to_parquet(RAW_DIR / "fred/fred_indicators.parquet", index=False)
    df.to_csv(RAW_DIR / "fred/fred_indicators.csv", index=False)
    logger.success(f"FRED synthetic: {len(df)} rows ({df['series_id'].nunique()} series)")
    return df


def make_bls_data() -> pd.DataFrame:
    np.random.seed(DEV_SEED + 1)
    """
    Synthetic BLS employment data.
    Mirrors actual patterns: Great Recession recovery, tight 2019 market,
    COVID shock, fast recovery 2021-2022, cooling 2023-2024.
    """
    n = len(DATES_MONTHLY)
    t = np.arange(n)

    def unemployment_curve(base_rate, covid_spike_height):
        # Declining trend 2010-2019
        u = base_rate - t * (base_rate * 0.6 / (10 * 12))
        u = np.clip(u, base_rate * 0.35, base_rate)
        # COVID spike April 2020
        for i, d in enumerate(DATES_MONTHLY):
            if d.year == 2020 and d.month == 4:
                u[i] = covid_spike_height
            elif d.year == 2020 and d.month > 4:
                months_after = d.month - 4
                u[i] = covid_spike_height * (0.75 ** months_after) + base_rate * 0.4
        # Recovery: back near pre-COVID by mid-2022
        for i, d in enumerate(DATES_MONTHLY):
            if d.year >= 2021:
                u[i] = max(u[i], base_rate * 0.38 + np.random.normal(0, 0.2))
        return u + np.random.normal(0, 0.15, n)

    unemp_20_24 = unemployment_curve(14.5, 26.0)
    unemp_25_34 = unemployment_curve(7.8,  15.5)
    unemp_total = unemployment_curve(9.6,  14.7)
    u6_rate     = unemployment_curve(16.5, 22.8)

    # Employment-population ratio
    emp_pop_25_34 = 75 - t * 0.02 + np.where(DATES_MONTHLY.year >= 2021, 2, 0)
    emp_pop_25_34 += np.random.normal(0, 0.3, n)
    emp_pop_25_34[DATES_MONTHLY.year == 2020] -= 8

    # Wages by age group (weekly)
    wage_20_24 = 420 + t * 1.1 + np.where(DATES_MONTHLY.year >= 2021, 30, 0)
    wage_25_34 = 660 + t * 1.7 + np.where(DATES_MONTHLY.year >= 2021, 45, 0)

    rows = []
    series_map = {
        "LNS14000036": ("Unemployment_20-24", unemp_20_24),
        "LNS14000091": ("Unemployment_25-34", unemp_25_34),
        "LNS14000006": ("Unemployment_Total", unemp_total),
        "U6RATE":       ("U-6 Underemployment Rate", u6_rate),
        "LNS12300091":  ("Emp_Pop_Ratio_25-34", emp_pop_25_34),
        "LEU0252881600": ("Median_Weekly_Earnings_20-24", wage_20_24),
        "LEU0252881700": ("Median_Weekly_Earnings_25-34", wage_25_34),
        "LEU0254530000": ("Median_Weekly_Earnings_Full_Time", (wage_20_24 + wage_25_34) / 2),
    }
    for sid, (label, values) in series_map.items():
        for date, val in zip(DATES_MONTHLY, values):
            rows.append({
                "date": date, "series_id": sid,
                "label": label, "value": round(float(max(val, 0)), 2),
                "period_type": "M"
            })

    df = pd.DataFrame(rows)
    df.to_parquet(RAW_DIR / "bls/bls_indicators.parquet", index=False)
    df.to_csv(RAW_DIR / "bls/bls_indicators.csv", index=False)
    logger.success(f"BLS synthetic: {len(df)} rows ({df['series_id'].nunique()} series)")
    return df


def make_zillow_data() -> pd.DataFrame:
    np.random.seed(DEV_SEED + 2)
    """Synthetic metro-level rent data (Zillow ZORI style)."""
    metros = [
        ("New York", "NY"), ("Los Angeles", "CA"), ("Chicago", "IL"),
        ("Houston", "TX"), ("Phoenix", "AZ"), ("Philadelphia", "PA"),
        ("San Antonio", "TX"), ("San Diego", "CA"), ("Dallas", "TX"),
        ("San Jose", "CA"), ("Austin", "TX"), ("Jacksonville", "FL"),
        ("San Francisco", "CA"), ("Columbus", "OH"), ("Indianapolis", "IN"),
        ("Seattle", "WA"), ("Denver", "CO"), ("Nashville", "TN"),
        ("Boston", "MA"), ("Detroit", "MI"), ("Miami", "FL"),
        ("Portland", "OR"), ("Las Vegas", "NV"), ("Minneapolis", "MN"),
        ("Atlanta", "GA"), ("Charlotte", "NC"), ("Raleigh", "NC"),
        ("Salt Lake City", "UT"), ("Richmond", "VA"), ("Boise", "ID"),
    ]

    # Base rents calibrated to real 2024 approximate values
    base_rents = {
        "San Francisco": 3100, "San Jose": 2900, "New York": 2700,
        "Boston": 2500, "Seattle": 2200, "Los Angeles": 2400,
        "San Diego": 2300, "Miami": 2100, "Denver": 1900,
        "Austin": 1700, "Nashville": 1600, "Portland": 1800,
        "Chicago": 1700, "Atlanta": 1600, "Dallas": 1500,
        "Phoenix": 1450, "Houston": 1400, "Charlotte": 1400,
        "Raleigh": 1500, "Minneapolis": 1400, "Salt Lake City": 1500,
        "Las Vegas": 1400, "Indianapolis": 1200, "Columbus": 1200,
        "Detroit": 1100, "Philadelphia": 1700, "Jacksonville": 1300,
        "San Antonio": 1200, "Richmond": 1400, "Boise": 1500,
    }

    rows = []
    for metro, state in metros:
        base = base_rents.get(metro, 1400)
        for i, date in enumerate(DATES_MONTHLY):
            growth = 1 + (i / len(DATES_MONTHLY)) * 0.65
            covid_bump = 1.18 if date.year >= 2021 else 1.0
            seasonal = 1 + 0.02 * np.sin(2 * np.pi * date.month / 12)
            rent = base * growth * covid_bump * seasonal + np.random.normal(0, 15)
            rows.append({
                "date": date, "RegionName": metro, "StateName": state,
                "value": round(max(rent, 800), 0), "series": "rent_index_metros"
            })

    df = pd.DataFrame(rows)
    df.to_parquet(RAW_DIR / "housing/zillow_rent_index_metros.parquet", index=False)
    df.to_csv(RAW_DIR / "housing/zillow_rent_index_metros.csv", index=False)
    logger.success(f"Zillow rent synthetic: {len(df)} rows ({len(metros)} metros)")
    return df


def make_college_scorecard() -> pd.DataFrame:
    """Synthetic college debt/earnings data mirroring Scorecard distributions."""
    np.random.seed(DEV_SEED + 3)
    schools = [
        ("Harvard University", "MA", 54000, 195000),
        ("MIT", "MA", 55000, 210000),
        ("Stanford University", "CA", 56000, 195000),
        ("State University - Flagship", "OH", 12000, 62000),
        ("Community College", "CA", 3500, 38000),
        ("For-Profit Online U", "FL", 15000, 31000),
        ("Liberal Arts College", "VT", 52000, 51000),
        ("HBCU", "GA", 18000, 43000),
        ("Large Public University", "TX", 11000, 58000),
        ("Art & Design School", "NY", 48000, 39000),
        ("Engineering School", "CA", 35000, 95000),
        ("Nursing College", "TX", 22000, 62000),
        ("Business School", "IL", 38000, 75000),
        ("Teachers College", "NY", 30000, 45000),
        ("Pharmacy School", "NC", 28000, 82000),
        ("Law School (undergrad feeder)", "VA", 42000, 68000),
        ("Midwest State U", "KS", 9000, 52000),
        ("Southern Regional U", "AL", 10000, 41000),
        ("Online State University", "AZ", 11000, 49000),
        ("Private Religious College", "IN", 33000, 47000),
    ]

    rows = []
    for name, state, tuition, median_earnings_6yr in schools:
        # Debt roughly correlated with tuition but not perfectly
        median_debt = tuition * 2.8 * np.random.uniform(0.7, 1.3)
        earnings_10yr = median_earnings_6yr * np.random.uniform(1.2, 1.5)
        completion = np.random.uniform(0.35, 0.92)
        first_gen = np.random.uniform(0.10, 0.55)

        rows.append({
            "school.name": name,
            "school.state": state,
            "latest.cost.tuition.in_state": tuition,
            "latest.aid.median_debt.completers.overall": round(median_debt),
            "latest.earnings.6_yrs_after_entry.median": median_earnings_6yr,
            "latest.earnings.10_yrs_after_entry.median": round(earnings_10yr),
            "latest.completion.completion_rate_4yr_150nt": round(completion, 3),
            "latest.student.demographics.share_first_generation": round(first_gen, 3),
        })

    df = pd.DataFrame(rows)
    df.to_parquet(RAW_DIR / "education/college_scorecard.parquet", index=False)
    df.to_csv(RAW_DIR / "education/college_scorecard.csv", index=False)
    logger.success(f"College Scorecard synthetic: {len(df)} schools")
    return df


def make_jobs_data() -> pd.DataFrame:
    """Synthetic job postings data."""
    np.random.seed(DEV_SEED + 4)
    sectors = ["Technology", "Healthcare", "Finance", "Education",
               "Retail/Service", "Creative", "Trades", "Government"]
    work_types = ["remote", "hybrid", "in_person"]
    degree_reqs = ["required", "preferred", "not_required", "unspecified"]

    rows = []
    for i in range(500):
        sector = np.random.choice(sectors, p=[0.22, 0.18, 0.12, 0.08, 0.18, 0.10, 0.07, 0.05])
        wtype = np.random.choice(work_types, p=[0.30, 0.35, 0.35])
        # Tech/Finance higher salaries, Retail lower
        salary_base = {"Technology": 95000, "Finance": 85000, "Healthcare": 72000,
                       "Education": 48000, "Retail/Service": 35000, "Creative": 58000,
                       "Trades": 62000, "Government": 65000}.get(sector, 55000)
        sal_min = salary_base * np.random.uniform(0.75, 0.95)
        sal_max = sal_min * np.random.uniform(1.15, 1.45)
        is_entry = np.random.random() < 0.28
        deg_req = np.random.choice(degree_reqs, p=[0.35, 0.30, 0.15, 0.20])

        rows.append({
            "source": np.random.choice(["remotive", "arbeitnow", "usajobs"]),
            "job_id": f"job_{i:04d}",
            "title": f"{'Junior ' if is_entry else ''}{sector} Analyst",
            "company": f"Company_{i % 50}",
            "sector": sector,
            "location": np.random.choice(["Remote", "New York", "Austin", "Chicago", "Denver"]),
            "work_type": wtype,
            "salary_min": round(sal_min),
            "salary_max": round(sal_max),
            "is_entry_level": is_entry,
            "degree_requirement": deg_req,
            "posted_at": pd.Timestamp("2025-01-01") + pd.Timedelta(days=int(np.random.uniform(0, 365))),
            "tags": f"{sector.lower()},analyst",
        })

    df = pd.DataFrame(rows)
    df.to_parquet(RAW_DIR / "jobs/job_postings.parquet", index=False)
    df.to_csv(RAW_DIR / "jobs/job_postings.csv", index=False)
    logger.success(f"Jobs synthetic: {len(df)} postings")
    return df


def make_news_data() -> pd.DataFrame:
    """Synthetic news sentiment data."""
    np.random.seed(DEV_SEED + 5)
    queries = ["Gen Z economy", "Gen Z housing", "Gen Z student debt",
               "Gen Z job market", "Gen Z financial stress"]
    outlets = ["NYT", "WSJ", "NPR", "Reuters", "CNN", "Bloomberg", "Axios"]

    rows = []
    for date in pd.date_range("2022-01-01", "2025-12-01", freq="W"):
        for query in queries:
            for _ in range(np.random.randint(2, 8)):
                # Sentiment trending slightly more negative post-2023 (cost of living crisis)
                base_sentiment = -0.05 - (0.03 if date.year >= 2023 else 0)
                rows.append({
                    "source": "synthetic",
                    "query": query,
                    "title": f"Article about {query} ({date.date()})",
                    "published_at": date,
                    "outlet": np.random.choice(outlets),
                    "compound_score": base_sentiment + np.random.normal(0, 0.25),
                    "sentiment": np.random.choice(["positive", "negative", "neutral"],
                                                  p=[0.28, 0.42, 0.30]),
                    "article_id": f"art_{date}_{query[:5]}_{_}",
                })

    df = pd.DataFrame(rows)
    df.to_parquet(RAW_DIR / "news/news_articles.parquet", index=False)
    df.to_csv(RAW_DIR / "news/news_articles.csv", index=False)
    logger.success(f"News synthetic: {len(df)} articles")
    return df


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def _real_data_exists() -> bool:
    """Check whether any real collected data is already on disk."""
    sentinels = [
        RAW_DIR / "fred/fred_indicators.parquet",
        RAW_DIR / "bls/bls_indicators.parquet",
        RAW_DIR / "housing/zillow_rent_index_metros.parquet",
    ]
    return any(p.exists() for p in sentinels)


def run_dev_mode(force: bool = False):
    logger.info("=== Bootstrap: DEV MODE (synthetic realistic data) ===")

    if _real_data_exists() and not force:
        logger.error(
            "Real collected data already exists in data/raw/. "
            "Refusing to overwrite with synthetic data.\n"
            "To force synthetic generation anyway, pass --force or call run_dev_mode(force=True)."
        )
        return None

    if _real_data_exists() and force:
        logger.warning("--force flag set: overwriting existing real data with synthetic data.")

    fred   = make_fred_data()
    bls    = make_bls_data()
    zillow = make_zillow_data()
    score  = make_college_scorecard()
    jobs   = make_jobs_data()
    news   = make_news_data()
    logger.success("\nAll synthetic datasets generated. Run ETL pipeline next:")
    logger.info("  python src/etl/pipeline.py")
    return {"fred": fred, "bls": bls, "zillow": zillow,
            "scorecard": score, "jobs": jobs, "news": news}


def run_github_mode():
    logger.info("=== Bootstrap: GITHUB MODE (free public datasets) ===")
    results = fetch_github_sources()
    # Supplement with synthetic for sources not on GitHub
    make_bls_data()
    make_zillow_data()
    make_jobs_data()
    make_news_data()
    logger.success("GitHub + synthetic data ready.")
    return results


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dev", "github", "real"], default="dev")
    parser.add_argument("--force", action="store_true", help="Overwrite existing real data with synthetic (dev mode only)")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    if args.mode == "dev":
        run_dev_mode(force=args.force)
    elif args.mode == "github":
        run_github_mode()
    else:
        logger.info("Real mode: use src/collectors/run_all.py with API keys configured.")
