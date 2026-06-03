# Code Fixes — genz-economy

This document summarises all 12 issues identified in the code review and the fixes applied.

---

## 🔴 Critical Fixes

### Fix 1 — BLS `END_YEAR` was hardcoded to 2025 (`src/collectors/bls_collector.py`)
**Problem:** Pipeline silently stopped fetching new BLS data after 2025.  
**Fix:** `END_YEAR` is now `datetime.today().year`, matching the FRED collector.

### Fix 2 — Survival score used min-max normalization (`src/analysis/survival_score.py`)
**Problem:** Min-max normalization is retroactively unstable — adding new data changed all historical scores, and the score was a percentile within history rather than an absolute measure of conditions.  
**Fix:** Replaced with anchored normalization using fixed real-world thresholds (e.g. rent burden: 20% = 100, 60% = 0). Scores are now stable and reproducible across runs. The old `normalize_to_100()` remains as a documented fallback for series without defined anchors.

### Fix 3 — Salary extraction silently produced absurd values (`src/news_parser/job_market.py`)
**Problem:** The heuristic `val if val > 1000 else val * 2080` misidentified non-hourly values (e.g. "$900 stipend") as hourly, producing inflated salaries like $1.87M.  
**Fix:** Replaced with `_annualize()`, which checks explicit textual signals (`/hr`, `/month`, `k` suffix), falls back to the hourly heuristic only for values < $200, and discards results outside the plausible range $15k–$500k instead of propagating garbage data.

### Fix 4 — Debt score used aggregate national stock, not individual burden (`src/analysis/survival_score.py`)
**Problem:** Total student loans outstanding (SLOAS) rises when more students enroll, not just when individual debt gets worse. The score penalised population growth.  
**Fix:** Now computes an approximate per-borrower debt-to-income ratio (total debt / 45M borrowers / median annual wage), anchored at 0.3 (manageable) to 1.5 (severe burden). Falls back to the aggregate series if the wage join fails.

---

## 🟠 Significant Fixes

### Fix 5 — Missing dimensions were silently rescaled to look complete (`src/analysis/survival_score.py`)
**Problem:** When a dimension's data was absent, the score was rescaled to still fill 0–100, making an incomplete score look like a complete one.  
**Fix:** Now emits an explicit `logger.warning` listing the missing dimensions and their combined weight. A `score_coverage_pct` column is added to the output CSV. Rescaling still happens (so the remaining dimensions are comparable) but the gap is visible.

### Fix 6 — `.history/` directory with `.env` files was committed (`repo root`)
**Problem:** VS Code Local History committed timestamped copies of `.env` files containing API keys.  
**Fix:** `.history/` directory removed from the repo. `.gitignore` updated to exclude `.history/` and explicitly re-state `.env`.  
**Action required:** Rotate any API keys (FRED, Census, College Scorecard, NewsAPI) that were in those files — treat them as compromised.

### Fix 7 — GitHub Actions wrote secrets to a plaintext `.env` file on disk (`.github/workflows/refresh.yml`)
**Problem:** `echo "KEY=${{ secrets.KEY }}" >> .env` creates a readable file in the runner workspace, risking exposure through artifact uploads or debug logs.  
**Fix:** Secrets are now injected directly as environment variables via the `env:` block at the job level. The `Create .env` step is replaced with a secrets-present check that warns on missing values.

### Fix 8 — GitHub Actions git push had no write permissions and silently failed (`.github/workflows/refresh.yml`)
**Problem:** The default `GITHUB_TOKEN` may lack write access. `continue-on-error: true` masked the failure, so data appeared to refresh when it didn't.  
**Fix:** Added `permissions: contents: write` to the job. The push step now exits non-zero on failure (no `continue-on-error`) with a clear error message.

---

## 🟡 Minor Fixes

### Fix 9 — Inconsistent random seeds in dev mode (`src/utils/bootstrap_data.py`)
**Problem:** `make_fred_data()` had no seed, `make_jobs_data()` used 99, `make_news_data()` used 7. Dev runs were not reproducible.  
**Fix:** Added a single `DEV_SEED = 42` constant. All generators derive their seed from it (`DEV_SEED`, `DEV_SEED+1`, etc.), making the full synthetic dataset deterministic.

### Fix 10 — Dev mode silently overwrote real data (`src/utils/bootstrap_data.py`)
**Problem:** Running `--mode dev` on a machine with real collected data silently replaced it with synthetic data, destroying the real API results.  
**Fix:** `run_dev_mode()` checks for the presence of real parquet files before generating. If found, it aborts with an error. A `--force` flag overrides this for intentional resets.

### Fix 11 — Projection model had no quality gate (`src/analysis/projections.py`)
**Problem:** A 3-year window that happened to include a structural break (e.g. COVID) was extrapolated without checking whether the trend was meaningful.  
**Fix:** Added `MIN_R2_THRESHOLD = 0.50` and `MIN_DATA_POINTS = 24`. Projections below the R² threshold return historical data only (rent burden) or widen the confidence band 2× (survival score). The projection window dates are logged for auditability.

### Fix 12 — Metro rent was divided by national wage, distorting all metro comparisons (`src/etl/pipeline.py`)
**Problem:** A single national median wage applied to all metros made San Francisco always look unaffordable and rural metros always look affordable — independent of local wage levels.  
**Fix:** The `cost_burden_mart` now joins a `state_income_index` derived from Census ACS median income data (relative to national median). Each metro's rent is divided by the national wage scaled by its state's income index. Falls back to `1.0` (national wage unchanged) for states not in the Census data.

---

## Notes

- **API keys:** After rotating keys (Fix 6), update them in GitHub → Settings → Secrets and variables → Actions.
- **Score history:** The survival score will now report different values than before Fix 2 because it uses absolute anchors instead of relative percentiles. This is correct behaviour — the old scores were not meaningful.
- **Tableau:** The `score_coverage_pct` column added in Fix 5 can be used as a data quality indicator in dashboards.
