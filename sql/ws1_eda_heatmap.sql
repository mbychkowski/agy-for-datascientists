-- Workstream 1 Exploratory Data Analysis: Hospital x Week Heatmap & Spike Concentration
-- Computes weekly positive counts, total tests, Positivity, duplicate row counts, and
-- each hospital's share of the Northeast Spike in the week ending on the Cutoff (2026-10-31).

WITH
  hospital_weekly AS (
    SELECT
      hospital_id,
      hospital_name,
      region,
      state,
      urban_rural,
      bed_count,
      DATE_TRUNC(feed_date, WEEK(SUNDAY)) AS week_start,
      DATE_ADD(DATE_TRUNC(feed_date, WEEK(SUNDAY)), INTERVAL 6 DAY) AS week_end,
      COUNT(*) AS physical_feed_rows,
      COUNT(DISTINCT feed_date) AS distinct_feed_days,
      COUNT(*) - COUNT(DISTINCT feed_date) AS duplicate_feed_rows,
      SUM(total_flu_tests) AS total_flu_tests,
      SUM(positive_flu_tests) AS positive_flu_tests,
      SAFE_DIVIDE(SUM(positive_flu_tests), SUM(total_flu_tests)) AS positivity
    FROM `staging.hospital_flu`
    WHERE feed_date BETWEEN DATE '2026-10-04' AND DATE '2026-10-31'
    GROUP BY
      hospital_id,
      hospital_name,
      region,
      state,
      urban_rural,
      bed_count,
      week_start,
      week_end
  ),
  prior_vs_cutoff AS (
    SELECT
      hospital_id,
      MAX(IF(week_start = DATE '2026-10-18', total_flu_tests, 0)) AS prior_week_tests,
      MAX(IF(week_start = DATE '2026-10-18', positive_flu_tests, 0)) AS prior_week_positives,
      MAX(IF(week_start = DATE '2026-10-18', positivity, NULL)) AS prior_week_positivity,
      MAX(IF(week_start = DATE '2026-10-25', total_flu_tests, 0)) AS cutoff_week_tests,
      MAX(IF(week_start = DATE '2026-10-25', positive_flu_tests, 0)) AS cutoff_week_positives,
      MAX(IF(week_start = DATE '2026-10-25', positivity, NULL)) AS cutoff_week_positivity,
      MAX(IF(week_start = DATE '2026-10-25', duplicate_feed_rows, 0)) AS cutoff_week_duplicate_rows
    FROM hospital_weekly
    GROUP BY hospital_id
  ),
  ne_totals AS (
    SELECT
      SUM(IF(w.week_start = DATE '2026-10-18' AND w.region = 'Northeast', w.positive_flu_tests, 0)) AS ne_prior_positives,
      SUM(IF(w.week_start = DATE '2026-10-25' AND w.region = 'Northeast', w.positive_flu_tests, 0)) AS ne_cutoff_positives
    FROM hospital_weekly AS w
  )
SELECT
  w.hospital_id,
  w.hospital_name,
  w.region,
  w.state,
  w.urban_rural,
  w.bed_count,
  w.week_start,
  w.week_end,
  w.physical_feed_rows,
  w.distinct_feed_days,
  w.duplicate_feed_rows,
  w.total_flu_tests,
  w.positive_flu_tests,
  ROUND(w.positivity, 4) AS positivity,
  p.cutoff_week_positives - p.prior_week_positives AS wow_positive_delta,
  ROUND(
    SAFE_DIVIDE(p.cutoff_week_tests - p.prior_week_tests, p.prior_week_tests) * 100.0,
    2
  ) AS wow_test_volume_pct,
  ROUND(
    IF(
      w.region = 'Northeast',
      SAFE_DIVIDE(p.cutoff_week_positives - p.prior_week_positives, n.ne_prior_positives) * 100.0,
      0.0
    ),
    2
  ) AS ne_spike_points_contributed,
  ROUND(
    IF(
      w.region = 'Northeast',
      SAFE_DIVIDE(
        p.cutoff_week_positives - p.prior_week_positives,
        n.ne_cutoff_positives - n.ne_prior_positives
      ) * 100.0,
      0.0
    ),
    2
  ) AS share_of_ne_spike_pct
FROM hospital_weekly AS w
INNER JOIN prior_vs_cutoff AS p
  USING (hospital_id)
CROSS JOIN ne_totals AS n
ORDER BY w.region, ne_spike_points_contributed DESC, w.hospital_id, w.week_start;
