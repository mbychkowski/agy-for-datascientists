#!/usr/bin/env python3
"""Dataproc Serverless runtime 3.0 hello-world batch script for preflight verification.

Writes a single verification record to a temporary table in the demo BigQuery
dataset (`ops`) using the presenter's credentials and temporary GCS staging bucket.
"""

import argparse
from datetime import UTC, datetime


def parse_args():
    parser = argparse.ArgumentParser(
        description="Dataproc Serverless hello-world BigQuery write check"
    )
    parser.add_argument("--project-id", required=True, help="Target GCP project ID")
    parser.add_argument(
        "--dataset", default="ops", help="Target BigQuery dataset (default: ops)"
    )
    parser.add_argument(
        "--table", required=True, help="Temporary BigQuery table name to write"
    )
    parser.add_argument(
        "--staging-bucket",
        required=True,
        help="GCS staging bucket for the Spark BigQuery connector",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    from pyspark.sql import SparkSession

    spark = SparkSession.builder.appName("preflight-dataproc-hello-world").getOrCreate()
    try:
        target_table = f"{args.project_id}.{args.dataset}.{args.table}"
        now_iso = datetime.now(UTC).isoformat()
        df = spark.createDataFrame(
            [("preflight_ok", now_iso)],
            ["status", "verified_at"],
        )
        (
            df.write.format("bigquery")
            .option("table", target_table)
            .option("temporaryGcsBucket", args.staging_bucket)
            .mode("overwrite")
            .save()
        )
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
