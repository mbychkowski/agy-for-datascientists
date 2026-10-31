"""Tests for Issue #13: Reference fix for Workstream 1 (deduplication, Positivity, and SQL fallback)."""

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
from pipelines.pipeline_clean import (
    CLEAN_STAGING_COLUMNS,
    LocalAnsiSparkDataFrame,
    _FunctionsNamespace,
    deduplicate_and_compute_positivity_rows,
    ensure_java_21_env,
    parse_args,
    transform_clean_dataframe,
)
from tests.helpers import (
    CHECKPOINT_BIN,
    CHECKPOINT_SYMLINK,
    PREFLIGHT_BIN,
    RUN_PIPELINE_CLEAN_BIN,
    RUN_PIPELINE_CLEAN_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
SQL_CLEAN_FILE = WORKTREE_ROOT / "sql" / "staging_hospital_flu_clean.sql"
SQL_EQUIV_FILE = WORKTREE_ROOT / "sql" / "verify_clean_equivalence.sql"
CHECKPOINT_MANIFEST_FILE = (
    WORKTREE_ROOT / "checkpoints" / "manifest.d" / "ws1_staging_clean.json"
)
RECORDED_RUNTIMES_DOC = WORKTREE_ROOT / "docs" / "recorded_runtimes.json"
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
    commands: list[str] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(("bq ", "gcloud ", "agy ", "java ")) or not commands:
            commands.append(line)
        else:
            commands[-1] = f"{commands[-1]}\n{line}"
    return commands


def _execute_sql_fallback_in_python(
    feeds: list[dict[str, Any]],
    hospitals: list[dict[str, Any]],
) -> list[dict[str, object]]:
    """Evaluate the SQL fallback query semantics (`QUALIFY ROW_NUMBER() ... = 1` + `SAFE_DIVIDE`)."""
    hosp_by_id = {str(h["hospital_id"]): h for h in hospitals}
    partitions: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in feeds:
        key = (str(row["hospital_id"]), str(row["feed_date"]))
        partitions.setdefault(key, []).append(row)

    results: list[dict[str, object]] = []
    for key in sorted(partitions.keys()):
        candidates = partitions[key]
        # QUALIFY ROW_NUMBER() OVER (PARTITION BY hospital_id, feed_date ORDER BY ingested_at DESC, batch_id DESC) = 1
        winner = max(
            candidates,
            key=lambda r: (str(r["ingested_at"]), str(r["batch_id"])),
        )
        hosp = hosp_by_id.get(str(winner["hospital_id"]))
        if hosp is None:
            continue
        tot = int(winner["total_flu_tests"])
        pos = int(winner["positive_flu_tests"])
        positivity = None if tot == 0 else float(pos) / float(tot)
        results.append(
            {
                "hospital_id": str(winner["hospital_id"]),
                "hospital_name": str(hosp["hospital_name"]),
                "region": str(hosp["region"]),
                "state": str(hosp["state"]),
                "urban_rural": str(hosp["urban_rural"]),
                "bed_count": int(hosp["bed_count"]),
                "feed_date": str(winner["feed_date"]),
                "total_flu_tests": tot,
                "positive_flu_tests": pos,
                "positivity": positivity,
                "batch_id": str(winner["batch_id"]),
                "ingested_at": str(winner["ingested_at"]),
            }
        )
    return results


def _canonical_row_tuple(row: dict[str, object]) -> tuple[object, ...]:
    pos = row["positivity"]
    rounded_pos = None if pos is None else round(float(pos), 6)  # type: ignore[arg-type]
    return (
        row["hospital_id"],
        row["hospital_name"],
        row["region"],
        row["state"],
        row["urban_rural"],
        row["bed_count"],
        row["feed_date"],
        row["total_flu_tests"],
        row["positive_flu_tests"],
        rounded_pos,
        row["batch_id"],
        row["ingested_at"],
    )


class TestWorkstream1ReferenceFix(unittest.TestCase):
    def test_dedup_and_positivity_tiny_fixture_with_zero_test_day_and_java_21_pin(
        self,
    ) -> None:
        """Local test against a tiny fixture with duplicates and a zero-test day pins Java 21, removes duplicates, and computes null-safe Positivity."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, env, _ = setup_preflight_test_env(tmpdir, java_version_override="21.0.4")
            java_home, version_out = ensure_java_21_env(env)
            self.assertIn("21.0.4", version_out)
            self.assertEqual(env["JAVA_HOME"], java_home)
            self.assertTrue(env["PATH"].startswith(f"{Path(java_home) / 'bin'}:"))

        tiny_hospitals = [
            {
                "hospital_id": "HOSP_NE_003",
                "hospital_name": "Berkshire Community Clinic",
                "region": "Northeast",
                "state": "MA",
                "urban_rural": "Rural",
                "bed_count": 90,
            },
            {
                "hospital_id": "HOSP_NE_001",
                "hospital_name": "Pine Valley Medical Center",
                "region": "Northeast",
                "state": "NY",
                "urban_rural": "Suburban",
                "bed_count": 320,
            },
        ]

        tiny_feeds = [
            # 1. Duplicate (HOSP_NE_003, 2026-10-28) with different ingested_at: latest ingested_at must win
            {
                "hospital_id": "HOSP_NE_003",
                "feed_date": "2026-10-28",
                "total_flu_tests": 25,
                "positive_flu_tests": 5,
                "batch_id": "BATCH-20261028-01",
                "ingested_at": "2026-10-28 04:10:00 UTC",
            },
            {
                "hospital_id": "HOSP_NE_003",
                "feed_date": "2026-10-28",
                "total_flu_tests": 25,
                "positive_flu_tests": 5,
                "batch_id": "BATCH-20261031-BACKFILL-01",
                "ingested_at": "2026-10-31 06:16:00 UTC",
            },
            # 2. Duplicate (HOSP_NE_001, 2026-10-29) with identical ingested_at: greatest batch_id must win
            {
                "hospital_id": "HOSP_NE_001",
                "feed_date": "2026-10-29",
                "total_flu_tests": 50,
                "positive_flu_tests": 10,
                "batch_id": "BATCH-20261029-01",
                "ingested_at": "2026-10-29 04:10:00 UTC",
            },
            {
                "hospital_id": "HOSP_NE_001",
                "feed_date": "2026-10-29",
                "total_flu_tests": 50,
                "positive_flu_tests": 12,
                "batch_id": "BATCH-20261029-02",
                "ingested_at": "2026-10-29 04:10:00 UTC",
            },
            # 3. Zero-test day (total_flu_tests = 0): Positivity must be None without divide-by-zero error
            {
                "hospital_id": "HOSP_NE_003",
                "feed_date": "2026-07-15",
                "total_flu_tests": 0,
                "positive_flu_tests": 0,
                "batch_id": "BATCH-20260715-01",
                "ingested_at": "2026-07-15 04:10:00 UTC",
            },
        ]

        # Confirm that unguarded division on the zero-test fixture raises Spark 4 ANSI DIVIDE_BY_ZERO
        F = _FunctionsNamespace
        with self.assertRaises(ZeroDivisionError):
            LocalAnsiSparkDataFrame(tiny_feeds).withColumn(
                "unguarded_positivity",
                F.col("positive_flu_tests").cast("double")
                / F.col("total_flu_tests").cast("double"),
            )

        cleaned = deduplicate_and_compute_positivity_rows(tiny_feeds, tiny_hospitals)
        self.assertEqual(len(cleaned), 3)

        by_key = {(r["hospital_id"], r["feed_date"]): r for r in cleaned}
        self.assertEqual(len(by_key), 3)

        # Latest ingested_at won for (HOSP_NE_003, 2026-10-28)
        row_ne3_oct28 = by_key[("HOSP_NE_003", "2026-10-28")]
        self.assertEqual(tuple(row_ne3_oct28.keys()), CLEAN_STAGING_COLUMNS)
        self.assertEqual(row_ne3_oct28["batch_id"], "BATCH-20261031-BACKFILL-01")
        self.assertEqual(row_ne3_oct28["ingested_at"], "2026-10-31 06:16:00 UTC")
        self.assertAlmostEqual(float(row_ne3_oct28["positivity"]), 0.20, places=6)  # type: ignore[arg-type]

        # Secondary tie-break on batch_id DESC won for (HOSP_NE_001, 2026-10-29)
        row_ne1_oct29 = by_key[("HOSP_NE_001", "2026-10-29")]
        self.assertEqual(row_ne1_oct29["batch_id"], "BATCH-20261029-02")
        self.assertEqual(row_ne1_oct29["positive_flu_tests"], 12)
        self.assertAlmostEqual(float(row_ne1_oct29["positivity"]), 0.24, places=6)  # type: ignore[arg-type]

        # Zero-test day produced None (NULL) Positivity
        row_zero = by_key[("HOSP_NE_003", "2026-07-15")]
        self.assertEqual(row_zero["total_flu_tests"], 0)
        self.assertEqual(row_zero["positive_flu_tests"], 0)
        self.assertIsNone(row_zero["positivity"])

        # Verify on full mock_dataset that all 20 duplicates are removed and Northeast Spike drops from +35% to +20%
        hospitals = _read_csv(MOCK_DATASET_DIR / "raw" / "hospital_reference.csv")
        feeds = _read_csv(MOCK_DATASET_DIR / "raw" / "hospital_flu_feeds" / "feeds.csv")
        clean_mock = deduplicate_and_compute_positivity_rows(feeds, hospitals)
        self.assertEqual(len(feeds) - len(clean_mock), 20)

        key_counts = Counter((r["hospital_id"], r["feed_date"]) for r in clean_mock)
        self.assertEqual(max(key_counts.values()), 1)

        zero_test_clean = [r for r in clean_mock if r["total_flu_tests"] == 0]
        self.assertGreater(len(zero_test_clean), 0)
        for z_row in zero_test_clean:
            self.assertIsNone(z_row["positivity"])

        w42_ne_pos = 0
        w43_ne_pos = 0
        for row in clean_mock:
            if row["region"] != "Northeast":
                continue
            fdate = date.fromisoformat(str(row["feed_date"]))
            pos = int(row["positive_flu_tests"])  # type: ignore[arg-type]
            if BASELINE_WEEK_START <= fdate <= BASELINE_WEEK_END:
                w42_ne_pos += pos
            elif SPIKE_WEEK_START <= fdate <= CUTOFF_DATE:
                w43_ne_pos += pos

        clean_growth_pct = ((w43_ne_pos - w42_ne_pos) / w42_ne_pos) * 100.0
        self.assertAlmostEqual(clean_growth_pct, 20.0, places=2)

        parsed = parse_args(
            ["--project-id", "demo-proj-123", "--staging-bucket", "demo-staging-bucket"]
        )
        self.assertEqual(parsed.output_table, "hospital_flu_clean")

    def test_preflight_checks_java_21_and_fails_on_java_25_or_missing(self) -> None:
        """bin/preflight must verify Java 21 is available and fail when Java 25 or no Java is installed."""
        for kwargs in (
            {"java_version_override": "25.0.1"},
            {"java_missing": True},
        ):
            with self.subTest(**kwargs), tempfile.TemporaryDirectory() as tmpdir:
                env_file, env, _ = setup_preflight_test_env(tmpdir, **kwargs)
                proc = subprocess.run(
                    [str(PREFLIGHT_BIN), "--env", str(env_file)],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(
                    "[FAIL] Java 21 runtime is available for local Spark 4 testing",
                    proc.stdout,
                )
                self.assertIn("Spark 4 does not support Java 25", proc.stdout)
                self.assertIn("openjdk@21", proc.stdout)

    def test_run_pipeline_clean_dataproc_sync_and_async_modes(self) -> None:
        """bin/run-pipeline-clean must submit pipelines/pipeline_clean.py on Dataproc 3.0 as presenter, label staging.hospital_flu_clean, record runtime, and support --async."""
        for path in (
            RUN_PIPELINE_CLEAN_BIN,
            RUN_PIPELINE_CLEAN_SYMLINK,
            RECORDED_RUNTIMES_DOC,
        ):
            self.assertTrue(path.exists(), f"{path} must exist")
        self.assertTrue(os.access(RUN_PIPELINE_CLEAN_BIN, os.X_OK))
        self.assertTrue(os.access(RUN_PIPELINE_CLEAN_SYMLINK, os.X_OK))

        doc_runtimes = json.loads(RECORDED_RUNTIMES_DOC.read_text(encoding="utf-8"))
        self.assertIn("ws1_pipeline_clean_dataproc_runtime_3_0", doc_runtimes)
        clean_meta = doc_runtimes["ws1_pipeline_clean_dataproc_runtime_3_0"]
        self.assertEqual(clean_meta["dataproc_serverless_runtime"], "3.0")
        self.assertEqual(clean_meta["target_table"], "staging.hospital_flu_clean")
        self.assertGreater(int(clean_meta["baseline_observed_seconds"]), 0)

        # 1. Synchronous submission
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                subnet="projects/demo-proj-123/regions/us-central1/subnetworks/custom-sub",
            )
            proc = subprocess.run(
                [str(RUN_PIPELINE_CLEAN_SYMLINK), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"run-pipeline-clean sync failed:\n{proc.stdout}\n{proc.stderr}",
            )
            self.assertIn("[PASS]", proc.stdout)

            calls = _parse_logged_commands(log_file)
            dp_calls = [
                c for c in calls if "gcloud dataproc batches submit pyspark" in c
            ]
            self.assertEqual(len(dp_calls), 1)
            dp_call = dp_calls[0]
            self.assertIn("pipelines/pipeline_clean.py", dp_call)
            self.assertIn("--version=3.0", dp_call)
            self.assertIn("--batch=ws1-pipeline-clean-test", dp_call)
            self.assertIn("--output-table hospital_flu_clean", dp_call)
            self.assertNotIn("--async", dp_call)
            self.assertNotIn("--service-account", dp_call)
            self.assertNotIn("ShieldedVm", dp_call)

            label_calls = [
                c
                for c in calls
                if "update --set_label demo:true" in c
                and "demo-proj-123:staging.hospital_flu_clean" in c
            ]
            self.assertEqual(len(label_calls), 1)

            recorded = json.loads(
                Path(env["RECORDED_RUNTIMES_FILE"]).read_text(encoding="utf-8")
            )
            self.assertEqual(
                recorded["ws1_pipeline_clean_dataproc_runtime_3_0"]["last_batch_id"],
                "ws1-pipeline-clean-test",
            )

            # Verify every CLI command passes guardrail-hook
            for cmd_line in calls:
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
                self.assertEqual(json.loads(hook_proc.stdout).get("decision"), "allow")

        # 2. Asynchronous submission (--async)
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
            )
            proc = subprocess.run(
                [str(RUN_PIPELINE_CLEAN_BIN), "--env", str(env_file), "--async"],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0)
            self.assertIn("asynchronously", proc.stdout)
            calls = _parse_logged_commands(log_file)
            self.assertEqual(len(calls), 1)
            self.assertIn("--async", calls[0])
            self.assertIn("pipelines/pipeline_clean.py", calls[0])

    def test_sql_fallback_and_equivalence_check_match_pyspark_output(self) -> None:
        """SQL fallback and PySpark pipeline must produce identical tables (empty set difference both ways, matching row counts, unique hospital_id + feed_date), and Clean-Staging Checkpoint must be configured."""
        for path in (SQL_CLEAN_FILE, SQL_EQUIV_FILE, CHECKPOINT_MANIFEST_FILE):
            self.assertTrue(path.exists(), f"Expected file at {path}")

        manifest = json.loads(CHECKPOINT_MANIFEST_FILE.read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "ws1_staging_clean")
        self.assertEqual(manifest["workstream"], "ws1")
        self.assertEqual(manifest["target_table"], "staging.hospital_flu_clean")
        self.assertEqual(manifest["sql_file"], "sql/staging_hospital_flu_clean.sql")

        sql_clean_text = SQL_CLEAN_FILE.read_text(encoding="utf-8")
        self.assertIn("QUALIFY ROW_NUMBER() OVER", sql_clean_text)
        self.assertIn("PARTITION BY hospital_id, feed_date", sql_clean_text)
        self.assertIn("ORDER BY ingested_at DESC, batch_id DESC", sql_clean_text)
        self.assertIn("SAFE_DIVIDE", sql_clean_text)

        sql_equiv_text = SQL_EQUIV_FILE.read_text(encoding="utf-8")
        self.assertIn("EXCEPT DISTINCT", sql_equiv_text)
        self.assertIn("diff_a_minus_b_count", sql_equiv_text)
        self.assertIn("diff_b_minus_a_count", sql_equiv_text)
        self.assertIn("duplicate_key_count", sql_equiv_text)

        # Prove equivalence on fixtures/mock_dataset between PySpark transform and SQL fallback
        hospitals = _read_csv(MOCK_DATASET_DIR / "raw" / "hospital_reference.csv")
        feeds = _read_csv(MOCK_DATASET_DIR / "raw" / "hospital_flu_feeds" / "feeds.csv")

        pyspark_rows = transform_clean_dataframe(
            LocalAnsiSparkDataFrame(feeds),
            LocalAnsiSparkDataFrame(hospitals),
        ).rows
        sql_rows = _execute_sql_fallback_in_python(feeds, hospitals)

        self.assertEqual(len(pyspark_rows), len(sql_rows))
        self.assertEqual(len(pyspark_rows), 15260)

        set_a = {_canonical_row_tuple(r) for r in pyspark_rows}
        set_b = {_canonical_row_tuple(r) for r in sql_rows}
        self.assertEqual(
            len(set_a - set_b), 0, "PySpark minus SQL set difference must be empty"
        )
        self.assertEqual(
            len(set_b - set_a), 0, "SQL minus PySpark set difference must be empty"
        )

        keys_a = [(r["hospital_id"], r["feed_date"]) for r in pyspark_rows]
        keys_b = [(r["hospital_id"], r["feed_date"]) for r in sql_rows]
        self.assertEqual(len(keys_a), len(set(keys_a)))
        self.assertEqual(len(keys_b), len(set(keys_b)))

        # Test CLI --sql-fallback --verify-equivalence
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
            )
            proc = subprocess.run(
                [
                    str(RUN_PIPELINE_CLEAN_BIN),
                    "--env",
                    str(env_file),
                    "--sql-fallback",
                    "--verify-equivalence",
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
                f"SQL fallback + equivalence check failed:\n{proc.stdout}\n{proc.stderr}",
            )
            self.assertIn("[PASS] Equivalence check passed", proc.stdout)
            self.assertIn("[PASS] SQL fallback materialised", proc.stdout)

            calls = _parse_logged_commands(log_file)
            self.assertTrue(
                any(
                    "--destination_table=demo-proj-123:staging.hospital_flu_clean" in c
                    and "--replace=true" in c
                    for c in calls
                )
            )
            self.assertTrue(
                any(
                    "update --set_label demo:true" in c
                    and "demo-proj-123:staging.hospital_flu_clean" in c
                    for c in calls
                )
            )
            self.assertTrue(any("diff_a_minus_b_count" in c for c in calls))

        # Test CLI --verify-equivalence failure cases
        failure_cases: list[tuple[dict[str, int], str]] = [
            (
                {"clean_equiv_row_count_a": 15260, "clean_equiv_row_count_b": 15280},
                "Row count mismatch",
            ),
            (
                {"clean_equiv_diff_ab": 3},
                "Set difference is non-empty",
            ),
            (
                {"clean_equiv_diff_ba": 2},
                "Set difference is non-empty",
            ),
            (
                {"clean_equiv_dup_keys": 5},
                "Duplicate (hospital_id, feed_date) keys detected",
            ),
        ]
        for kwargs, expected_err in failure_cases:
            with self.subTest(**kwargs), tempfile.TemporaryDirectory() as tmpdir:
                env_file, env, _ = setup_preflight_test_env(tmpdir, **kwargs)
                proc = subprocess.run(
                    [
                        str(RUN_PIPELINE_CLEAN_BIN),
                        "--env",
                        str(env_file),
                        "--verify-equivalence",
                    ],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(expected_err, f"{proc.stdout}\n{proc.stderr}")

    def test_clean_staging_checkpoint_list_build_and_swap(self) -> None:
        """bin/checkpoint must list, build (from sql/staging_hospital_flu_clean.sql), and swap ws1_staging_clean into staging.hospital_flu_clean with demo:true."""
        list_proc = subprocess.run(
            [str(CHECKPOINT_SYMLINK), "--list"],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        self.assertIn("ws1_staging_clean", list_proc.stdout)
        self.assertIn(
            "checkpoint.ws1_staging_hospital_flu_clean -> staging.hospital_flu_clean",
            list_proc.stdout,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables={
                    "raw": {
                        "hospital_reference": {"demo": "true"},
                        "hospital_flu_feeds": {"demo": "true"},
                    },
                    "ops": {"pipeline_run_log": {"demo": "true"}},
                    "staging": {"hospital_flu": {"demo": "true"}},
                    "features": {},
                    "ml": {},
                    "checkpoint": {
                        "ws1_staging_hospital_flu": {"demo": "true"},
                    },
                },
            )

            # 1. Build ws1_staging_clean into checkpoint.ws1_staging_hospital_flu_clean from sql/staging_hospital_flu_clean.sql
            build_proc = subprocess.run(
                [
                    str(CHECKPOINT_BIN),
                    "--build",
                    "ws1_staging_clean",
                    "--env",
                    str(env_file),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                build_proc.returncode,
                0,
                f"checkpoint --build ws1_staging_clean failed:\n{build_proc.stdout}\n{build_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Built Checkpoint 'ws1_staging_clean': demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean",
                build_proc.stdout,
            )

            # 2. Swap ws1_staging_clean from checkpoint.ws1_staging_hospital_flu_clean -> staging.hospital_flu_clean
            swap_proc = subprocess.run(
                [
                    str(CHECKPOINT_SYMLINK),
                    "ws1_staging_clean",
                    "--env",
                    str(env_file),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                swap_proc.returncode,
                0,
                f"checkpoint ws1_staging_clean failed:\n{swap_proc.stdout}\n{swap_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Swapped Checkpoint 'ws1_staging_clean': demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean -> demo-proj-123:staging.hospital_flu_clean",
                swap_proc.stdout,
            )

            final_state = json.loads(
                (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                final_state["checkpoint"].get("ws1_staging_hospital_flu_clean"),
                {"demo": "true"},
            )
            self.assertEqual(
                final_state["staging"].get("hospital_flu_clean"),
                {"demo": "true"},
            )

            calls = _parse_logged_commands(log_file)
            self.assertTrue(
                any(
                    "--destination_table=demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean"
                    in c
                    and "QUALIFY ROW_NUMBER()" in c
                    for c in calls
                )
            )
            self.assertTrue(
                any(
                    "cp -f" in c
                    and "demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean" in c
                    and "demo-proj-123:staging.hospital_flu_clean" in c
                    for c in calls
                )
            )

    def test_none_of_issue_013_files_exist_on_workstream_1_start_branch(self) -> None:
        """None of the Issue #13 reference fix files may exist on the workstream-1-start branch."""
        branch_ref = None
        for candidate in ("workstream-1-start", "origin/workstream-1-start"):
            chk = subprocess.run(
                ["git", "rev-parse", "--verify", candidate],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if chk.returncode == 0:
                branch_ref = candidate
                break

        if branch_ref is None:
            subprocess.run(
                [
                    "git",
                    "fetch",
                    "--depth=1",
                    "origin",
                    "workstream-1-start:refs/remotes/origin/workstream-1-start",
                ],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            chk = subprocess.run(
                ["git", "rev-parse", "--verify", "origin/workstream-1-start"],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if chk.returncode == 0:
                branch_ref = "origin/workstream-1-start"

        self.assertIsNotNone(
            branch_ref,
            "Expected workstream-1-start (or origin/workstream-1-start) branch to exist",
        )
        ls_proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", str(branch_ref)],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        branch_files = set(ls_proc.stdout.splitlines())

        issue_013_files = (
            "pipelines/pipeline_clean.py",
            "bin/run-pipeline-clean",
            "run-pipeline-clean",
            "sql/staging_hospital_flu_clean.sql",
            "sql/verify_clean_equivalence.sql",
            "checkpoints/manifest.d/ws1_staging_clean.json",
            "docs/recorded_runtimes.json",
            "tests/test_ws1_reference_fix.py",
        )
        for rel_path in issue_013_files:
            self.assertNotIn(
                rel_path,
                branch_files,
                f"{rel_path} must NOT exist on {branch_ref}",
            )


if __name__ == "__main__":
    unittest.main()
