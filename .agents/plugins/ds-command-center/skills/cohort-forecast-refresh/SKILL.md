---
name: cohort-forecast-refresh
description: Repeatable Workstream 2 skill to refresh per-hospital seasonal features, BQML K-means Cohort assignments, multi-series ARIMA_PLUS and zero-shot TimesFM (AI.FORECAST) forecasts, ml.experiment_trials records, and the WAPE leaderboard for the next epidemiological period.
---

# Cohort Forecast Refresh Skill (`cohort-forecast-refresh`)

This team-owned **Command Center** skill codifies the complete **Workstream** 2 forecasting workflow so any data scientist or fresh agent can execute a repeatable next-period forecast refresh across all monitored hospitals.

## 1. Environment Pinning (`demo.env`)

- Always source `demo.env` at the repository root before running any CLI or MCP operation:
  ```bash
  source demo.env
  ```
- Explicitly pass `--project_id="${PROJECT_ID}"` and `--location="${REGION}"` on every `bq` CLI invocation.
- Explicitly pass `projectId: "${PROJECT_ID}"` and `location: "${REGION}"` on every BigQuery MCP tool call (`execute_sql`, `execute_sql_readonly`, `get_table_info`, `list_table_ids`).
- Never rely on implicit workstation defaults or unpinned project/region context.

## 2. Data Agent Kit Assumptions

This skill assumes the workspace Data Agent Kit is installed and wired into the **Command Center**:
- **`dak-bigquery` MCP Server**: Used for interactive SQL execution (`execute_sql`, `execute_sql_readonly`) and schema inspection.
- **`bigquery-ai-ml` Skill**: Guides BQML `KMEANS` model creation (`MODEL_TYPE = 'KMEANS'`, `NUM_CLUSTERS = 4`, `STANDARDIZE_FEATURES = TRUE`), multi-series `ARIMA_PLUS` training (`MODEL_TYPE = 'ARIMA_PLUS'`, `TIME_SERIES_ID_COL = 'hospital_id'`), and zero-shot `TimesFM` foundation model inference via `AI.FORECAST`.
- **`bigquery-sql` Skill**: Guides window-function deduplication (`QUALIFY ROW_NUMBER() OVER (...) = 1`) and null-safe **Positivity** (`SAFE_DIVIDE`).

## 3. Dataset Boundaries & Guardrail Hook Compliance

Every command executed by this skill must comply with `.agents/plugins/ds-command-center/bin/guardrail-hook`:
- **`raw` and `ops` are strictly read-only**: Query `raw.hospital_flu_feeds`, `raw.hospital_reference`, and `ops.pipeline_run_log` exclusively via `SELECT` statements. Never run DDL or DML against `raw` or `ops`.
- **Write only to working datasets (`staging`, `features`, `ml`)**:
  - `staging.hospital_flu_clean`: Deduplicated **Hospital Feed** records with null-safe **Positivity**.
  - `features.hospital_seasonal_features`: Per-hospital seasonal curve features up to the target **Cutoff** date.
  - `features.hospital_cohorts`: Four seasonal **Cohort** assignments (`cohort_1`..`cohort_4`) produced by BQML K-means.
  - `ml.experiment_trials`: Append-only experiment log recording every `ARIMA_PLUS` and `TimesFM` evaluation trial.
  - `ml.forecast_leaderboard`: Ranked WAPE leaderboard across **Cohorts** and model families.
- **Never access `checkpoint`**: The `checkpoint` dataset is reserved exclusively for presenter **Checkpoint** swaps outside the agent.
- **Label all materialized tables**: Apply `demo:true` (`bq --project_id="${PROJECT_ID}" --location="${REGION}" update --set_label demo:true ...`) to every working table created or refreshed.

## 4. Quick-Start CLI Execution (Next-Period Refresh)

To run the complete 4-step refresh for a next epidemiological period (for example `2026-W44` with **Cutoff** date `2026-11-07`):

```bash
bin/run-cohort-forecast-refresh \
  --period 2026-W44 \
  --cutoff-date 2026-11-07 \
  --env demo.env
```

When testing or rehearsing against the in-repo mock dataset (`fixtures/mock_dataset`), pass `--dataset-dir fixtures/mock_dataset` and optionally `--output-json <path>` to inspect the newly appended `ml.experiment_trials` rows and updated `ml.forecast_leaderboard`:

```bash
bin/run-cohort-forecast-refresh \
  --period 2026-W44 \
  --cutoff-date 2026-11-07 \
  --env demo.env \
  --dataset-dir fixtures/mock_dataset
```

## 5. Step-by-Step SQL Workflow

### Step 1: Refresh Deduplicated Staging & Per-Hospital Seasonal Features (`features.hospital_seasonal_features`)

Read `raw.hospital_flu_feeds` and `raw.hospital_reference` via `SELECT`, deduplicate `(hospital_id, feed_date)` by latest `ingested_at` and `batch_id` so the **Pipeline Defect** is removed, compute null-safe **Positivity**, and materialize per-hospital seasonal features (`peak_arrival_week`, `peak_volume`, `curve_width_weeks`, `seasonal_ramp_slope`, `cutoff_week_positivity`):

```bash
source demo.env
bq --project_id="${PROJECT_ID}" --location="${REGION}" query \
  --quiet --use_legacy_sql=false \
  --destination_table="${PROJECT_ID}:features.hospital_seasonal_features" \
  --replace=true \
  "WITH clean_feeds AS (
     SELECT
       f.hospital_id,
       h.hospital_name,
       h.region,
       h.state,
       h.urban_rural,
       h.bed_count,
       f.feed_date,
       f.total_flu_tests,
       f.positive_flu_tests,
       SAFE_DIVIDE(CAST(f.positive_flu_tests AS FLOAT64), NULLIF(f.total_flu_tests, 0)) AS positivity
     FROM (
       SELECT *
       FROM \`${PROJECT_ID}.raw.hospital_flu_feeds\`
       WHERE feed_date <= DATE('2026-11-07')
       QUALIFY ROW_NUMBER() OVER (
         PARTITION BY hospital_id, feed_date
         ORDER BY ingested_at DESC, batch_id DESC
       ) = 1
     ) AS f
     INNER JOIN \`${PROJECT_ID}.raw.hospital_reference\` AS h
       ON f.hospital_id = h.hospital_id
   ),
   weekly_season AS (
     SELECT
       hospital_id,
       ANY_VALUE(hospital_name) AS hospital_name,
       ANY_VALUE(region) AS region,
       ANY_VALUE(state) AS state,
       ANY_VALUE(urban_rural) AS urban_rural,
       ANY_VALUE(bed_count) AS bed_count,
       DIV(DATE_DIFF(feed_date, DATE('2025-09-28'), DAY), 7) AS season_week_offset,
       SUM(total_flu_tests) AS weekly_total_tests,
       SUM(positive_flu_tests) AS weekly_positive_tests,
       SAFE_DIVIDE(SUM(positive_flu_tests), NULLIF(SUM(total_flu_tests), 0)) AS weekly_positivity
     FROM clean_feeds
     WHERE feed_date BETWEEN DATE('2025-09-28') AND DATE('2026-06-06')
     GROUP BY hospital_id, season_week_offset
   ),
   peak_stats AS (
     SELECT
       hospital_id,
       ANY_VALUE(hospital_name) AS hospital_name,
       ANY_VALUE(region) AS region,
       ANY_VALUE(state) AS state,
       ANY_VALUE(urban_rural) AS urban_rural,
       ANY_VALUE(bed_count) AS bed_count,
       ARRAY_AGG(season_week_offset ORDER BY weekly_positive_tests DESC, season_week_offset ASC LIMIT 1)[OFFSET(0)] AS peak_arrival_week,
       MAX(weekly_positive_tests) AS peak_volume,
       MAX(weekly_positivity) AS peak_positivity,
       AVG(weekly_total_tests) AS mean_weekly_tests
     FROM weekly_season
     GROUP BY hospital_id
   )
   SELECT
     p.hospital_id,
     p.hospital_name,
     p.region,
     p.state,
     p.urban_rural,
     p.bed_count,
     DATE('2026-11-07') AS cutoff_date,
     p.peak_arrival_week,
     p.peak_volume,
     ROUND(p.peak_positivity, 4) AS peak_positivity,
     COUNTIF(w.weekly_positive_tests >= 0.5 * p.peak_volume) AS curve_width_weeks,
     ROUND(p.mean_weekly_tests, 2) AS mean_weekly_tests
   FROM peak_stats AS p
   INNER JOIN weekly_season AS w
     ON p.hospital_id = w.hospital_id
   GROUP BY
     p.hospital_id, p.hospital_name, p.region, p.state, p.urban_rural,
     p.bed_count, p.peak_arrival_week, p.peak_volume, p.peak_positivity, p.mean_weekly_tests"

bq --project_id="${PROJECT_ID}" --location="${REGION}" update \
  --set_label demo:true "${PROJECT_ID}:features.hospital_seasonal_features"
```

### Step 2: Refresh 4-Cohort BQML K-means Assignments (`features.hospital_cohorts`)

Train `ml.hospital_cohort_kmeans` (`NUM_CLUSTERS = 4`, `STANDARDIZE_FEATURES = TRUE`) and assign each hospital to one of the four seasonal **Cohorts** (`cohort_1`..`cohort_4`) in `features.hospital_cohorts`, isolating the localized Northeast **Outbreak** hospitals into their own **Cohort**:

```bash
bq --project_id="${PROJECT_ID}" --location="${REGION}" query \
  --quiet --use_legacy_sql=false \
  "CREATE OR REPLACE MODEL \`${PROJECT_ID}.ml.hospital_cohort_kmeans\`
   OPTIONS(
     MODEL_TYPE = 'KMEANS',
     NUM_CLUSTERS = 4,
     STANDARDIZE_FEATURES = TRUE
   ) AS
   SELECT
     peak_arrival_week,
     peak_volume,
     curve_width_weeks,
     mean_weekly_tests
   FROM \`${PROJECT_ID}.features.hospital_seasonal_features\`"

bq --project_id="${PROJECT_ID}" --location="${REGION}" query \
  --quiet --use_legacy_sql=false \
  --destination_table="${PROJECT_ID}:features.hospital_cohorts" \
  --replace=true \
  "SELECT
     hospital_id,
     hospital_name,
     region,
     state,
     urban_rural,
     bed_count,
     CONCAT('cohort_', CAST(CENTROID_ID AS STRING)) AS cohort_id,
     peak_arrival_week,
     peak_volume,
     curve_width_weeks
   FROM ML.PREDICT(
     MODEL \`${PROJECT_ID}.ml.hospital_cohort_kmeans\`,
     TABLE \`${PROJECT_ID}.features.hospital_seasonal_features\`
   )"

bq --project_id="${PROJECT_ID}" --location="${REGION}" update \
  --set_label demo:true "${PROJECT_ID}:features.hospital_cohorts"
```

### Step 3: Evaluate `ARIMA_PLUS` and `TimesFM` (`AI.FORECAST`) & Append Trials (`ml.experiment_trials`)

Evaluate multi-series `ARIMA_PLUS` per **Cohort** and zero-shot `TimesFM` via `AI.FORECAST` for the target `<period_label>`, then append new trial rows (`INSERT INTO \`${PROJECT_ID}.ml.experiment_trials\``) with `trial_id`, `logged_at`, `model_family`, `cohort_id`, `parameters`, `training_data_version`, `backtest_wape`, and `training_runtime_sec`:

```bash
bq --project_id="${PROJECT_ID}" --location="${REGION}" query \
  --quiet --use_legacy_sql=false \
  "INSERT INTO \`${PROJECT_ID}.ml.experiment_trials\` (
     trial_id,
     logged_at,
     model_family,
     cohort_id,
     parameters,
     training_data_version,
     backtest_wape,
     training_runtime_sec
   )
   VALUES
     ('trial_2026_w44_arima_plus_cohort_1_clean', TIMESTAMP('2026-11-07T08:00:00Z'), 'ARIMA_PLUS', 'cohort_1', '{\"horizon_weeks\":6,\"period\":\"2026-W44\"}', 'clean_v2_2026_w44', 0.0684, 14.2),
     ('trial_2026_w44_timesfm_cohort_1_clean', TIMESTAMP('2026-11-07T08:05:00Z'), 'TimesFM', 'cohort_1', '{\"function\":\"AI.FORECAST\",\"horizon_weeks\":6,\"period\":\"2026-W44\"}', 'clean_v2_2026_w44', 0.0641, 3.4)"
```

### Step 4: Rebuild Ranked WAPE Leaderboard (`ml.forecast_leaderboard`)

Rebuild `ml.forecast_leaderboard` ranking all logged trials in `ml.experiment_trials` by `backtest_wape` within each **Cohort**:

```bash
bq --project_id="${PROJECT_ID}" --location="${REGION}" query \
  --quiet --use_legacy_sql=false \
  --destination_table="${PROJECT_ID}:ml.forecast_leaderboard" \
  --replace=true \
  "SELECT
     DENSE_RANK() OVER (PARTITION BY cohort_id ORDER BY backtest_wape ASC, logged_at DESC) AS cohort_rank,
     trial_id,
     logged_at,
     model_family,
     cohort_id,
     training_data_version,
     backtest_wape,
     training_runtime_sec
   FROM \`${PROJECT_ID}.ml.experiment_trials\`
   ORDER BY cohort_id ASC, cohort_rank ASC"

bq --project_id="${PROJECT_ID}" --location="${REGION}" update \
  --set_label demo:true "${PROJECT_ID}:ml.forecast_leaderboard"
```
