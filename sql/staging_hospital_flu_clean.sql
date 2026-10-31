-- =============================================================================
-- Workstream 1 SQL Fallback: staging.hospital_flu_clean
--
-- Deduplicates raw.hospital_flu_feeds by (hospital_id, feed_date) using a
-- window function (keeping latest ingested_at, then lexicographically greatest
-- batch_id), joins raw.hospital_reference, and computes null-safe Positivity.
-- =============================================================================

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
    SAFE_DIVIDE(
      CAST(f.positive_flu_tests AS FLOAT64),
      CAST(f.total_flu_tests AS FLOAT64)
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
