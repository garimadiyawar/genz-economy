# Data Methodology & Dictionary
## Gen Z Economy Report

---

## Defining "Gen Z"

For this project, **Gen Z = born 1997–2012**.
- Primary analysis age bracket: **22–30** (post-education, entering workforce)
- Secondary bracket: **18–24** (early adulthood, education phase)

All statistics use this age cohort where granular data allows, otherwise uses
the closest available brackets (typically BLS: 20–24, 25–34).

---

## Gen Z Survival Score Methodology

The composite score is computed monthly from available dimension indices.

### Dimension 1: Cost Burden Index (weight: 25%)
**Measures:** How much of median Gen Z income goes to rent.

Formula:
```
cost_burden_score = normalize_inverse(avg_rent / median_monthly_income * 100)
```
- Source: Zillow ZORI (rent) × BLS median earnings 25–34 (income)
- Normalization: 0 = worst ever observed, 100 = best ever observed
- Inversion: high rent burden → low score

### Dimension 2: Employment Quality Index (weight: 25%)
**Measures:** Unemployment rate, U-6 underemployment, employment-to-population ratio.

Formula:
```
employment_score = 0.4 * normalize_inv(unemployment_25_34)
                 + 0.3 * normalize_inv(u6_underemployment)
                 + 0.3 * normalize(emp_pop_ratio_25_34)
```

### Dimension 3: Real Wage Index (weight: 20%)
**Measures:** Purchasing power of Gen Z wages (inflation-adjusted).

Formula:
```
real_wage = median_weekly_earnings / (CPI / 100)
wage_score = normalize(real_wage)
```
- Captures whether wages are keeping up with cost of living

### Dimension 4: Education Debt Index (weight: 15%)
**Measures:** Total outstanding student loan debt (national).

Formula:
```
debt_score = normalize_inverse(student_loans_outstanding_billions)
```
- Caveat: national aggregate, not Gen Z-specific (Gen Z-specific data sparse)
- Supplement with College Scorecard median debt for institution-level analysis

### Dimension 5: Housing Access Index (weight: 15%)
**Measures:** Months of income required to save 20% down payment (at 10% savings rate).

Formula:
```
months_to_down = (median_home_price * 0.20) / (annual_wage / 12 * 0.10)
housing_score = normalize_inverse(months_to_down)
```

---

## Data Source Details

### FRED (Federal Reserve Economic Data)
- **API:** https://fred.stlouisfed.org/docs/api/fred/
- **Key series used:** See `src/collectors/fred_collector.py`
- **Frequency:** Monthly, quarterly, annual
- **Lag:** Typically 1–3 months behind current date
- **Reliability:** ⭐⭐⭐⭐⭐ — Primary government source

### BLS CPS (Current Population Survey)
- **URL:** https://www.bls.gov/cps/
- **Key series used:** See `src/collectors/bls_collector.py`
- **Coverage:** Unemployment by age group, wages, labor participation
- **Reliability:** ⭐⭐⭐⭐⭐ — Gold standard for employment data

### Census ACS (American Community Survey)
- **API:** https://api.census.gov/data/
- **1-year vs 5-year:** We use 1-year for recency; 5-year for small geographies
- **Coverage:** Income, housing, demographics by geography
- **Caveat:** 2020 ACS 1-year suppressed due to COVID — use 2019 + 2021
- **Reliability:** ⭐⭐⭐⭐⭐

### College Scorecard
- **URL:** https://collegescorecard.ed.gov/data/
- **Institution coverage:** ~6,000+ Title IV institutions
- **Key fields:** Median debt at graduation, earnings 6yr/10yr post-enrollment
- **Caveat:** Earnings are for ALL completers, not Gen Z-specific
- **Reliability:** ⭐⭐⭐⭐

### Zillow Research Data
- **URL:** https://www.zillow.com/research/data/
- **ZORI:** Zillow Observed Rent Index — repeat-rent index, controls for mix
- **ZHVI:** Zillow Home Value Index — Zestimate-based
- **Caveat:** Zillow estimates ≠ official government data; directionally accurate
- **Reliability:** ⭐⭐⭐⭐

### GDELT Project
- **URL:** https://www.gdeltproject.org/
- **Use:** News sentiment about Gen Z economic topics
- **Coverage:** Global English-language news since 2015
- **Caveat:** News volume ≠ severity; sentiment is headline-level
- **Reliability:** ⭐⭐⭐ (sentiment proxy only)

---

## Known Limitations

1. **Geographic granularity:** Gen Z economic outcomes vary massively by city.
   National averages mask severe local disparities (San Francisco vs. Boise).

2. **Demographic granularity:** Race, gender, disability, and first-gen status
   dramatically affect outcomes. Aggregate Gen Z numbers obscure inequality
   within the generation. Supplement with Census microdata (PUMS) for equity analysis.

3. **Gig economy undercount:** BLS/CPS surveys undercount gig workers.
   True underemployment may be 3–5 points higher than U-6 suggests.

4. **Recency lag:** Most government data is 1–3 months old. Real-time signals
   come from job postings and news sentiment, which have their own biases.

5. **Survivorship bias in education data:** College Scorecard earnings data only
   covers students who received federal financial aid at Title IV institutions.

6. **Inflation adjustment:** All real comparisons use CPI-U. Some economists
   argue this understates inflation for renters (shelter weight ~33%);
   actual Gen Z cost burden may be higher than CPI implies.

---

## Generational Comparison Caveats

Comparing Gen Z to Boomers at the same age is complex:
- Economy, job types, and cost structures have fundamentally changed
- Boomers had union jobs, defined-benefit pensions, lower education costs
- But also faced higher mortgage rates (18%+ in 1981) and no internet
- We compare observable economic outcomes (real wages, home price to income)
  not subjective life quality

**Opportunity Insights** (Harvard/Census collaboration) data is the gold standard
for intergenerational mobility: https://opportunityinsights.org/data/

---

## Survival Score Interpretation Guide

| Score | Category | Interpretation |
|-------|----------|----------------|
| 0–20 | 🔴 Crisis | Structural barriers preventing basic economic stability |
| 21–33 | 🔴 Barely Surviving | Making ends meet but no accumulation, high stress |
| 34–50 | 🟡 Treading Water | Stable but not progressing; one crisis away from hardship |
| 51–66 | 🟡 Living | Meeting needs, some savings, modest progress |
| 67–80 | 🟢 Thriving | Comfortable, building wealth, positive trajectory |
| 81–100 | 🟢 Flourishing | Exceptional conditions; strong mobility and security |

**Important:** Scores below 50 do not mean Gen Z is "failing" — they reflect
structural economic conditions, not personal failures. The score is a
diagnostic tool, not a judgment.
