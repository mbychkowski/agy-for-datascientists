"""Tests for Issue #15: Cohorts: seasonal features and K-means."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.mock_dataset_generator import generate_dataset
from lib.ws2_cohorts import (
    OUTBREAK_HOSPITAL_IDS,
    SEASONAL_FEATURE_COLUMNS,
    assign_kmeans_cohorts,
    compute_hospital_seasonal_features,
    load_clean_staging_rows,
    summarize_cohort_separation,
)
from tests.helpers import (
    CHECKPOINT_BIN,
    CHECKPOINT_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
MANIFEST_DIR = WORKTREE_ROOT / "checkpoints" / "manifest.d"
FEATURES_SQL_PATH = WORKTREE_ROOT / "sql" / "ws2_seasonal_features.sql"
KMEANS_SQL_PATH = WORKTREE_ROOT / "sql" / "ws2_kmeans_cohorts.sql"
RUN_WS2_COHORTS_BIN = WORKTREE_ROOT / "bin" / "run-ws2-cohorts"
RUN_WS2_COHORTS_SYMLINK = WORKTREE_ROOT / "run-ws2-cohorts"
PRIMER_PATH = WORKTREE_ROOT / "docs" / "data-science-primer.md"


def _parse_logged_commands(log_file: Path) -> list[str]:
    """Group multi-line logged CLI invocations into full commands."""
    if not log_file.exists():
        return []
    commands: list[str] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(("bq ", "gcloud ", "agy ")) or not commands:
            commands.append(line)
        else:
            commands[-1] = f"{commands[-1]}\n{line}"
    return commands


class TestWs2SeasonalFeaturesAndKmeans(unittest.TestCase):
    def test_sql_files_exist_and_define_seasonal_features_and_kmeans_model(
        self,
    ) -> None:
        """sql/ws2_seasonal_features.sql and sql/ws2_kmeans_cohorts.sql must exist and define the expected SQL structures."""
        self.assertTrue(
            FEATURES_SQL_PATH.is_file(), "ws2_seasonal_features.sql missing"
        )
        self.assertTrue(KMEANS_SQL_PATH.is_file(), "ws2_kmeans_cohorts.sql missing")

        features_sql = FEATURES_SQL_PATH.read_text(encoding="utf-8")
        self.assertIn("`staging.hospital_flu_clean`", features_sql)
        for col in (
            "hospital_id",
            "hospital_name",
            "region",
            "state",
            "urban_rural",
            "bed_count",
            *SEASONAL_FEATURE_COLUMNS,
        ):
            self.assertIn(col, features_sql, f"Expected column {col} in features SQL")

        kmeans_sql = KMEANS_SQL_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "CREATE OR REPLACE MODEL `${PROJECT_ID}.ml.hospital_cohort_kmeans`",
            kmeans_sql,
        )
        self.assertIn("model_type='KMEANS'", kmeans_sql)
        self.assertIn("num_clusters=4", kmeans_sql)
        self.assertIn("standardize_features=TRUE", kmeans_sql)
        self.assertIn("kmeans_init_method='KMEANS++'", kmeans_sql)
        self.assertIn(
            "FROM `${PROJECT_ID}.features.hospital_seasonal_features`",
            kmeans_sql,
        )
        self.assertIn(
            "CREATE OR REPLACE TABLE `${PROJECT_ID}.features.hospital_cohorts`",
            kmeans_sql,
        )
        self.assertIn(
            "CONCAT('COHORT_', CAST(CENTROID_ID AS STRING)) AS cohort_id",
            kmeans_sql,
        )
        self.assertIn("ML.PREDICT", kmeans_sql)

    def test_seasonal_features_and_kmeans_isolate_outbreak_hospitals_on_mock_dataset(
        self,
    ) -> None:
        """compute_hospital_seasonal_features and assign_kmeans_cohorts must populate all 4 features and isolate Outbreak hospitals."""
        clean_rows = load_clean_staging_rows(MOCK_DATASET_DIR)
        feature_rows = compute_hospital_seasonal_features(clean_rows)
        self.assertEqual(len(feature_rows), 20)

        for row in feature_rows:
            for col in SEASONAL_FEATURE_COLUMNS:
                self.assertIn(col, row)
                self.assertIsInstance(row[col], float)
                self.assertGreater(row[col], 0.0)

        cohort_rows = assign_kmeans_cohorts(feature_rows, k=4, seed=42)
        self.assertEqual(len(cohort_rows), 20)

        # Determinism check across repeated runs
        cohort_rows_repeat = assign_kmeans_cohorts(
            compute_hospital_seasonal_features(dataset_dir=MOCK_DATASET_DIR),
            k=4,
            seed=42,
        )
        self.assertEqual(cohort_rows, cohort_rows_repeat)

        summary = summarize_cohort_separation(cohort_rows)
        self.assertEqual(summary["num_cohorts"], 4)
        self.assertEqual(
            set(summary["cohort_counts"].keys()),
            {"COHORT_1", "COHORT_2", "COHORT_3", "COHORT_4"},
        )
        self.assertTrue(summary["outbreak_isolated_in_own_cohort"])
        self.assertEqual(summary["outbreak_cohort_id"], "COHORT_4")
        self.assertEqual(
            summary["outbreak_hospital_ids"],
            list(OUTBREAK_HOSPITAL_IDS),
        )
        self.assertEqual(
            summary["top_outlier_hospital_ids"],
            list(OUTBREAK_HOSPITAL_IDS),
        )
        self.assertGreater(summary["outbreak_mean_seasonal_trend"], 2.5)
        self.assertLess(summary["non_outbreak_max_seasonal_trend"], 1.10)

        for row in cohort_rows:
            if row["hospital_id"] in OUTBREAK_HOSPITAL_IDS:
                self.assertEqual(row["cohort_id"], "COHORT_4")
                self.assertTrue(row["is_outbreak_outlier"])
                self.assertAlmostEqual(row["seasonal_trend"], 2.7143, places=3)
            else:
                self.assertNotEqual(row["cohort_id"], "COHORT_4")
                self.assertFalse(row["is_outbreak_outlier"])
                self.assertLess(row["seasonal_trend"], 1.10)

    def test_kmeans_isolates_outbreak_hospitals_at_55_and_90_hospital_scales(
        self,
    ) -> None:
        """Outbreak hospitals (HOSP_NE_001, HOSP_NE_004, HOSP_NE_006) must form their own 3-hospital Cohort at 55- and 90-hospital scales."""
        with tempfile.TemporaryDirectory() as tmpdir:
            full_dir = Path(tmpdir) / "full_dataset"
            wh_dir = Path(tmpdir) / "withheld"
            generate_dataset(
                seed=42, scale="full", output_dir=full_dir, withheld_dir=wh_dir
            )
            full_features = compute_hospital_seasonal_features(full_dir)
            self.assertEqual(len(full_features), 90)

            # Test both 55-hospital subset (25 NE + 15 MW + 15 SO) and full 90 hospitals
            subset_55 = [
                r
                for r in full_features
                if r["region"] == "Northeast"
                or (
                    r["region"] in ("Midwest", "South")
                    and int(str(r["hospital_id"]).split("_")[-1]) <= 15
                )
            ]
            self.assertEqual(len(subset_55), 55)

            for label, rows in (
                ("55_hospitals", subset_55),
                ("90_hospitals", full_features),
            ):
                with self.subTest(scale=label):
                    cohorts = assign_kmeans_cohorts(rows, k=4, seed=42)
                    summary = summarize_cohort_separation(cohorts)
                    self.assertEqual(summary["num_cohorts"], 4)
                    self.assertTrue(summary["outbreak_isolated_in_own_cohort"])
                    self.assertEqual(summary["outbreak_cohort_id"], "COHORT_4")
                    self.assertEqual(
                        summary["outbreak_hospital_ids"],
                        list(OUTBREAK_HOSPITAL_IDS),
                    )
                    self.assertEqual(
                        summary["top_outlier_hospital_ids"],
                        list(OUTBREAK_HOSPITAL_IDS),
                    )

    def test_run_ws2_cohorts_cli_executes_sql_and_labels_tables_demo_true(
        self,
    ) -> None:
        """bin/run-ws2-cohorts must materialise features.hospital_seasonal_features and features.hospital_cohorts with demo:true."""
        for path in (RUN_WS2_COHORTS_BIN, RUN_WS2_COHORTS_SYMLINK):
            self.assertTrue(path.exists(), f"{path} must exist")
            self.assertTrue(os.access(path, os.X_OK), f"{path} must be executable")

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
                    "staging": {
                        "hospital_flu": {"demo": "true"},
                        "hospital_flu_clean": {"demo": "true"},
                    },
                    "features": {},
                    "ml": {},
                    "checkpoint": {},
                },
            )

            proc = subprocess.run(
                [str(RUN_WS2_COHORTS_SYMLINK), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"run-ws2-cohorts failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )
            self.assertIn(
                "[PASS] Workstream 2 seasonal features and K-means hospital Cohorts materialised and labelled demo:true.",
                proc.stdout,
            )

            calls = _parse_logged_commands(log_file)
            self.assertTrue(
                any(
                    "--destination_table=demo-proj-123:features.hospital_seasonal_features"
                    in c
                    and "--replace=true" in c
                    for c in calls
                ),
                "Expected bq query --destination_table=demo-proj-123:features.hospital_seasonal_features",
            )
            self.assertTrue(
                any(
                    "update --set_label demo:true" in c
                    and "demo-proj-123:features.hospital_seasonal_features" in c
                    for c in calls
                ),
                "Expected demo:true label on features.hospital_seasonal_features",
            )
            self.assertTrue(
                any(
                    "CREATE OR REPLACE MODEL `demo-proj-123.ml.hospital_cohort_kmeans`"
                    in c
                    and "CREATE OR REPLACE TABLE `demo-proj-123.features.hospital_cohorts`"
                    in c
                    for c in calls
                ),
                "Expected K-means model training and features.hospital_cohorts creation query",
            )
            self.assertTrue(
                any(
                    "update --set_label demo:true" in c
                    and "demo-proj-123:features.hospital_cohorts" in c
                    for c in calls
                ),
                "Expected demo:true label on features.hospital_cohorts",
            )

            final_state = json.loads(
                (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                final_state["features"],
                {
                    "hospital_seasonal_features": {"demo": "true"},
                    "hospital_cohorts": {"demo": "true"},
                },
            )

        # Verify failure propagation when K-means training fails or demo.env has placeholders
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                kmeans_fails=True,
            )
            fail_proc = subprocess.run(
                [str(RUN_WS2_COHORTS_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(fail_proc.returncode, 0)
            self.assertIn("[FAIL]", fail_proc.stderr)

        placeholder_proc = subprocess.run(
            [
                str(RUN_WS2_COHORTS_BIN),
                "--env",
                str(WORKTREE_ROOT / "demo.env.example"),
            ],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(placeholder_proc.returncode, 0)
        self.assertIn("[FAIL]", placeholder_proc.stderr)

    def test_ws2_checkpoints_list_build_and_swap(self) -> None:
        """ws2_seasonal_features and ws2_hospital_cohorts Checkpoints must be registered, buildable, and swappable."""
        expected_manifests = {
            "ws2_seasonal_features": {
                "workstream": "ws2",
                "source_table": "checkpoint.ws2_seasonal_features",
                "target_table": "features.hospital_seasonal_features",
                "sql_file": "sql/ws2_seasonal_features.sql",
            },
            "ws2_hospital_cohorts": {
                "workstream": "ws2",
                "source_table": "checkpoint.ws2_hospital_cohorts",
                "target_table": "features.hospital_cohorts",
                "sql_file": "sql/ws2_kmeans_cohorts.sql",
            },
        }
        for cid, expected in expected_manifests.items():
            manifest_path = MANIFEST_DIR / f"{cid}.json"
            self.assertTrue(manifest_path.is_file(), f"Missing {manifest_path}")
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(data["id"], cid)
            for key, val in expected.items():
                self.assertEqual(data[key], val)

        list_proc = subprocess.run(
            [str(CHECKPOINT_SYMLINK), "--list"],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        self.assertIn("ws2_seasonal_features", list_proc.stdout)
        self.assertIn(
            "checkpoint.ws2_seasonal_features -> features.hospital_seasonal_features",
            list_proc.stdout,
        )
        self.assertIn("ws2_hospital_cohorts", list_proc.stdout)
        self.assertIn(
            "checkpoint.ws2_hospital_cohorts -> features.hospital_cohorts",
            list_proc.stdout,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables={
                    "raw": {},
                    "ops": {},
                    "staging": {"hospital_flu_clean": {"demo": "true"}},
                    "features": {},
                    "ml": {},
                    "checkpoint": {},
                },
            )

            for cid, expected in expected_manifests.items():
                build_proc = subprocess.run(
                    [str(CHECKPOINT_BIN), "--build", cid, "--env", str(env_file)],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    build_proc.returncode,
                    0,
                    f"checkpoint --build {cid} failed:\n{build_proc.stdout}\n{build_proc.stderr}",
                )
                self.assertIn(
                    f"[PASS] Built Checkpoint '{cid}': demo-proj-123:{expected['source_table']}",
                    build_proc.stdout,
                )

                swap_proc = subprocess.run(
                    [str(CHECKPOINT_SYMLINK), cid, "--env", str(env_file)],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    swap_proc.returncode,
                    0,
                    f"checkpoint swap {cid} failed:\n{swap_proc.stdout}\n{swap_proc.stderr}",
                )
                self.assertIn(
                    f"[PASS] Swapped Checkpoint '{cid}': demo-proj-123:{expected['source_table']} -> demo-proj-123:{expected['target_table']}",
                    swap_proc.stdout,
                )

            final_state = json.loads(
                (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                final_state["checkpoint"],
                {
                    "ws2_seasonal_features": {"demo": "true"},
                    "ws2_hospital_cohorts": {"demo": "true"},
                },
            )
            self.assertEqual(
                final_state["features"],
                {
                    "hospital_seasonal_features": {"demo": "true"},
                    "hospital_cohorts": {"demo": "true"},
                },
            )

    def test_primer_documents_four_seasonal_features_and_outbreak_cohort_and_passes_glossary(
        self,
    ) -> None:
        """docs/data-science-primer.md must explain the 4 seasonal features and Outbreak Cohort separation and pass check-glossary.js."""
        primer_text = PRIMER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "#### Why These Four Seasonal Features (Peak Arrival Week, Peak Volume, Curve Width, and Trend)",
            primer_text,
        )
        for col in SEASONAL_FEATURE_COLUMNS:
            self.assertIn(col, primer_text)
        for hid in OUTBREAK_HOSPITAL_IDS:
            self.assertIn(hid, primer_text)
        self.assertIn("COHORT_4", primer_text)

        glossary_proc = subprocess.run(
            [
                "node",
                "bin/check-glossary.js",
                "docs/data-science-primer.md",
                "sql/ws2_seasonal_features.sql",
                "sql/ws2_kmeans_cohorts.sql",
                "lib/ws2_cohorts.py",
                "bin/run-ws2-cohorts",
                "checkpoints/manifest.d/ws2_seasonal_features.json",
                "checkpoints/manifest.d/ws2_hospital_cohorts.json",
                "tests/test_ws2_cohorts.py",
            ],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            glossary_proc.returncode,
            0,
            f"Glossary check failed:\n{glossary_proc.stdout}\n{glossary_proc.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
