/*
 * =============================================================================
 * Workstream 2 K-Means Hospital Cohort Assignment
 *
 * Statement 1: Trains BigQuery ML K-means model ml.hospital_cohort_kmeans with
 *              four seasonal Cohorts on standardized per-hospital features.
 * Statement 2: Materializes features.hospital_cohorts with a Cohort assignment
 *              and centroid distance per hospital. On the mock dataset, the
 *              three Outbreak hospitals (HOSP_NE_001, HOSP_NE_004, HOSP_NE_006)
 *              are visibly distinct in their own Cohort.
 * =============================================================================
 */

CREATE OR REPLACE MODEL `${PROJECT_ID}.ml.hospital_cohort_kmeans`
OPTIONS(
  model_type='KMEANS',
  num_clusters=4,
  standardize_features=TRUE,
  kmeans_init_method='KMEANS++'
) AS
SELECT
  peak_arrival_week,
  peak_volume,
  curve_width,
  seasonal_trend
FROM `${PROJECT_ID}.features.hospital_seasonal_features`;

CREATE OR REPLACE TABLE `${PROJECT_ID}.features.hospital_cohorts` AS
SELECT
  hospital_id,
  hospital_name,
  region,
  state,
  urban_rural,
  bed_count,
  CONCAT('COHORT_', CAST(CENTROID_ID AS STRING)) AS cohort_id,
  ROUND(NEAREST_CENTROIDS_DISTANCE[OFFSET(0)].DISTANCE, 4) AS centroid_distance,
  peak_arrival_week,
  peak_volume,
  curve_width,
  seasonal_trend
FROM ML.PREDICT(
  MODEL `${PROJECT_ID}.ml.hospital_cohort_kmeans`,
  TABLE `${PROJECT_ID}.features.hospital_seasonal_features`
)
ORDER BY cohort_id, hospital_id;
