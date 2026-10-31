"""Tests for Issue #10: Workstream 1 one-time setup, pipeline v1, and verify-start-point ws1."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from lib.mock_dataset_generator import (
    BASELINE_WEEK_END,
    BASELINE_WEEK_START,
    CUTOFF_DATE,
    SPIKE_WEEK_START,
)
from pipelines.pipeline_v1 import (
    STAGING_COLUMNS,
    build_v1_rows,
    parse_args,
    transform_v1_dataframe,
)
from tests.helpers import (
    SETUP_BIN,
    SETUP_SYMLINK,
    VERIFY_START_POINT_BIN,
    VERIFY_START_POINT_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
RUN_PIPELINE_V1_BIN = WORKTREE_ROOT / "bin" / "run-pipeline-v1"
GUARDRAIL_HOOK = (
    WORKTREE_ROOT
    / ".agents"
    / "plugins"
    / "ds-command-center"
    / "bin"
    / "guardrail-hook"
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _parse_logged_commands(log_file: Path) -> list[str]:
    """Group multi-line logged CLI invocations (such as multi-line bq query SQL) into full commands."""
    commands: list[str] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(("bq ", "gcloud ", "agy ")) or not commands:
            commands.append(line)
        else:
            commands[-1] = f"{commands[-1]}\n{line}"
    return commands


class _FakeDataFrame:
    """Minimal DataFrame double to verify transform_v1_dataframe joins without deduplicating."""

    def __init__(self, name: str, history: tuple[tuple[str, Any], ...] = ()) -> None:
        self.name = name
        self.history = history

    def join(
        self, other: _FakeDataFrame, on: str, how: str = "inner"
    ) -> _FakeDataFrame:
        return _FakeDataFrame(
            f"{self.name}_join_{other.name}",
            (*self.history, ("join", (other.name, on, how))),
        )

    def select(self, *cols: str) -> _FakeDataFrame:
        return _FakeDataFrame(
            self.name,
            (*self.history, ("select", cols)),
        )


class TestWorkstream1SetupAndVerify(unittest.TestCase):
    def test_pipeline_v1_preserves_duplicates_and_northeast_spike_on_mock_dataset(
        self,
    ) -> None:
        """Pipeline v1 must join hospital metadata while keeping duplicate backfill rows and the +35.0% Northeast Spike intact."""
        hospitals = _read_csv(MOCK_DATASET_DIR / "raw" / "hospital_reference.csv")
        feeds = _read_csv(MOCK_DATASET_DIR / "raw" / "hospital_flu_feeds" / "feeds.csv")

        v1_rows = build_v1_rows(feeds, hospitals)

        # Row count equals raw feeds row count; duplicate (hospital_id, feed_date) pairs are intact
        self.assertEqual(len(v1_rows), len(feeds))
        key_counts = Counter(
            (str(r["hospital_id"]), str(r["feed_date"])) for r in v1_rows
        )
        duplicate_keys = {k: count for k, count in key_counts.items() if count > 1}
        self.assertGreater(
            len(duplicate_keys),
            0,
            "Pipeline v1 must leave duplicate (hospital_id, feed_date) rows intact",
        )
        self.assertEqual(len(duplicate_keys), 20)

        # Every output row has the exact staging columns and non-empty joined hospital metadata
        for row in v1_rows:
            self.assertEqual(tuple(row.keys()), STAGING_COLUMNS)
            self.assertTrue(row["hospital_name"])
            self.assertIn(row["region"], {"Northeast", "Midwest", "South", "West"})
            self.assertTrue(row["state"])
            self.assertIn(row["urban_rural"], {"Urban", "Suburban", "Rural"})
            self.assertGreater(int(row["bed_count"]), 0)

        # Northeast Spike in the week ending on the Cutoff (2026-10-31) vs prior week is +35.0%
        w42_ne_positives = 0
        w43_ne_positives = 0
        for row in v1_rows:
            if row["region"] != "Northeast":
                continue
            fdate = date.fromisoformat(str(row["feed_date"]))
            pos = int(row["positive_flu_tests"])
            if BASELINE_WEEK_START <= fdate <= BASELINE_WEEK_END:
                w42_ne_positives += pos
            elif SPIKE_WEEK_START <= fdate <= CUTOFF_DATE:
                w43_ne_positives += pos

        self.assertGreater(w42_ne_positives, 0)
        spike_pct = ((w43_ne_positives - w42_ne_positives) / w42_ne_positives) * 100.0
        self.assertAlmostEqual(spike_pct, 35.0, places=2)

        # Verify DataFrame transformation and CLI argument defaults
        feeds_df = _FakeDataFrame("feeds")
        hospitals_df = _FakeDataFrame("hospitals")
        result_df = transform_v1_dataframe(feeds_df, hospitals_df)
        self.assertEqual(
            result_df.history,
            (
                ("join", ("hospitals", "hospital_id", "inner")),
                ("select", STAGING_COLUMNS),
            ),
        )

        parsed = parse_args(
            ["--project-id", "demo-proj-123", "--staging-bucket", "demo-staging-bucket"]
        )
        self.assertEqual(parsed.project_id, "demo-proj-123")
        self.assertEqual(parsed.raw_dataset, "raw")
        self.assertEqual(parsed.staging_dataset, "staging")
        self.assertEqual(parsed.output_table, "hospital_flu")
        self.assertEqual(parsed.staging_bucket, "demo-staging-bucket")

    def test_setup_loads_mock_dataset_runs_pipeline_v1_labels_tables_and_verifies_ws1(
        self,
    ) -> None:
        """bin/setup must load raw/ops tables, submit pipeline v1 on Dataproc Serverless 3.0, label staging.hospital_flu, and verify ws1."""
        for path in (
            SETUP_BIN,
            SETUP_SYMLINK,
            RUN_PIPELINE_V1_BIN,
            VERIFY_START_POINT_BIN,
            VERIFY_START_POINT_SYMLINK,
        ):
            self.assertTrue(path.exists(), f"{path} must exist")
            self.assertTrue(os.access(path, os.X_OK), f"{path} must be executable")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                subnet="projects/demo-proj-123/regions/us-central1/subnetworks/custom-sub",
            )

            proc = subprocess.run(
                [
                    str(SETUP_SYMLINK),
                    "--env",
                    str(env_file),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"setup failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )
            self.assertIn("[PASS]", proc.stdout)

            calls = _parse_logged_commands(log_file)

            # 1. Raw and ops tables loaded with --replace and labelled demo:true
            for tbl in (
                "demo-proj-123:raw.hospital_reference",
                "demo-proj-123:raw.hospital_flu_feeds",
                "demo-proj-123:ops.pipeline_run_log",
            ):
                self.assertTrue(
                    any("load --replace" in c and tbl in c for c in calls),
                    f"Expected bq load --replace for {tbl}",
                )
                self.assertTrue(
                    any(
                        "update --set_label demo:true" in c and tbl in c for c in calls
                    ),
                    f"Expected bq update --set_label demo:true for {tbl}",
                )

            # 2. Dataproc Serverless batch submission for pipeline_v1.py
            dataproc_calls = [
                c for c in calls if "gcloud dataproc batches submit pyspark" in c
            ]
            self.assertEqual(len(dataproc_calls), 1)
            dp_call = dataproc_calls[0]
            self.assertIn("pipelines/pipeline_v1.py", dp_call)
            self.assertIn("--project=demo-proj-123", dp_call)
            self.assertIn("--region=us-central1", dp_call)
            self.assertIn("--batch=ws1-pipeline-v1-test", dp_call)
            self.assertIn("--version=3.0", dp_call)
            self.assertIn(
                "--subnet=projects/demo-proj-123/regions/us-central1/subnetworks/custom-sub",
                dp_call,
            )
            self.assertNotIn("--service-account", dp_call)
            self.assertNotIn("ShieldedVm", dp_call)
            self.assertIn(
                "--project-id demo-proj-123 --raw-dataset raw --staging-dataset staging --output-table hospital_flu",
                dp_call,
            )

            # 3. staging.hospital_flu labelled demo:true after Dataproc batch
            dp_idx = next(
                i
                for i, c in enumerate(calls)
                if "gcloud dataproc batches submit pyspark" in c
            )
            staging_label_indices = [
                i
                for i, c in enumerate(calls)
                if "update --set_label demo:true" in c
                and "demo-proj-123:staging.hospital_flu" in c
            ]
            self.assertEqual(len(staging_label_indices), 1)
            self.assertGreater(staging_label_indices[0], dp_idx)

            # 4. verify-start-point ws1 ran bq show and read-only bq query
            self.assertTrue(
                any(
                    "bq show" in c and "demo-proj-123:staging.hospital_flu" in c
                    for c in calls
                )
            )
            self.assertTrue(
                any("bq query" in c and "duplicate_groups" in c for c in calls)
            )

        # Also verify positional dataset location (e.g., gs:// URI from Data Generator)
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
            )
            proc = subprocess.run(
                [
                    str(SETUP_BIN),
                    "--env",
                    str(env_file),
                    "gs://demo-staging-bucket/generated_dataset",
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"setup with positional gs:// path failed:\n{proc.stdout}\n{proc.stderr}",
            )
            calls_text = log_file.read_text(encoding="utf-8")
            self.assertIn(
                "gs://demo-staging-bucket/generated_dataset/raw/hospital_reference.csv",
                calls_text,
            )
            self.assertIn(
                "gs://demo-staging-bucket/generated_dataset/raw/hospital_flu_feeds/feeds.csv",
                calls_text,
            )
            self.assertIn(
                "gs://demo-staging-bucket/generated_dataset/ops/pipeline_run_log.csv",
                calls_text,
            )

    def test_setup_is_idempotent_and_stays_within_demo_datasets(self) -> None:
        """Running bin/setup twice must succeed both times and touch only raw, ops, and staging.hospital_flu."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
            )

            for run_idx in (1, 2):
                env["PIPELINE_V1_BATCH_ID"] = f"ws1-pipeline-v1-test-{run_idx}"
                proc = subprocess.run(
                    [
                        str(SETUP_BIN),
                        "--env",
                        str(env_file),
                        "--dataset-dir",
                        str(MOCK_DATASET_DIR),
                    ],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    proc.returncode,
                    0,
                    f"Run {run_idx} failed:\n{proc.stdout}\n{proc.stderr}",
                )

            calls = _parse_logged_commands(log_file)
            allowed_table_refs = {
                "demo-proj-123:raw.hospital_reference",
                "demo-proj-123:raw.hospital_flu_feeds",
                "demo-proj-123:ops.pipeline_run_log",
                "demo-proj-123:staging.hospital_flu",
            }
            write_calls = [
                c
                for c in calls
                if c.startswith("bq ") and (" load " in c or " update " in c)
            ]
            self.assertEqual(
                len(write_calls),
                14,
                "Expected 7 bq write/label calls per setup run across 2 runs",
            )
            for call in write_calls:
                self.assertTrue(
                    any(ref in call for ref in allowed_table_refs),
                    f"Unexpected bq write target in call: {call}",
                )
                for forbidden in ("features.", "ml.", "checkpoint."):
                    self.assertNotIn(forbidden, call)

    def test_verify_start_point_ws1_is_readonly_and_passes_guardrail_hook(self) -> None:
        """verify-start-point ws1 must issue only read-only bq commands that are allowed by guardrail-hook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
            )

            proc = subprocess.run(
                [str(VERIFY_START_POINT_SYMLINK), "ws1", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"verify-start-point ws1 failed:\n{proc.stdout}\n{proc.stderr}",
            )
            self.assertIn("[PASS]", proc.stdout)

            calls = _parse_logged_commands(log_file)
            self.assertGreaterEqual(len(calls), 5)

            for cmd_line in calls:
                self.assertTrue(cmd_line.startswith("bq "))
                for mutating_token in (
                    " load ",
                    " update ",
                    " rm ",
                    " cp ",
                    " mk ",
                    "INSERT",
                    "UPDATE",
                    "DELETE",
                    "DROP",
                    "CREATE",
                    "ALTER",
                    "TRUNCATE",
                    "MERGE",
                ):
                    self.assertNotIn(mutating_token, cmd_line)

                payload = {
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": cmd_line},
                    },
                    "stepIdx": 1,
                }
                hook_proc = subprocess.run(
                    [str(GUARDRAIL_HOOK)],
                    cwd=WORKTREE_ROOT,
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(hook_proc.returncode, 0)
                decision = json.loads(hook_proc.stdout)
                self.assertEqual(
                    decision.get("decision"),
                    "allow",
                    f"Guardrail hook blocked verify-start-point command: {cmd_line} -> {decision}",
                )

    def test_verify_start_point_ws1_fails_on_missing_table_label_duplicates_or_spike(
        self,
    ) -> None:
        """verify-start-point ws1 must exit non-zero when a table or label is missing, duplicates are removed, or the Northeast Spike is wrong."""
        failure_cases: list[tuple[dict[str, Any], str]] = [
            (
                {"ws1_missing_table": "staging.hospital_flu"},
                "Required Workstream 1 table missing: demo-proj-123:staging.hospital_flu",
            ),
            (
                {"ws1_missing_label": "staging.hospital_flu"},
                "Table demo-proj-123:staging.hospital_flu is missing required label demo:true",
            ),
            (
                {"ws1_no_duplicates": True},
                "Defective staging table staging.hospital_flu has no duplicate",
            ),
            (
                {"ws1_wrong_spike": True},
                "Northeast Spike in week ending on Cutoff (2026-10-31) is 12.50%",
            ),
        ]

        for kwargs, expected_msg in failure_cases:
            with self.subTest(**kwargs), tempfile.TemporaryDirectory() as tmpdir:
                env_file, env, _ = setup_preflight_test_env(
                    tmpdir,
                    project_id="demo-proj-123",
                    region="us-central1",
                    **kwargs,
                )
                proc = subprocess.run(
                    [str(VERIFY_START_POINT_BIN), "ws1", "--env", str(env_file)],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(
                    proc.returncode,
                    0,
                    f"Expected non-zero exit code for {kwargs}",
                )
                combined_output = f"{proc.stdout}\n{proc.stderr}"
                self.assertIn("[FAIL]", combined_output)
                self.assertIn(expected_msg, combined_output)


if __name__ == "__main__":
    unittest.main()
