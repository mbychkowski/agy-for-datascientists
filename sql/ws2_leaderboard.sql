-- =============================================================================
-- Workstream 2 Forecast Leaderboard Query: ml.forecast_leaderboard
--
-- Ranks (model_family, training_data_version) per Cohort and overall across
-- Cohorts by backtest_wape ASC from ml.experiment_trials.
-- =============================================================================

WITH
  trial_metrics AS (
    SELECT
      trial_id,
      logged_at,
      model_family,
      cohort_id,
      parameters,
      training_data_version,
      backtest_wape,
      training_runtime_sec
    FROM `ml.experiment_trials`
  ),
  family_summary AS (
    SELECT
      model_family,
      training_data_version,
      AVG(backtest_wape) AS mean_wape_across_cohorts,
      AVG(training_runtime_sec) AS mean_runtime_sec,
      RANK() OVER (ORDER BY AVG(backtest_wape) ASC) AS overall_family_rank
    FROM trial_metrics
    GROUP BY model_family, training_data_version
  )
SELECT
  t.cohort_id,
  RANK() OVER (PARTITION BY cohort_id ORDER BY backtest_wape ASC) AS cohort_rank,
  f.overall_family_rank,
  t.model_family,
  t.training_data_version,
  ROUND(t.backtest_wape, 2) AS backtest_wape,
  ROUND(f.mean_wape_across_cohorts, 2) AS mean_wape_across_cohorts,
  ROUND(t.training_runtime_sec, 2) AS training_runtime_sec,
  ROUND(f.mean_runtime_sec, 2) AS mean_runtime_sec,
  t.trial_id,
  t.logged_at,
  t.parameters
FROM trial_metrics AS t
INNER JOIN family_summary AS f
  USING (model_family, training_data_version)
ORDER BY t.cohort_id ASC, cohort_rank ASC, t.backtest_wape ASC;
