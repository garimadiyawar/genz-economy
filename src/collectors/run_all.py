"""
Run All Collectors
Usage: python src/collectors/run_all.py

Orchestrates all data collection in the correct order.
Estimated runtime: 2-5 minutes depending on API speed.
"""

import time
from loguru import logger
from pathlib import Path

# Configure logging
logger.add("logs/collection_{time}.log", rotation="1 week")
Path("logs").mkdir(exist_ok=True)


def run():
    logger.info("╔══════════════════════════════════════════╗")
    logger.info("║  Gen Z Economy Report — Data Collection  ║")
    logger.info("╚══════════════════════════════════════════╝\n")

    results = {}

    # ── 1. FRED (macro indicators) ─────────────────────────────
    logger.info("Step 1/5: FRED Economic Indicators")
    try:
        from collectors.fred_collector import run as run_fred
        results["fred"] = run_fred()
        logger.success("FRED ✓\n")
    except Exception as e:
        logger.error(f"FRED failed: {e}\n")
    time.sleep(1)

    # ── 2. BLS (employment + wages) ────────────────────────────
    logger.info("Step 2/5: BLS Employment Data")
    try:
        from collectors.bls_collector import run as run_bls
        results["bls"] = run_bls()
        logger.success("BLS ✓\n")
    except Exception as e:
        logger.error(f"BLS failed: {e}\n")
    time.sleep(1)

    # ── 3. Census ACS (demographics) ──────────────────────────
    logger.info("Step 3/5: Census ACS Demographics")
    try:
        from collectors.census_collector import run as run_census
        results["census"] = run_census()
        logger.success("Census ✓\n")
    except Exception as e:
        logger.error(f"Census failed: {e}\n")
    time.sleep(1)

    # ── 4. Education (College Scorecard) ──────────────────────
    logger.info("Step 4/5: Education + Housing Data")
    try:
        from collectors.education_housing_collector import run_education, run_housing
        results["education"] = run_education()
        results["housing"] = run_housing()
        logger.success("Education + Housing ✓\n")
    except Exception as e:
        logger.error(f"Education/Housing failed: {e}\n")
    time.sleep(1)

    # ── 5. Summary ─────────────────────────────────────────────
    logger.info("╔══════════════════════════════════╗")
    logger.info("║  Collection Complete              ║")
    logger.info("╚══════════════════════════════════╝")
    logger.info("Next step: python src/etl/pipeline.py")

    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "src")
    run()
