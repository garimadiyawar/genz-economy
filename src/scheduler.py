"""
Auto-Refresh Scheduler
Keeps all data current without manual effort.

Two modes:
  1. Local schedule (runs while your machine is on)
  2. GitHub Actions config (runs in cloud, free tier)

Usage (local): python src/scheduler.py
"""

import schedule
import time
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from loguru import logger

logger.add("logs/scheduler.log", rotation="1 week", retention="1 month")


def run_step(script_path: str, label: str) -> bool:
    """Run a Python script as subprocess and log result."""
    logger.info(f"  ▶ {label}...")
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True, text=True, timeout=600,
            cwd=Path(__file__).parent.parent  # project root
        )
        if result.returncode == 0:
            logger.success(f"  ✓ {label}")
            return True
        else:
            logger.error(f"  ✗ {label}: {result.stderr[-500:]}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"  ✗ {label}: Timed out after 10 minutes")
        return False
    except Exception as e:
        logger.error(f"  ✗ {label}: {e}")
        return False


def full_pipeline():
    """Run the complete data pipeline."""
    logger.info(f"\n{'='*50}")
    logger.info(f"PIPELINE RUN: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info(f"{'='*50}")

    steps = [
        ("src/collectors/fred_collector.py",               "FRED macro data"),
        ("src/collectors/bls_collector.py",                "BLS employment data"),
        ("src/collectors/census_collector.py",             "Census ACS data"),
        ("src/collectors/education_housing_collector.py",  "Education + housing"),
        ("src/etl/pipeline.py",                            "ETL → DuckDB"),
        ("src/analysis/survival_score.py",                 "Survival scores"),
        ("src/analysis/projections.py",                    "ML projections"),
        ("src/etl/export_tableau.py",                      "Tableau exports"),
        ("src/news_parser/news_parser.py",                 "News sentiment"),
        ("src/news_parser/job_market.py",                  "Job market data"),
    ]

    results = []
    for script, label in steps:
        success = run_step(script, label)
        results.append((label, success))
        time.sleep(2)  # Brief pause between steps

    # Summary
    passed = sum(1 for _, ok in results if ok)
    logger.info(f"\nPipeline complete: {passed}/{len(steps)} steps succeeded")
    for label, ok in results:
        status = "✓" if ok else "✗"
        logger.info(f"  {status} {label}")

    return passed == len(steps)


def news_only():
    """Quick refresh — just news and jobs (runs more frequently)."""
    logger.info(f"Quick refresh: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    run_step("src/news_parser/news_parser.py", "News sentiment")
    run_step("src/news_parser/job_market.py",  "Job market")


def setup_local_schedule():
    """Configure local schedule."""
    # Full pipeline: weekly on Sunday at 6 AM
    schedule.every().sunday.at("06:00").do(full_pipeline)

    # News + jobs: daily at 9 AM
    schedule.every().day.at("09:00").do(news_only)

    logger.info("Scheduler configured:")
    logger.info("  Full pipeline: Every Sunday at 06:00")
    logger.info("  News/jobs:     Every day at 09:00")
    logger.info("  Press Ctrl+C to stop\n")

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-now", action="store_true", help="Run full pipeline immediately")
    parser.add_argument("--schedule", action="store_true", help="Start local scheduler")
    args = parser.parse_args()

    if args.run_now:
        full_pipeline()
    elif args.schedule:
        setup_local_schedule()
    else:
        print("Usage:")
        print("  python src/scheduler.py --run-now       # Run pipeline once")
        print("  python src/scheduler.py --schedule      # Start local scheduler")
