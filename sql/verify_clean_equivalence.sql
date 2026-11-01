/*
 * =============================================================================
 * Workstream 1 Equivalence Check: PySpark vs SQL Fallback on staging.hospital_flu_clean
 *
 * Verifies that staging.hospital_flu_clean matches the SQL fallback:
 *   1. Set difference is empty in both directions (diff_a_minus_b_count = 0
 *      and diff_b_minus_a_count = 0).
 *   2. Row counts match (row_count_a = row_count_b > 0).
 *   3. (hospital_id, feed_date) is unique (duplicate_key_count = 0).
 * =============================================================================
 */

WITH
  pyspark_clean AS (
    SELECT
      hospital_id,
      hospital_name,
      region,
      state,
      urban_rural,
      bed_count,
      feed_date,
      total_flu_tests,
      positive_flu_tests,
      ROUND(positivity, 6) AS positivity,
      batch_id,
      ingested_at
    FROM `staging.hospital_flu_clean`
  ),
  sql_clean AS (
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
      IF(
        f.total_flu_tests = 0,
        CAST(NULL AS FLOAT64),
        ROUND(
          SAFE_DIVIDE(
            CAST(f.positive_flu_tests AS FLOAT64),
            CAST(f.total_flu_tests AS FLOAT64)
          ),
          6
        )
      ) AS positivity,
      f.batch_id,
      f.ingested_at
    FROM (
      SELECT
        hospital_id,
        feed_date,
        total_flu_tests,
        positive_flu_tests,
        batch_id,
        ingested_at
      FROM `raw.hospital_flu_feeds`
      QUALIFY ROW_NUMBER() OVER (
        PARTITION BY hospital_id, feed_date
        ORDER BY ingested_at DESC, batch_id DESC
      ) = 1
    ) AS f
    INNER JOIN `raw.hospital_reference` AS h
      ON f.hospital_id = h.hospital_id
  ),
  diff_a_minus_b AS (
    SELECT * FROM pyspark_clean
    EXCEPT DISTINCT
    SELECT * FROM sql_clean
  ),
  diff_b_minus_a AS (
    SELECT * FROM sql_clean
    EXCEPT DISTINCT
    SELECT * FROM pyspark_clean
  ),
  dup_keys_a AS (
    SELECT hospital_id, feed_date
    FROM pyspark_clean
    GROUP BY hospital_id, feed_date
    HAVING COUNT(*) > 1
  ),
  dup_keys_b AS (
    SELECT hospital_id, feed_date
    FROM sql_clean
    GROUP BY hospital_id, feed_date
    HAVING COUNT(*) > 1
  )
SELECT
  (SELECT COUNT(*) FROM pyspark_clean) AS row_count_a,
  (SELECT COUNT(*) FROM sql_clean) AS row_count_b,
  (SELECT COUNT(*) FROM diff_a_minus_b) AS diff_a_minus_b_count,
  (SELECT COUNT(*) FROM diff_b_minus_a) AS diff_b_minus_a_count,
  (SELECT COUNT(*) FROM dup_keys_a) + (SELECT COUNT(*) FROM dup_keys_b) AS duplicate_key_count
