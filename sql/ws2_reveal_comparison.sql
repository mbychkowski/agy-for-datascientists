-- =============================================================================
-- Workstream 2 Finale: staging.reveal_forecast_comparison
--
-- Joins the post-Cutoff Reveal Hospital Feeds (raw.hospital_flu_feeds_reveal)
-- against Northeast weekly positive flu test forecasts built from:
--   1. Deduplicated clean data (staging.hospital_flu_clean), and
--   2. Uncleaned defective data (staging.hospital_flu) containing the +35%
--      Northeast Spike duplicate backfill rows.
--
-- The uncleaned forecast projects the inflated Spike jump across the six
-- withheld Reveal weeks (2026-11-01..2026-12-12) and visibly overshoots the
-- observed Reveal counts, whereas the clean Cohort-aware forecast tracks the
-- Reveal closely.
-- =============================================================================

WITH
  uncleaned_pre_cutoff AS (
    SELECT
      SUM(IF(feed_date BETWEEN DATE '2026-10-04' AND DATE '2026-10-10', positive_flu_tests, 0)) AS w40_uncleaned_positives,
      SUM(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', positive_flu_tests, 0)) AS w42_uncleaned_positives,
      SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', positive_flu_tests, 0)) AS w43_uncleaned_positives,
      SAFE_DIVIDE(
        SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', positive_flu_tests, 0))
        - SUM(IF(feed_date BETWEEN DATE '2026-10-04' AND DATE '2026-10-10', positive_flu_tests, 0)),
        3.0
      ) AS uncleaned_weekly_slope
    FROM `staging.hospital_flu`
    WHERE region = 'Northeast'
      AND feed_date BETWEEN DATE '2026-10-04' AND DATE '2026-10-31'
  ),
  clean_hospital_weekly AS (
    SELECT
      hospital_id,
      SUM(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', total_flu_tests, 0)) AS prior_tests,
      SUM(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', positive_flu_tests, 0)) AS prior_positives,
      SAFE_DIVIDE(
        SUM(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', positive_flu_tests, 0)),
        SUM(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', total_flu_tests, 0))
      ) AS prior_positivity,
      SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', total_flu_tests, 0)) AS cutoff_tests,
      SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', positive_flu_tests, 0)) AS cutoff_positives,
      SAFE_DIVIDE(
        SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', positive_flu_tests, 0)),
        SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', total_flu_tests, 0))
      ) AS cutoff_positivity
    FROM `staging.hospital_flu_clean`
    WHERE region = 'Northeast'
      AND feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-31'
    GROUP BY hospital_id
  ),
  classified_clean_hospitals AS (
    SELECT
      h.*,
      CASE
        WHEN (h.cutoff_positivity - h.prior_positivity) >= 0.05
          AND ABS(SAFE_DIVIDE(h.cutoff_tests - h.prior_tests, h.prior_tests)) < 0.15
          THEN 'outbreak'
        WHEN SAFE_DIVIDE(h.cutoff_tests - h.prior_tests, h.prior_tests) >= 0.30
          AND ABS(h.cutoff_positivity - h.prior_positivity) < 0.02
          THEN 'sampling_artifact'
        ELSE 'seasonal_ramp'
      END AS hospital_class
    FROM clean_hospital_weekly AS h
  ),
  normal_ramp AS (
    SELECT
      COALESCE(
        SAFE_DIVIDE(
          SUM(cutoff_positives) - SUM(prior_positives),
          SUM(prior_positives)
        ),
        0.05
      ) AS ramp_ratio
    FROM classified_clean_hospitals
    WHERE hospital_class = 'seasonal_ramp'
  ),
  clean_cohort_bases AS (
    SELECT
      MAX(r.ramp_ratio) AS ramp_ratio,
      SUM(IF(c.hospital_class = 'sampling_artifact', c.prior_positives, 0)) * (1.0 + MAX(r.ramp_ratio)) AS sampling_clean_base,
      SUM(IF(c.hospital_class = 'outbreak', c.cutoff_positives, 0)) AS outbreak_clean_base,
      SUM(IF(c.hospital_class = 'seasonal_ramp', c.cutoff_positives, 0)) AS seasonal_clean_base
    FROM classified_clean_hospitals AS c
    CROSS JOIN normal_ramp AS r
  ),
  reveal_weekly AS (
    SELECT
      DATE_TRUNC(r.feed_date, WEEK(SUNDAY)) AS week_start,
      DATE_ADD(DATE_TRUNC(r.feed_date, WEEK(SUNDAY)), INTERVAL 6 DAY) AS week_end,
      DATE_DIFF(DATE_TRUNC(r.feed_date, WEEK(SUNDAY)), DATE '2026-10-25', WEEK) AS horizon_week,
      SUM(r.positive_flu_tests) AS reveal_observed_positives
    FROM `raw.hospital_flu_feeds_reveal` AS r
    INNER JOIN `raw.hospital_reference` AS h
      ON r.hospital_id = h.hospital_id
    WHERE h.region = 'Northeast'
      AND r.feed_date BETWEEN DATE '2026-11-01' AND DATE '2026-12-12'
    GROUP BY week_start, week_end, horizon_week
  ),
  projected AS (
    SELECT
      rw.horizon_week,
      rw.week_start,
      rw.week_end,
      rw.reveal_observed_positives,
      ROUND(
        (cb.sampling_clean_base + cb.seasonal_clean_base) * POW(1.0 + cb.ramp_ratio, rw.horizon_week)
        + cb.outbreak_clean_base * POW(1.0 + 0.8 * cb.ramp_ratio, rw.horizon_week),
        1
      ) AS clean_forecast_positives,
      ROUND(
        u.w43_uncleaned_positives + u.uncleaned_weekly_slope * rw.horizon_week,
        1
      ) AS uncleaned_forecast_positives
    FROM reveal_weekly AS rw
    CROSS JOIN clean_cohort_bases AS cb
    CROSS JOIN uncleaned_pre_cutoff AS u
  )
SELECT
  horizon_week,
  week_start,
  week_end,
  reveal_observed_positives,
  clean_forecast_positives,
  uncleaned_forecast_positives,
  ROUND(
    SAFE_DIVIDE(clean_forecast_positives - reveal_observed_positives, reveal_observed_positives) * 100.0,
    2
  ) AS clean_error_pct,
  ROUND(
    SAFE_DIVIDE(uncleaned_forecast_positives - reveal_observed_positives, reveal_observed_positives) * 100.0,
    2
  ) AS uncleaned_overshoot_pct
FROM projected
ORDER BY horizon_week;
