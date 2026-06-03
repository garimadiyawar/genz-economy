# Tableau Public — Dashboard Build Guide
## Gen Z Economy Report: Living, Thriving, or Barely Surviving?

---

## Setup

1. Download **Tableau Public** (free): https://public.tableau.com/app/discover
2. Open Tableau Public → Connect → Text File
3. Navigate to `data/exports/` and connect to the files below

---

## Dashboard 1: National Overview (Survival Score)

**Data source:** `tableau_survival_score_timeseries.csv`

### Sheets to build:

#### Sheet 1A — Survival Score KPI Tile
- Drag `survival_score` to Text
- Create calculated field:
  ```
  SCORE_COLOR:
  IF [Survival Score] <= 33 THEN "🔴 Barely Surviving"
  ELSEIF [Survival Score] <= 66 THEN "🟡 Living"
  ELSE "🟢 Thriving"
  END
  ```
- Display as Big Number with category label below

#### Sheet 1B — Survival Score Over Time (Line Chart)
- X-axis: `date` (continuous)
- Y-axis: `survival_score`
- Color: `category` (red/yellow/green)
- Add reference line at 33 and 66 (format as dashed)
- Tooltip: Date, Score, Category

#### Sheet 1C — Dimension Radar (Bar Chart alternative)
**Data source:** `tableau_dimension_breakdown.csv`
- Rows: `label`
- Columns: `score`
- Color: gradient (red 0 → green 100)
- Sort descending by score
- This becomes your dimension performance overview

#### Sheet 1D — Annual KPI Table
**Data source:** `tableau_annual_summary.csv`
- Rows: `year`
- Columns: all score dimensions
- Format as heatmap (Color > Score gradient)

---

## Dashboard 2: The Cost Crunch

**Data source:** `tableau_cost_burden_by_metro.csv`

### Sheets to build:

#### Sheet 2A — Rent Burden Map
- Double-click `state_name` → auto-generates map
- Color: `rent_to_income_pct` (diverging palette, midpoint at 30%)
- Add `region_name` to tooltip
- Filter: Year slider

#### Sheet 2B — Rent vs Income Over Time
- X-axis: `date`
- Y-axis dual-axis: `avg_rent` (left) + `avg_income_median` (right)
- Mark: Line
- Color: Measure Names

#### Sheet 2C — Burden Category Breakdown (Stacked Bar)
- X-axis: `year`
- Y-axis: COUNT of records
- Color: `burden_category` (Affordable=green, Cost Burdened=orange, Severely Burdened=red)

#### Sheet 2D — Top 20 Most Burdened Metros (Bullet Bar)
- Filter to latest year
- Rows: `region_name` (top 20 by rent_to_income_pct)
- Color: `burden_category`
- Add reference line at 30%

---

## Dashboard 3: The Education Trap

**Data sources:**
- `tableau_education_debt.csv` (macro debt trends)
- `tableau_college_scorecard.csv` (institution-level)

### Sheets to build:

#### Sheet 3A — Student Debt Outstanding (Area Chart)
- Filter: `metric = 'outstanding'`
- X: date, Y: student_debt_billions
- Color: Solid fill (#FF6B35 gradient)

#### Sheet 3B — Debt Delinquency Rate (Line)
- Filter: `metric = 'delinquency_rate'`
- X: date, Y: delinquency_pct
- Add reference band for COVID moratorium period

#### Sheet 3C — Debt vs Earnings by School (Scatter)
**Source:** `tableau_college_scorecard.csv`
- X: `earnings_6yr` (horizontal)
- Y: `median_debt` (vertical)
- Color: `state`
- Size: `tuition_in_state`
- Tooltip: school_name, debt, earnings, ratio
- Add reference line where debt = earnings (break-even)
- Quadrant annotations:
  - Top-left = Debt Trap (high debt, low earnings)
  - Bottom-right = ROI Sweet Spot

#### Sheet 3D — Completion Rate vs Debt (Scatter)
- X: `completion_rate`
- Y: `median_debt`
- Insight: schools with low completion still load students with debt

---

## Dashboard 4: Job Market Reality

**Data sources:**
- `tableau_employment_landscape.csv`
- `tableau_job_postings.csv`
- `tableau_degree_requirements.csv`

### Sheets to build:

#### Sheet 4A — Unemployment by Age Group Over Time
- X: date
- Y: Measure Values
- Measures: `unemployment_20_24`, `unemployment_25_34`, all gen total
- Color: age group
- Shade COVID spike (Mar 2020 – Dec 2020) with annotation

#### Sheet 4B — U-6 Underemployment (Area)
- X: date, Y: `underemployment_u6`
- Compare to standard unemployment on same axis
- Gap between lines = hidden underemployment

#### Sheet 4C — Job Postings by Sector (Treemap)
**Source:** `tableau_job_postings.csv`
- Size: count of postings
- Color: `entry_level_pct`
- Label: `sector`

#### Sheet 4D — Degree Requirement Shift (Stacked Bar)
**Source:** `tableau_degree_requirements.csv`
- X: sector
- Color: required/preferred/not_required
- Key story: are companies dropping degree requirements?

#### Sheet 4E — Remote Work Availability (Donut)
- Work type breakdown: remote/hybrid/in_person
- Filter by sector for drill-down

---

## Dashboard 5: Gen Z vs The Generations

**Data source:** `tableau_generational_comparison.csv`

### Sheets to build:

#### Sheet 5A — Home Price to Income Ratio Over Time
- X: date, Y: `home_price_to_income`
- Color: `cohort_label`
- Annotate: "Boomers bought homes at 3–4x income; Gen Z faces 7–8x"

#### Sheet 5B — Real Median Income by Decade (Bar)
- Group by decade
- Compare purchasing power

#### Sheet 5C — Generational Timeline (Gantt/Band)
- Show economic events each generation faced at age 22:
  - Boomers: post-WWII boom
  - Gen X: savings & loan crisis
  - Millennials: 2008 crash
  - Gen Z: COVID + inflation spike

---

## Dashboard 6: The 2030 Outlook

**Data sources:**
- `tableau_projections.csv`
- `tableau_news_sentiment.csv`

### Sheets to build:

#### Sheet 6A — Rent Burden Projection (Line + Band)
- Filter: `metric = 'rent_burden_pct'`
- X: date, Y: rent_burden
- Dashed line where `is_forecast = True`
- Band: `lower_95` to `upper_95` (light shading)

#### Sheet 6B — Survival Score Forecast (Line + Band)
- Filter: `metric = 'survival_score'`
- Dashed forecast + confidence band
- Color zones: red (0–33) / yellow (34–66) / green (67–100)
- Annotation: "Projected score in 2030: XX"

#### Sheet 6C — Student Debt Trajectory
- Filter: `metric = 'student_debt_billions'`
- Bar (actuals) + dashed line (forecast)

#### Sheet 6D — News Sentiment Over Time
**Source:** `tableau_news_sentiment.csv`
- X: date, Y: avg_sentiment
- Color: sentiment_label
- Size: article_count
- Filter: query dropdown

---

## Story Points (Tableau Story)

Build a Tableau Story connecting all dashboards in order:

1. **"The Setup"** → Dashboard 1 (survival score overview)
2. **"The Squeeze"** → Dashboard 2 (cost burden)
3. **"The Debt Trap"** → Dashboard 3 (education)
4. **"The Work Reality"** → Dashboard 4 (jobs)
5. **"Standing on Shoulders"** → Dashboard 5 (generational gap)
6. **"Where It's Going"** → Dashboard 6 (projections)

Each story point adds a caption (300 chars max in Tableau Public) with the key finding.

---

## Calculated Fields Reference

```
// Rent burden classification
BURDEN_LABEL:
IF [Rent To Income Pct] > 50 THEN "Severely Burdened"
ELSEIF [Rent To Income Pct] > 30 THEN "Cost Burdened"
ELSE "Affordable"
END

// Education ROI flag
DEBT_ROI_FLAG:
IF [Debt To Earnings Ratio] > 1.5 THEN "Debt Trap"
ELSEIF [Debt To Earnings Ratio] > 1.0 THEN "Break Even"
ELSE "Positive ROI"
END

// Survival score band
SCORE_BAND:
IF [Survival Score] <= 33 THEN 1
ELSEIF [Survival Score] <= 66 THEN 2
ELSE 3
END

// YoY change label
YOY_LABEL:
IF [Unemployment 20 24 Yoy] > 0 THEN "▲ " + STR(ABS(ROUND([Unemployment 20 24 Yoy],1))) + "%"
ELSE "▼ " + STR(ABS(ROUND([Unemployment 20 24 Yoy],1))) + "%"
END
```

---

## Publishing to Tableau Public

1. File → Save to Tableau Public
2. Sign in / create free account
3. Name: "Gen Z Economy Report 2024"
4. Set to Public
5. Share URL on LinkedIn, Twitter/X, GitHub

**Pro tips:**
- Use device preview to ensure mobile responsiveness
- Add dashboard description with data sources cited
- Tag: #DataViz #GenZ #Economy #Python #Tableau
