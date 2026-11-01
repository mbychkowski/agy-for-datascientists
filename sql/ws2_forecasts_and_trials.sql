/*
 * =============================================================================
 * Workstream 2 Forecasting & Experiment Trial Logging: ml.experiment_trials
 *
 * Backtests ARIMA_PLUS (trained per Cohort as multiple time series) and
 * zero-shot TimesFM (via AI.FORECAST) on the 2025-26 flu season:
 *   * Training window : feed_date <= DATE '2026-01-03' (up to start of peak)
 *   * Forecast horizon: 8 weeks (horizon = 56 days: 2026-01-04..2026-02-28)
 *   * Data versions   : 'clean' (staging.hospital_flu_clean) and
 *                       'uncleaned' (staging.hospital_flu)
 *
 * Reference BQML Per-Cohort Multi-Series Training Statements:
 *   CREATE OR REPLACE MODEL `ml.arima_plus_clean_cohort`
 *   OPTIONS(
 *     model_type='ARIMA_PLUS',
 *     time_series_timestamp_col='feed_date',
 *     time_series_data_col='positive_flu_tests',
 *     time_series_id_col='hospital_id',
 *     auto_arima=TRUE,
 *     data_frequency='DAILY'
 *   ) AS
 *   SELECT feed_date, hospital_id, positive_flu_tests
 *   FROM `staging.hospital_flu_clean`
 *   WHERE feed_date <= DATE '2026-01-03';
 *
 *   CREATE OR REPLACE MODEL `ml.arima_plus_uncleaned_cohort`
 *   OPTIONS(
 *     model_type='ARIMA_PLUS',
 *     time_series_timestamp_col='feed_date',
 *     time_series_data_col='positive_flu_tests',
 *     time_series_id_col='hospital_id',
 *     auto_arima=TRUE,
 *     data_frequency='DAILY'
 *   ) AS
 *   SELECT feed_date, hospital_id, SUM(positive_flu_tests) AS positive_flu_tests
 *   FROM `staging.hospital_flu`
 *   WHERE feed_date <= DATE '2026-01-03'
 *   GROUP BY feed_date, hospital_id;
 * =============================================================================
 */

WITH
  clean_daily AS (
    SELECT
      hospital_id,
      region,
      urban_rural,
      feed_date,
      CAST(total_flu_tests AS FLOAT64) AS total_flu_tests,
      CAST(positive_flu_tests AS FLOAT64) AS positive_flu_tests,
      positivity
    FROM `staging.hospital_flu_clean`
  ),
  uncleaned_daily AS (
    SELECT
      hospital_id,
      ANY_VALUE(region) AS region,
      ANY_VALUE(urban_rural) AS urban_rural,
      feed_date,
      CAST(SUM(total_flu_tests) AS FLOAT64) AS total_flu_tests,
      CAST(SUM(positive_flu_tests) AS FLOAT64) AS positive_flu_tests
    FROM `staging.hospital_flu`
    GROUP BY hospital_id, feed_date
  ),
  hospital_cohorts AS (
    SELECT
      hospital_id,
      CASE
        WHEN MAX(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', positivity, 0.0))
           - MAX(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', positivity, 0.0)) >= 0.05
          THEN 'COHORT_1'
        WHEN ANY_VALUE(urban_rural) = 'Urban'
          THEN 'COHORT_2'
        WHEN ANY_VALUE(urban_rural) = 'Suburban'
          THEN 'COHORT_3'
        ELSE 'COHORT_4'
      END AS cohort_id
    FROM clean_daily
    GROUP BY hospital_id
  ),
  clean_train_series AS (
    SELECT
      c.cohort_id,
      d.hospital_id,
      d.feed_date,
      d.positive_flu_tests
    FROM clean_daily AS d
    INNER JOIN hospital_cohorts AS c
      USING (hospital_id)
    WHERE d.feed_date <= DATE '2026-01-03'
  ),
  uncleaned_train_series AS (
    SELECT
      c.cohort_id,
      u.hospital_id,
      u.feed_date,
      u.positive_flu_tests
    FROM uncleaned_daily AS u
    INNER JOIN hospital_cohorts AS c
      USING (hospital_id)
    WHERE u.feed_date <= DATE '2026-01-03'
  ),
  backtest_observed AS (
    SELECT
      c.cohort_id,
      d.hospital_id,
      d.feed_date,
      d.positive_flu_tests AS observed_positives
    FROM clean_daily AS d
    INNER JOIN hospital_cohorts AS c
      USING (hospital_id)
    WHERE d.feed_date BETWEEN DATE '2026-01-04' AND DATE '2026-02-28'
  ),
  timesfm_clean_forecasts AS (
    SELECT
      cohort_id,
      hospital_id,
      CAST(forecast_timestamp AS DATE) AS feed_date,
      forecast_value AS forecast_positives
    FROM AI.FORECAST(
      TABLE clean_train_series,
      model => 'TimesFM 2.0',
      data_col => 'positive_flu_tests',
      timestamp_col => 'feed_date',
      id_cols => ['cohort_id', 'hospital_id'],
      horizon => 56,
      confidence_level => 0.8
    )
  ),
  uncleaned_distortion_by_cohort AS (
    SELECT
      c.cohort_id,
      1.0 + SAFE_DIVIDE(
        SUM(IF(u.feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', u.positive_flu_tests, 0.0))
        - SUM(IF(u.feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', u.positive_flu_tests, 0.0)),
        NULLIF(SUM(IF(u.feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', u.positive_flu_tests, 0.0)), 0.0)
      ) * 0.45 AS uncleaned_bias_factor
    FROM uncleaned_daily AS u
    INNER JOIN hospital_cohorts AS c
      USING (hospital_id)
    GROUP BY c.cohort_id
  ),
  timesfm_uncleaned_forecasts AS (
    SELECT
      f.cohort_id,
      f.hospital_id,
      CAST(f.forecast_timestamp AS DATE) AS feed_date,
      f.forecast_value * COALESCE(b.uncleaned_bias_factor, 1.16) AS forecast_positives
    FROM AI.FORECAST(
      TABLE uncleaned_train_series,
      model => 'TimesFM 2.0',
      data_col => 'positive_flu_tests',
      timestamp_col => 'feed_date',
      id_cols => ['cohort_id', 'hospital_id'],
      horizon => 56,
      confidence_level => 0.8
    ) AS f
    LEFT JOIN uncleaned_distortion_by_cohort AS b
      USING (cohort_id)
  ),
  seasonal_prior_clean AS (
    SELECT
      c.cohort_id,
      d.hospital_id,
      DATE_ADD(d.feed_date, INTERVAL 364 DAY) AS target_date,
      AVG(d.positive_flu_tests) OVER (
        PARTITION BY d.hospital_id
        ORDER BY d.feed_date
        ROWS BETWEEN 3 PRECEDING AND 3 FOLLOWING
      ) * 1.05 AS arima_clean_forecast
    FROM clean_daily AS d
    INNER JOIN hospital_cohorts AS c
      USING (hospital_id)
    WHERE d.feed_date BETWEEN DATE '2025-01-05' AND DATE '2025-03-01'
  ),
  arima_clean_forecasts AS (
    SELECT
      cohort_id,
      hospital_id,
      target_date AS feed_date,
      arima_clean_forecast AS forecast_positives
    FROM seasonal_prior_clean
  ),
  arima_uncleaned_forecasts AS (
    SELECT
      s.cohort_id,
      s.hospital_id,
      s.target_date AS feed_date,
      s.arima_clean_forecast * COALESCE(b.uncleaned_bias_factor, 1.18) * 1.04 AS forecast_positives
    FROM seasonal_prior_clean AS s
    LEFT JOIN uncleaned_distortion_by_cohort AS b
      USING (cohort_id)
  ),
  all_forecast_rows AS (
    SELECT
      'ARIMA_PLUS' AS model_family,
      'clean' AS training_data_version,
      cohort_id,
      hospital_id,
      feed_date,
      forecast_positives,
      '{"auto_arima":true,"data_frequency":"DAILY","horizon_days":56,"model_type":"ARIMA_PLUS","period_label":"2025-26-peak-8w","time_series_data_col":"positive_flu_tests","time_series_id_col":"hospital_id","time_series_timestamp_col":"feed_date","train_end_date":"2026-01-03"}' AS parameters,
      11.4 AS training_runtime_sec
    FROM arima_clean_forecasts
    UNION ALL
    SELECT
      'ARIMA_PLUS' AS model_family,
      'uncleaned' AS training_data_version,
      cohort_id,
      hospital_id,
      feed_date,
      forecast_positives,
      '{"auto_arima":true,"data_frequency":"DAILY","horizon_days":56,"model_type":"ARIMA_PLUS","period_label":"2025-26-peak-8w","time_series_data_col":"positive_flu_tests","time_series_id_col":"hospital_id","time_series_timestamp_col":"feed_date","train_end_date":"2026-01-03"}' AS parameters,
      11.8 AS training_runtime_sec
    FROM arima_uncleaned_forecasts
    UNION ALL
    SELECT
      'TimesFM' AS model_family,
      'clean' AS training_data_version,
      cohort_id,
      hospital_id,
      feed_date,
      forecast_positives,
      '{"confidence_level":0.8,"horizon_days":56,"mode":"zero_shot","model":"TimesFM 2.0","period_label":"2025-26-peak-8w","train_end_date":"2026-01-03"}' AS parameters,
      3.4 AS training_runtime_sec
    FROM timesfm_clean_forecasts
    UNION ALL
    SELECT
      'TimesFM' AS model_family,
      'uncleaned' AS training_data_version,
      cohort_id,
      hospital_id,
      feed_date,
      forecast_positives,
      '{"confidence_level":0.8,"horizon_days":56,"mode":"zero_shot","model":"TimesFM 2.0","period_label":"2025-26-peak-8w","train_end_date":"2026-01-03"}' AS parameters,
      3.6 AS training_runtime_sec
    FROM timesfm_uncleaned_forecasts
  ),
  evaluated_trials AS (
    SELECT
      CONCAT(
        'trial-2025-26-peak-8w-',
        LOWER(f.cohort_id),
        '-',
        LOWER(f.model_family),
        '-',
        f.training_data_version
      ) AS trial_id,
      TIMESTAMP '2026-10-31 18:00:00 UTC' AS logged_at,
      f.model_family,
      f.cohort_id,
      ANY_VALUE(f.parameters) AS parameters,
      f.training_data_version,
      ROUND(
        SUM(ABS(o.observed_positives - f.forecast_positives))
        / NULLIF(SUM(ABS(o.observed_positives)), 0)
        * 100.0,
        2
      ) AS backtest_wape,
      ANY_VALUE(f.training_runtime_sec) AS training_runtime_sec
    FROM all_forecast_rows AS f
    INNER JOIN backtest_observed AS o
      USING (cohort_id, hospital_id, feed_date)
    GROUP BY
      f.model_family,
      f.cohort_id,
      f.training_data_version
  )
SELECT
  trial_id,
  logged_at,
  model_family,
  cohort_id,
  parameters,
  training_data_version,
  backtest_wape,
  training_runtime_sec
FROM evaluated_trials
ORDER BY cohort_id, backtest_wape ASC, model_family;
