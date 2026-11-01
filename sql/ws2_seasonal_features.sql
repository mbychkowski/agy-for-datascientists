/*
 * =============================================================================
 * Workstream 2 Seasonal Feature Engineering: features.hospital_seasonal_features
 *
 * Computes four per-hospital seasonal features from staging.hospital_flu_clean
 * up to the Cutoff (2026-10-31):
 *   1. peak_arrival_week : Average seasonal week offset (from MMWR Week 40)
 *                          when the hospital reaches its seasonal peak positive
 *                          flu test count across historical seasons.
 *   2. peak_volume       : Average weekly positive flu test count at the
 *                          seasonal peak across historical seasons.
 *   3. curve_width       : Average number of weeks per season where weekly
 *                          positive flu tests are at least 50% of that season's
 *                          peak (full width at half maximum, measuring broad
 *                          versus sharp seasonal waves).
 *   4. seasonal_trend    : Early-season Positivity ratio comparing the Spike
 *                          week ending on the Cutoff (2026-10-25..2026-10-31)
 *                          against the prior baseline week (2026-10-18..2026-10-24).
 * =============================================================================
 */

WITH
  hospital_metadata AS (
    SELECT
      hospital_id,
      ANY_VALUE(hospital_name) AS hospital_name,
      ANY_VALUE(region) AS region,
      ANY_VALUE(state) AS state,
      ANY_VALUE(urban_rural) AS urban_rural,
      ANY_VALUE(bed_count) AS bed_count
    FROM `staging.hospital_flu_clean`
    GROUP BY hospital_id
  ),
  historical_weekly AS (
    SELECT
      hospital_id,
      CASE
        WHEN feed_date < DATE '2024-09-29' THEN DATE '2023-10-01'
        WHEN feed_date < DATE '2025-09-28' THEN DATE '2024-09-29'
        ELSE DATE '2025-09-28'
      END AS season_start,
      DIV(
        DATE_DIFF(
          DATE_TRUNC(feed_date, WEEK(SUNDAY)),
          CASE
            WHEN feed_date < DATE '2024-09-29' THEN DATE '2023-10-01'
            WHEN feed_date < DATE '2025-09-28' THEN DATE '2024-09-29'
            ELSE DATE '2025-09-28'
          END,
          DAY
        ),
        7
      ) AS season_week_offset,
      SUM(positive_flu_tests) AS weekly_positives
    FROM `staging.hospital_flu_clean`
    WHERE feed_date < DATE '2026-10-04'
    GROUP BY hospital_id, season_start, season_week_offset
  ),
  season_peaks AS (
    SELECT
      hospital_id,
      season_start,
      MAX(weekly_positives) AS season_peak_positives
    FROM historical_weekly
    GROUP BY hospital_id, season_start
  ),
  season_metrics AS (
    SELECT
      w.hospital_id,
      w.season_start,
      ANY_VALUE(p.season_peak_positives) AS season_peak_positives,
      MIN(
        IF(
          w.weekly_positives = p.season_peak_positives,
          w.season_week_offset,
          NULL
        )
      ) AS season_peak_week_offset,
      COUNTIF(w.weekly_positives >= 0.5 * p.season_peak_positives) AS season_curve_width
    FROM historical_weekly AS w
    INNER JOIN season_peaks AS p
      USING (hospital_id, season_start)
    GROUP BY w.hospital_id, w.season_start
  ),
  historical_features AS (
    SELECT
      hospital_id,
      ROUND(AVG(CAST(season_peak_week_offset AS FLOAT64)), 4) AS peak_arrival_week,
      ROUND(AVG(CAST(season_peak_positives AS FLOAT64)), 4) AS peak_volume,
      ROUND(AVG(CAST(season_curve_width AS FLOAT64)), 4) AS curve_width
    FROM season_metrics
    GROUP BY hospital_id
  ),
  cutoff_window AS (
    SELECT
      hospital_id,
      SAFE_DIVIDE(
        SUM(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', positive_flu_tests, 0)),
        SUM(IF(feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-24', total_flu_tests, 0))
      ) AS baseline_week_positivity,
      SAFE_DIVIDE(
        SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', positive_flu_tests, 0)),
        SUM(IF(feed_date BETWEEN DATE '2026-10-25' AND DATE '2026-10-31', total_flu_tests, 0))
      ) AS cutoff_week_positivity
    FROM `staging.hospital_flu_clean`
    WHERE feed_date BETWEEN DATE '2026-10-18' AND DATE '2026-10-31'
    GROUP BY hospital_id
  )
SELECT
  m.hospital_id,
  m.hospital_name,
  m.region,
  m.state,
  m.urban_rural,
  m.bed_count,
  h.peak_arrival_week,
  h.peak_volume,
  h.curve_width,
  ROUND(
    COALESCE(
      SAFE_DIVIDE(c.cutoff_week_positivity, c.baseline_week_positivity),
      1.0
    ),
    4
  ) AS seasonal_trend
FROM hospital_metadata AS m
INNER JOIN historical_features AS h
  USING (hospital_id)
LEFT JOIN cutoff_window AS c
  USING (hospital_id)
ORDER BY m.hospital_id;
