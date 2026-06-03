# 🧬 Gen Z Economy Report
## *Living, Thriving, or Barely Surviving?*

**[→ Live Report](https://genzeconomy.vercel.app)** · **[Tableau Dashboards](#)** · Built with BLS · FRED · Zillow · Census · scikit-learn

> Survival Score: 48.2 / 100 — Living 🟡 (as of January 2025)

A multi-dimensional, data-driven analysis of how Gen Z (born 1997–2012) is faring in today's economy — using 100% free, publicly available data sources.

---

## 📐 Project Architecture

```
genz_economy/
├── data/
│   ├── raw/          ← Downloaded from APIs/CSV
│   ├── processed/    ← Cleaned, normalized
│   └── exports/      ← Tableau-ready .csv / .hyper files
├── src/
│   ├── collectors/   ← Data ingestion scripts
│   ├── etl/          ← Transform + load to DuckDB
│   ├── analysis/     ← Scoring, indexing, projections
│   └── news_parser/  ← NewsAPI + GDELT pipeline
├── notebooks/        ← Exploratory Jupyter notebooks
├── tableau/          ← Tableau workbook docs/notes
└── docs/             ← Methodology + data dictionary
```

---

## 🎯 Analysis Dimensions

| # | Dimension | Key Metrics | Primary Sources |
|---|-----------|-------------|-----------------|
| 1 | **Cost of Living vs. Income** | Rent-to-income ratio, wage growth vs CPI | BLS, FRED, Zillow |
| 2 | **Education Debt** | Student debt per borrower, debt-to-income, degree ROI | College Scorecard, NCES, FRED |
| 3 | **Employment Quality** | Gig %, underemployment rate, median wage age 22-27 | BLS CPS, Census ACS |
| 4 | **Housing Access** | Homeownership 18-30, months to save down payment | Census, Zillow, HUD |
| 5 | **Healthcare Access** | Uninsured rate 18-29, mental health service access | CDC NHIS, KFF |
| 6 | **Wealth Building** | Savings rate, retirement plan access, net worth | Fed SCF, FRED |
| 7 | **Social Mobility** | Intergenerational income comparison vs Boomers at same age | Opportunity Insights, Census |

---

## 🔑 Survival Score Formula

Each dimension is indexed 0–100 and weighted to produce a composite **Gen Z Survival Score**:

```
survival_score = (
  0.25 * cost_burden_index +
  0.20 * employment_quality_index +
  0.20 * housing_access_index +
  0.15 * education_debt_index +
  0.10 * healthcare_index +
  0.05 * wealth_index +
  0.05 * mobility_index
)
```

Score bands:
- **0–33**: Barely Surviving 🔴
- **34–66**: Living 🟡
- **67–100**: Thriving 🟢

---

## 📡 Free Data Sources

| Source | URL | Format | Use |
|--------|-----|--------|-----|
| BLS CPS | https://data.bls.gov/cew/apps/data_views/data_views.htm | API + CSV | Employment, wages |
| FRED | https://fred.stlouisfed.org/ | API (free key) | CPI, rent, macro |
| Census ACS | https://api.census.gov/data | REST API (free key) | Income, housing, demographics |
| College Scorecard | https://collegescorecard.ed.gov/data/ | API + CSV | Education debt, outcomes |
| Zillow Research | https://www.zillow.com/research/data/ | CSV | Rent, home prices |
| HUD | https://www.huduser.gov/portal/datasets/ | CSV | Fair market rent |
| CDC NHIS | https://www.cdc.gov/nchs/nhis/ | CSV | Health, insurance |
| KFF | https://www.kff.org/statedata/ | CSV | Healthcare access |
| Opportunity Insights | https://opportunityinsights.org/data/ | CSV | Social mobility |
| GDELT | https://www.gdeltproject.org/ | Stream/CSV | News sentiment |
| NewsAPI | https://newsapi.org/ | REST API (free tier) | News parser |

---

## 🚀 Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up API keys (free)
cp .env.example .env
# Fill in: FRED_API_KEY, CENSUS_API_KEY, NEWSAPI_KEY

# 3. Pull all data
python src/collectors/run_all.py

# 4. Run ETL pipeline
python src/etl/pipeline.py

# 5. Generate survival scores
python src/analysis/survival_score.py

# 6. Export for Tableau
python src/etl/export_tableau.py
```

---

## 📊 Tableau Dashboard Plan

1. **National Overview** — Survival score map by state, trend over time
2. **Cost Crunch** — Rent burden % by metro, wage vs inflation
3. **Education Trap** — Debt load by degree, income outcomes, enrollment shift
4. **Job Market Reality** — Employment quality heatmap, gig economy share
5. **Housing Squeeze** — Homeownership rate by generation at same age
6. **The Big Picture** — Gen Z vs Boomers/Millennials at age 25 comparison

---

## 🔮 Phase 4: Extensions

- **News Parser** — Track economic sentiment about Gen Z in media
- **Job Market Analyzer** — Real-time job postings via Indeed RSS + classification
- **ML Projections** — sklearn forecasting for cost burden, homeownership
- **Auto-refresh** — cron job + GitHub Actions to keep data current
