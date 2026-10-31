#!/usr/bin/env python3
"""Workstream 1 PySpark pipeline v1 (defective staging build).

Reads `raw.hospital_flu_feeds` and `raw.hospital_reference` from BigQuery,
joins them on `hospital_id`, and writes `staging.hospital_flu` with the
duplicate Hospital Feed rows intact (the planted Pipeline Defect).
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from typing import Any

STAGING_COLUMNS: tuple[str, ...] = (
    "hospital_id",
    "hospital_name",
    "region",
    "state",
    "urban_rural",
    "bed_count",
    "feed_date",
    "total_flu_tests",
    "positive_flu_tests",
    "batch_id",
    "ingested_at",
)


def build_v1_rows(
    feeds: Sequence[Mapping[str, Any]],
    hospitals: Sequence[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Join in-memory Hospital Feed rows with hospital reference rows without deduplication.

    Preserves every row from `feeds` (with the duplicates intact) whose
    `hospital_id` exists in `hospitals`, returning rows with columns in
    `STAGING_COLUMNS` order.
    """
    hosp_by_id: dict[str, Mapping[str, Any]] = {
        str(h["hospital_id"]): h for h in hospitals
    }
    output: list[dict[str, object]] = []
    for feed in feeds:
        hid = str(feed["hospital_id"])
        hosp = hosp_by_id.get(hid)
        if hosp is None:
            continue
        output.append(
            {
                "hospital_id": hid,
                "hospital_name": str(hosp["hospital_name"]),
                "region": str(hosp["region"]),
                "state": str(hosp["state"]),
                "urban_rural": str(hosp["urban_rural"]),
                "bed_count": int(hosp["bed_count"]),
                "feed_date": str(feed["feed_date"]),
                "total_flu_tests": int(feed["total_flu_tests"]),
                "positive_flu_tests": int(feed["positive_flu_tests"]),
                "batch_id": str(feed["batch_id"]),
                "ingested_at": str(feed["ingested_at"]),
            }
        )
    return output


def transform_v1_dataframe(feeds_df: Any, hospitals_df: Any) -> Any:
    """Join Hospital Feeds with hospital reference metadata without deduplication.

    Pipeline v1 intentionally omits deduplication on `(hospital_id, feed_date)`
    so the Pipeline Defect (duplicate backfill rows) remains intact in
    `staging.hospital_flu` at the Workstream 1 Start Point.
    """
    joined = feeds_df.join(hospitals_df, on="hospital_id", how="inner")
    return joined.select(*STAGING_COLUMNS)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for the Workstream 1 v1 PySpark pipeline."""
    parser = argparse.ArgumentParser(
        description="Workstream 1 PySpark pipeline v1 (leaves duplicate Hospital Feeds intact)"
    )
    parser.add_argument("--project-id", required=True, help="Target GCP project ID")
    parser.add_argument(
        "--raw-dataset",
        default="raw",
        help="Source BigQuery raw dataset name (default: raw)",
    )
    parser.add_argument(
        "--staging-dataset",
        default="staging",
        help="Target BigQuery staging dataset name (default: staging)",
    )
    parser.add_argument(
        "--output-table",
        default="hospital_flu",
        help="Target BigQuery table in staging dataset (default: hospital_flu)",
    )
    parser.add_argument(
        "--staging-bucket",
        required=True,
        help="GCS staging bucket for the Spark BigQuery connector",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Execute pipeline v1 on Dataproc Serverless and materialise staging.hospital_flu."""
    args = parse_args(argv)
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("workstream-1-pipeline-v1").getOrCreate()
    try:
        feeds_table = f"{args.project_id}.{args.raw_dataset}.hospital_flu_feeds"
        hospitals_table = f"{args.project_id}.{args.raw_dataset}.hospital_reference"
        target_table = f"{args.project_id}.{args.staging_dataset}.{args.output_table}"

        feeds_df = spark.read.format("bigquery").option("table", feeds_table).load()
        hospitals_df = (
            spark.read.format("bigquery").option("table", hospitals_table).load()
        )
        staging_df = transform_v1_dataframe(feeds_df, hospitals_df)

        (
            staging_df.write.format("bigquery")
            .option("table", target_table)
            .option("temporaryGcsBucket", args.staging_bucket)
            .mode("overwrite")
            .save()
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
