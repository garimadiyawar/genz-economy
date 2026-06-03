"""
Job Market Analyzer — Gen Z Employment Quality
Uses free sources: Indeed RSS, USAJobs API, Remotive API (remote jobs)

Tracks:
- Job posting volume by sector
- Entry-level vs experienced ratios
- Remote vs in-person trends
- Wage ranges in postings
- Degree requirement trends (degree inflation vs skills-based hiring)

Usage: python src/news_parser/job_market.py
"""

import re
import time
import hashlib
import requests
import feedparser
import pandas as pd
import os
from pathlib import Path
from datetime import datetime
from loguru import logger
from collections import defaultdict

JOB_DIR = Path("data/raw/jobs")
JOB_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR = Path("data/exports")
EXPORT_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# JOB CLASSIFICATION CONFIG
# ═══════════════════════════════════════════════════════════════

SECTORS = {
    "Technology":     ["software", "developer", "engineer", "data", "cloud", "AI", "cybersecurity", "devops", "python", "javascript"],
    "Healthcare":     ["nurse", "medical", "clinical", "pharmacy", "therapist", "healthcare", "doctor", "dental"],
    "Finance":        ["analyst", "finance", "accounting", "banking", "investment", "financial", "audit"],
    "Education":      ["teacher", "instructor", "tutor", "education", "curriculum", "school"],
    "Retail/Service": ["retail", "customer service", "cashier", "barista", "food", "hospitality", "server", "driver"],
    "Creative":       ["designer", "writer", "content", "marketing", "social media", "ux", "graphic"],
    "Trades":         ["electrician", "plumber", "mechanic", "construction", "hvac", "welder"],
    "Government":     ["federal", "government", "public sector", "policy", "military", "civil service"],
}

ENTRY_LEVEL_SIGNALS = [
    "entry level", "entry-level", "new grad", "recent graduate",
    "0-2 years", "0-1 year", "junior", "associate level",
    "no experience required", "will train",
]

DEGREE_SIGNALS = {
    "required":    ["degree required", "bachelor's required", "must have degree", "bs required", "ba required"],
    "preferred":   ["degree preferred", "bachelor's preferred", "degree a plus"],
    "not_required":["no degree required", "degree not required", "skills-based", "equivalent experience"],
}

REMOTE_SIGNALS     = ["remote", "work from home", "wfh", "fully remote", "100% remote"]
HYBRID_SIGNALS     = ["hybrid", "flexible location", "2 days in office", "3 days in office"]
IN_PERSON_SIGNALS  = ["on-site", "onsite", "in-office", "in person", "no remote"]

SALARY_PATTERN = re.compile(
    r'\$[\d,]+(?:\.\d+)?(?:k|K)?(?:\s*[-–]\s*\$[\d,]+(?:\.\d+)?(?:k|K)?)?(?:\s*(?:per|/)\s*(?:year|yr|hour|hr|month))?'
)


# ═══════════════════════════════════════════════════════════════
# SOURCE 1: Remotive API (remote tech jobs — no key needed)
# ═══════════════════════════════════════════════════════════════

def fetch_remotive(category: str = None) -> list[dict]:
    """
    Remotive.com — free remote job API, no key required.
    https://remotive.com/api/remote-jobs
    """
    url = "https://remotive.com/api/remote-jobs"
    params = {}
    if category:
        params["category"] = category

    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
        results = []
        for j in jobs:
            desc = j.get("description", "")
            title = j.get("title", "")
            text = f"{title} {desc}".lower()

            results.append({
                "source":           "remotive",
                "job_id":           hashlib.md5(str(j.get("id", title)).encode()).hexdigest(),
                "title":            title,
                "company":          j.get("company_name"),
                "sector":           classify_sector(text),
                "location":         "Remote",
                "work_type":        "remote",
                "salary_text":      j.get("salary", ""),
                "salary_min":       extract_salary_min(j.get("salary", "") + " " + desc),
                "salary_max":       extract_salary_max(j.get("salary", "") + " " + desc),
                "is_entry_level":   is_entry_level(text),
                "degree_requirement": classify_degree(text),
                "posted_at":        j.get("publication_date"),
                "tags":             ", ".join(j.get("tags", [])[:5]),
                "url":              j.get("url"),
            })
        logger.info(f"  Remotive: {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"Remotive error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# SOURCE 2: USAJobs API (federal — no key for basic use)
# ═══════════════════════════════════════════════════════════════

def fetch_usajobs(keyword: str = "analyst", grade: str = "05,07,09") -> list[dict]:
    """
    USAJobs.gov - entry-level federal positions (GS-05 to GS-09).
    Register free at: https://developer.usajobs.gov/
    Add USAJOBS_EMAIL and USAJOBS_API_KEY to your .env file.
    """
    usajobs_key   = os.getenv("USAJOBS_API_KEY", "")
    usajobs_email = os.getenv("USAJOBS_EMAIL", "")
    if not usajobs_key or not usajobs_email:
        logger.warning("  USAJobs skipped - add USAJOBS_EMAIL + USAJOBS_API_KEY to .env")
        return []
    url = "https://data.usajobs.gov/api/search"
    headers = {
        "Host":              "data.usajobs.gov",
        "User-Agent":        usajobs_email,
        "Authorization-Key": usajobs_key,
    }
    params = {
        "Keyword":        keyword,
        "GradeMin":       "05",
        "GradeMax":       "09",
        "ResultsPerPage": 50,
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        jobs_raw = resp.json().get("SearchResult", {}).get("SearchResultItems", [])
        results = []
        for item in jobs_raw:
            j = item.get("MatchedObjectDescriptor", {})
            title = j.get("PositionTitle", "")
            text = title.lower()
            salary_raw = j.get("PositionRemuneration", [{}])[0]

            results.append({
                "source":           "usajobs",
                "job_id":           hashlib.md5(j.get("PositionID", title).encode()).hexdigest(),
                "title":            title,
                "company":          j.get("DepartmentName"),
                "sector":           "Government",
                "location":         j.get("PositionLocation", [{}])[0].get("CityName", ""),
                "work_type":        classify_work_type(title + " " + j.get("UserArea", {}).get("Details", {}).get("TeleworkEligible", "")),
                "salary_text":      f"{salary_raw.get('MinimumRange', '')} - {salary_raw.get('MaximumRange', '')}",
                "salary_min":       safe_float(salary_raw.get("MinimumRange")),
                "salary_max":       safe_float(salary_raw.get("MaximumRange")),
                "is_entry_level":   True,  # GS-05/07/09 are entry-level
                "degree_requirement": "preferred",
                "posted_at":        j.get("PublicationStartDate"),
                "tags":             "",
                "url":              j.get("PositionURI"),
            })
        logger.info(f"  USAJobs '{keyword}': {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"USAJobs error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# SOURCE 3: Arbeitnow (free job board API — no key)
# ═══════════════════════════════════════════════════════════════

def fetch_arbeitnow() -> list[dict]:
    """
    Arbeitnow free job board API.
    https://www.arbeitnow.com/api/job-board-api
    Covers remote + international roles.
    """
    url = "https://www.arbeitnow.com/api/job-board-api"
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        jobs = resp.json().get("data", [])
        results = []
        for j in jobs[:100]:
            desc = j.get("description", "")
            title = j.get("title", "")
            text = f"{title} {desc}".lower()

            results.append({
                "source":           "arbeitnow",
                "job_id":           hashlib.md5(j.get("slug", title).encode()).hexdigest(),
                "title":            title,
                "company":          j.get("company_name"),
                "sector":           classify_sector(text),
                "location":         j.get("location", ""),
                "work_type":        "remote" if j.get("remote") else classify_work_type(text),
                "salary_text":      "",
                "salary_min":       extract_salary_min(text),
                "salary_max":       extract_salary_max(text),
                "is_entry_level":   is_entry_level(text),
                "degree_requirement": classify_degree(text),
                "posted_at":        j.get("created_at"),
                "tags":             ", ".join(j.get("tags", [])[:5]),
                "url":              j.get("url"),
            })
        logger.info(f"  Arbeitnow: {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"Arbeitnow error: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# CLASSIFICATION HELPERS
# ═══════════════════════════════════════════════════════════════

def classify_sector(text: str) -> str:
    text = text.lower()
    for sector, keywords in SECTORS.items():
        if any(kw.lower() in text for kw in keywords):
            return sector
    return "Other"


def is_entry_level(text: str) -> bool:
    return any(sig in text.lower() for sig in ENTRY_LEVEL_SIGNALS)


def classify_degree(text: str) -> str:
    text = text.lower()
    for req_type, signals in DEGREE_SIGNALS.items():
        if any(sig in text for sig in signals):
            return req_type
    return "unspecified"


def classify_work_type(text: str) -> str:
    text = text.lower()
    if any(s in text for s in REMOTE_SIGNALS):    return "remote"
    if any(s in text for s in HYBRID_SIGNALS):    return "hybrid"
    if any(s in text for s in IN_PERSON_SIGNALS): return "in_person"
    return "unspecified"


def safe_float(val) -> float | None:
    try:
        return float(str(val).replace(",", "").replace("$", ""))
    except:
        return None


# Salary bounds: realistic US annual range ($15k min wage equiv → $500k max)
SALARY_ANNUAL_MIN = 15_000
SALARY_ANNUAL_MAX = 500_000
HOURLY_THRESHOLD  = 200   # values below this are treated as hourly rates


def _annualize(val: float, original_text: str) -> float | None:
    """Convert a raw salary value to annual. Returns None if outside plausible range."""
    text_lower = original_text.lower()
    # Explicit hourly signal
    if any(kw in text_lower for kw in ["/hr", "/hour", "per hour", "hourly"]):
        annual = val * 2080
    # Explicit monthly signal
    elif any(kw in text_lower for kw in ["/month", "per month", "monthly"]):
        annual = val * 12
    # K suffix means thousands
    elif "k" in text_lower and val < 1000:
        annual = val * 1000
    # Heuristic: very small numbers are likely hourly (< $200)
    elif val < HOURLY_THRESHOLD:
        annual = val * 2080
    else:
        annual = val

    if SALARY_ANNUAL_MIN <= annual <= SALARY_ANNUAL_MAX:
        return annual
    return None  # outside plausible range — discard rather than corrupt data


def extract_salary_min(text: str) -> float | None:
    matches = SALARY_PATTERN.findall(text)
    if not matches:
        return None
    try:
        first = matches[0].replace("$", "").replace(",", "").split("-")[0].strip()
        val = float(re.sub(r'[^\d.]', '', first))
        return _annualize(val, matches[0])
    except Exception:
        return None


def extract_salary_max(text: str) -> float | None:
    matches = SALARY_PATTERN.findall(text)
    if not matches or "-" not in matches[0]:
        return None
    try:
        parts = matches[0].replace("$", "").replace(",", "").split("-")
        if len(parts) < 2:
            return None
        val = float(re.sub(r'[^\d.]', '', parts[1].strip()))
        return _annualize(val, matches[0])
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════════
# ANALYSIS: Job Market Quality Index
# ═══════════════════════════════════════════════════════════════

def compute_job_market_metrics(df: pd.DataFrame) -> dict:
    """Compute Gen Z relevant job market quality metrics."""
    total = len(df)
    if total == 0:
        return {}

    metrics = {
        "total_postings":           total,
        "entry_level_pct":          round(df["is_entry_level"].mean() * 100, 1),
        "remote_pct":               round((df["work_type"] == "remote").mean() * 100, 1),
        "hybrid_pct":               round((df["work_type"] == "hybrid").mean() * 100, 1),
        "degree_required_pct":      round((df["degree_requirement"] == "required").mean() * 100, 1),
        "degree_preferred_pct":     round((df["degree_requirement"] == "preferred").mean() * 100, 1),
        "no_degree_pct":            round((df["degree_requirement"] == "not_required").mean() * 100, 1),
        "median_salary_min":        df["salary_min"].median(),
        "median_salary_max":        df["salary_max"].median(),
        "sector_distribution":      df["sector"].value_counts().to_dict(),
        "work_type_distribution":   df["work_type"].value_counts().to_dict(),
    }

    logger.info("\n=== Job Market Snapshot ===")
    logger.info(f"  Total postings analyzed: {total:,}")
    logger.info(f"  Entry-level: {metrics['entry_level_pct']}%")
    logger.info(f"  Remote:      {metrics['remote_pct']}%")
    logger.info(f"  Degree req'd:{metrics['degree_required_pct']}%")
    logger.info(f"  Median salary range: ${metrics['median_salary_min']:,.0f} – ${metrics['median_salary_max']:,.0f}" if metrics['median_salary_min'] else "  Salary data sparse")

    return metrics


def export_for_tableau(df: pd.DataFrame):
    """Export job market data for Tableau dashboards."""
    # 1. Full postings (with key fields)
    export_cols = ["source", "title", "company", "sector", "location", "work_type",
                   "salary_min", "salary_max", "is_entry_level", "degree_requirement",
                   "posted_at", "tags"]
    clean = df[[c for c in export_cols if c in df.columns]].copy()
    clean.to_csv(EXPORT_DIR / "tableau_job_postings.csv", index=False)

    # 2. Sector summary
    sector_summary = df.groupby("sector").agg(
        count          = ("job_id", "count"),
        entry_level_pct= ("is_entry_level", lambda x: round(x.mean()*100,1)),
        remote_pct     = ("work_type", lambda x: round((x=="remote").mean()*100,1)),
        median_sal_min = ("salary_min", "median"),
        median_sal_max = ("salary_max", "median"),
    ).reset_index()
    sector_summary.to_csv(EXPORT_DIR / "tableau_job_sectors.csv", index=False)

    # 3. Degree requirement trend
    degree_dist = df.groupby(["sector", "degree_requirement"]).size().reset_index(name="count")
    degree_dist.to_csv(EXPORT_DIR / "tableau_degree_requirements.csv", index=False)

    logger.success(f"Job exports → {EXPORT_DIR}/")


def run():
    logger.info("=== Job Market Analyzer ===")
    all_jobs = []

    all_jobs.extend(fetch_remotive())
    time.sleep(1)
    all_jobs.extend(fetch_arbeitnow())
    time.sleep(1)
    all_jobs.extend(fetch_usajobs("analyst"))
    time.sleep(1)
    all_jobs.extend(fetch_usajobs("coordinator"))

    if not all_jobs:
        logger.warning("No job data collected.")
        return pd.DataFrame()

    df = pd.DataFrame(all_jobs).drop_duplicates(subset=["job_id"])
    df["posted_at"] = pd.to_datetime(df["posted_at"], errors="coerce").dt.strftime("%Y-%m-%d")
    df.to_parquet(JOB_DIR / "job_postings.parquet", index=False)
    df.to_csv(JOB_DIR / "job_postings.csv", index=False)
    logger.success(f"Saved {len(df)} job postings")

    metrics = compute_job_market_metrics(df)
    export_for_tableau(df)

    return df


if __name__ == "__main__":
    run()
