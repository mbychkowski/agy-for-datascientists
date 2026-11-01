"""Tests for Issue #21: Switch to the refined dataset and re-verify."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from datetime import date
from pathlib import Path

from lib.mock_dataset_generator import (
    BACKFILL_BATCH_ID,
    BACKFILL_END_DATE,
    BACKFILL_INGESTED_AT,
    BACKFILL_RUN_ID,
    BACKFILL_START_DATE,
    CUTOFF_DATE,
    FULL_START_DATE,
    REVEAL_END_DATE,
    REVEAL_START_DATE,
    generate_dataset,
)
from lib.reveal_chart import (
    REVEAL_HORIZON_WEEKS,
    build_reveal_comparison_series,
    evaluate_reveal_overshoot,
    load_reveal_feeds,
)
from lib.ws1_triage import (
    ATTRIBUTION_TOLERANCE_POINTS,
    build_eda_heatmap,
    compare_attribution_to_answer_key,
    load_dataset_tables,
    reconcile_attribution,
    run_stats_reviewer_checks,
)
from lib.ws2_cohorts import (
    OUTBREAK_HOSPITAL_IDS,
    assign_kmeans_cohorts,
    compute_hospital_seasonal_features,
    load_clean_staging_rows,
    summarize_cohort_separation,
)
from lib.ws2_forecasting import (
    COHORT_IDS,
    MODEL_FAMILIES,
    build_forecast_leaderboard,
    forecast_post_cutoff_six_weeks,
    run_backtest_trials,
)
from pipelines.pipeline_clean import deduplicate_and_compute_positivity_rows
from pipelines.pipeline_v1 import build_v1_rows
from tests.helpers import (
    RESET_BIN,
    SETUP_BIN,
    VERIFY_START_POINT_BIN,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

LOAD_RAW_OPS_BIN = WORKTREE_ROOT / "bin" / "load-raw-ops"
LOAD_REVEAL_BIN = WORKTREE_ROOT / "bin" / "load-reveal"
VERIFY_MAIN_BIN = WORKTREE_ROOT / "bin" / "verify-main-end-state"
MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
MOCK_WITHHELD_DIR = WORKTREE_ROOT / "fixtures" / "mock_withheld"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_logged_commands(log_file: Path) -> list[str]:
    if not log_file.exists():
        return []
    commands: list[str] = []
    for line in log_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(("bq ", "gcloud ", "agy ", "java ")) or not commands:
            commands.append(line)
        else:
            commands[-1] = f"{commands[-1]}\n{line}"
    return commands


def _main_end_state_tables() -> dict[str, dict[str, dict[str, str]]]:
    return {
        "raw": {
            "hospital_reference": {"demo": "true"},
            "hospital_flu_feeds": {"demo": "true"},
        },
        "ops": {
            "pipeline_run_log": {"demo": "true"},
        },
        "staging": {
            "hospital_flu": {"demo": "true"},
            "hospital_flu_clean": {"demo": "true"},
        },
        "features": {
            "hospital_seasonal_features": {"demo": "true"},
            "hospital_cohorts": {"demo": "true"},
        },
        "ml": {
            "experiment_trials": {"demo": "true"},
            "forecast_leaderboard": {"demo": "true"},
        },
        "checkpoint": {
            "ws1_staging_hospital_flu": {"demo": "true"},
            "ws1_staging_hospital_flu_clean": {"demo": "true"},
        },
    }


class TestRefinedDatasetSwitchover(unittest.TestCase):
    """End-to-end verification of the refined full-scale dataset (90 hospitals) and DATASET_LOCATION hand-off."""

    refined_tmp: str
    refined_dataset_dir: Path
    refined_withheld_dir: Path
    summary: dict[str, object]

    @classmethod
    def setUpClass(cls) -> None:
        cls.refined_tmp = tempfile.mkdtemp(prefix="refined_full_dataset_")
        base = Path(cls.refined_tmp)
        cls.refined_dataset_dir = base / "dataset"
        cls.refined_withheld_dir = base / "withheld"
        cls.summary = generate_dataset(
            seed=42,
            scale="full",
            output_dir=cls.refined_dataset_dir,
            withheld_dir=cls.refined_withheld_dir,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.refined_tmp, ignore_errors=True)

    def test_refined_90_hospital_dataset_meets_full_contract_and_storyline(
        self,
    ) -> None:
        """Full-scale dataset (90 hospitals) must satisfy all contract invariants, Attribution, K-means Cohorts, backtest WAPE, and Reveal overshoot."""
        # 1. Contract volume & regional distribution invariants
        self.assertEqual(self.summary["scale"], "full")
        self.assertEqual(self.summary["hospitals"], 90)
        self.assertEqual(self.summary["duplicate_rows"], 40)
        self.assertEqual(self.summary["feed_rows"], 101470)
        self.assertEqual(self.summary["run_log_rows"], 1128)
        self.assertEqual(self.summary["reveal_rows"], 3780)

        hospitals = _read_csv(
            self.refined_dataset_dir / "raw" / "hospital_reference.csv"
        )
        feeds = _read_csv(
            self.refined_dataset_dir / "raw" / "hospital_flu_feeds" / "feeds.csv"
        )
        run_log = _read_csv(self.refined_dataset_dir / "ops" / "pipeline_run_log.csv")
        answer_key = json.loads(
            (self.refined_withheld_dir / "answer_key.json").read_text(encoding="utf-8")
        )
        reveal_rows = load_reveal_feeds(self.refined_withheld_dir)

        self.assertEqual(len(hospitals), 90)
        self.assertEqual(len(feeds), 101470)
        self.assertEqual(len(run_log), 1128)
        self.assertEqual(len(reveal_rows), 3780)

        region_counts = Counter(h["region"] for h in hospitals)
        self.assertEqual(
            dict(region_counts),
            {"Northeast": 25, "Midwest": 25, "South": 25, "West": 15},
        )

        feed_dates = sorted({date.fromisoformat(r["feed_date"]) for r in feeds})
        self.assertEqual(feed_dates[0], FULL_START_DATE)
        self.assertEqual(feed_dates[-1], CUTOFF_DATE)
        self.assertEqual(len(feed_dates), 1127)

        reveal_dates = sorted({date.fromisoformat(r["feed_date"]) for r in reveal_rows})
        self.assertEqual(reveal_dates[0], REVEAL_START_DATE)
        self.assertEqual(reveal_dates[-1], REVEAL_END_DATE)
        self.assertEqual(len(reveal_dates), 42)

        # Backfill run log correlation (40 duplicate rows across 8 NE hospitals x 5 days)
        backfill_runs = [r for r in run_log if r["run_type"] == "backfill"]
        self.assertEqual(len(backfill_runs), 1)
        bf = backfill_runs[0]
        self.assertEqual(bf["run_id"], BACKFILL_RUN_ID)
        self.assertEqual(bf["date_range_start"], BACKFILL_START_DATE.isoformat())
        self.assertEqual(bf["date_range_end"], BACKFILL_END_DATE.isoformat())
        self.assertEqual(int(bf["rows_written"]), 40)

        dup_rows = [
            r
            for r in feeds
            if r["batch_id"] == BACKFILL_BATCH_ID
            and r["ingested_at"] == BACKFILL_INGESTED_AT
        ]
        self.assertEqual(len(dup_rows), 40)

        # 2. Pipeline v1 vs Pipeline Clean equivalence on full-scale dataset (90 hospitals)
        v1_rows = build_v1_rows(feeds, hospitals)
        clean_rows = deduplicate_and_compute_positivity_rows(feeds, hospitals)
        self.assertEqual(len(v1_rows), 101470)
        self.assertEqual(len(clean_rows), 101430)

        clean_keys = {(str(r["hospital_id"]), str(r["feed_date"])) for r in clean_rows}
        self.assertEqual(len(clean_keys), 101430)

        # 3. Workstream 1 EDA heatmap, 4-cause Attribution vs Answer Key, and stats-reviewer
        staging_rows, run_log_rows = load_dataset_tables(self.refined_dataset_dir)
        eda = build_eda_heatmap(staging_rows)
        self.assertEqual(eda["headline_spike_pct"], 35.0)
        self.assertEqual(eda["ne_prior_positives"], 2000)
        self.assertEqual(eda["ne_cutoff_positives"], 2700)

        attribution_rows = reconcile_attribution(
            staging_rows=staging_rows,
            run_log_rows=run_log_rows,
        )
        attr_cmp = compare_attribution_to_answer_key(
            attribution_rows,
            answer_key,
            tolerance_points=ATTRIBUTION_TOLERANCE_POINTS,
        )
        self.assertTrue(attr_cmp["passed"], f"Attribution mismatch: {attr_cmp}")
        self.assertEqual(attr_cmp["total_contributed_points"], 35.0)
        for cause_name, cause_detail in attr_cmp["causes"].items():
            self.assertEqual(
                cause_detail["point_error"],
                0.0,
                f"Expected 0.0 pt error for {cause_name} on full-scale dataset, got {cause_detail}",
            )

        stats_review = run_stats_reviewer_checks(staging_rows)
        self.assertTrue(stats_review["counts_vs_positivity"]["passed"])
        self.assertTrue(stats_review["small_sample_hospitals"]["passed"])
        self.assertTrue(stats_review["simpsons_paradox"]["passed"])

        # 4. Workstream 2 seasonal features and 4-Cohort K-means separation
        loaded_clean = load_clean_staging_rows(self.refined_dataset_dir)
        feature_rows = compute_hospital_seasonal_features(loaded_clean)
        self.assertEqual(len(feature_rows), 90)

        cohort_rows = assign_kmeans_cohorts(feature_rows, k=4, seed=42)
        self.assertEqual(len(cohort_rows), 90)
        cohort_summary = summarize_cohort_separation(cohort_rows)
        self.assertEqual(cohort_summary["num_cohorts"], 4)
        self.assertTrue(cohort_summary["outbreak_isolated_in_own_cohort"])
        self.assertEqual(cohort_summary["outbreak_cohort_id"], "COHORT_4")
        self.assertEqual(
            cohort_summary["outbreak_hospital_ids"],
            list(OUTBREAK_HOSPITAL_IDS),
        )

        # 5. Workstream 2 16-trial backtest leaderboard & post-Cutoff forecast
        trials = run_backtest_trials(
            staging_rows=staging_rows,
            clean_rows=loaded_clean,
        )
        self.assertEqual(len(trials), 16)
        leaderboard = build_forecast_leaderboard(trials)
        self.assertEqual(len(leaderboard), 16)

        wape_by_combo = {
            (
                str(t["cohort_id"]),
                str(t["model_family"]),
                str(t["training_data_version"]),
            ): float(t["backtest_wape"])
            for t in trials
        }
        for cid in COHORT_IDS:
            for fam in MODEL_FAMILIES:
                c_wape = wape_by_combo[(cid, fam, "clean")]
                u_wape = wape_by_combo[(cid, fam, "uncleaned")]
                self.assertLess(c_wape, u_wape)
                self.assertLess(c_wape, 15.0)
                self.assertGreater(u_wape - c_wape, 5.0)

        post_cutoff = forecast_post_cutoff_six_weeks(
            staging_rows=staging_rows,
            clean_rows=loaded_clean,
        )
        self.assertGreaterEqual(post_cutoff["overshoot_pct"], 25.0)

        # 6. Finale Reveal comparison series & overshoot verification
        reveal_series = build_reveal_comparison_series(
            self.refined_dataset_dir,
            self.refined_withheld_dir,
        )
        self.assertEqual(len(reveal_series), REVEAL_HORIZON_WEEKS)
        overshoot = evaluate_reveal_overshoot(reveal_series)
        self.assertTrue(overshoot["every_week_overshoots"])
        self.assertTrue(overshoot["uncleaned_visibly_overshoots"])
        self.assertLess(overshoot["clean_wape"], 1.0)
        self.assertGreater(overshoot["uncleaned_wape"], overshoot["clean_wape"] + 25.0)
        self.assertGreaterEqual(overshoot["uncleaned_mean_overshoot_pct"], 30.0)

    def test_dataset_location_handoff_in_setup_reset_and_verify_start_point(
        self,
    ) -> None:
        """Setting DATASET_LOCATION in demo.env must switch setup, reset (ws1 & ws2), load-raw-ops, and verify-start-point (ws1, ws2, main) to the refined dataset."""
        # Case A: Local refined full-scale dataset path in DATASET_LOCATION
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_location=str(self.refined_dataset_dir),
                dataset_tables=_main_end_state_tables(),
            )

            # 1. bin/setup without --dataset-dir reads DATASET_LOCATION from demo.env
            setup_proc = subprocess.run(
                [str(SETUP_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                setup_proc.returncode,
                0,
                f"setup failed:\n{setup_proc.stdout}\n{setup_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Workstream 1 setup complete and verified.", setup_proc.stdout
            )
            calls_text = log_file.read_text(encoding="utf-8")
            self.assertIn(
                f"{self.refined_dataset_dir}/raw/hospital_reference.csv",
                calls_text,
            )
            self.assertIn(
                f"{self.refined_dataset_dir}/raw/hospital_flu_feeds/feeds.csv",
                calls_text,
            )
            self.assertIn(
                f"{self.refined_dataset_dir}/ops/pipeline_run_log.csv",
                calls_text,
            )
            self.assertNotIn("fixtures/mock_dataset", calls_text)

            # 2. bin/reset ws1 --yes without --dataset-dir reads DATASET_LOCATION from demo.env
            log_file.write_text("", encoding="utf-8")
            reset_ws1_proc = subprocess.run(
                [str(RESET_BIN), "ws1", "--yes", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                reset_ws1_proc.returncode,
                0,
                f"reset ws1 failed:\n{reset_ws1_proc.stdout}\n{reset_ws1_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Reset to Workstream 1 Start Point (ws1) complete and verified.",
                reset_ws1_proc.stdout,
            )
            ws1_calls_text = log_file.read_text(encoding="utf-8")
            self.assertIn(
                f"{self.refined_dataset_dir}/raw/hospital_flu_feeds/feeds.csv",
                ws1_calls_text,
            )
            self.assertNotIn("fixtures/mock_dataset", ws1_calls_text)

            # 3. bin/reset ws2 --yes without --dataset-dir reads DATASET_LOCATION from demo.env
            log_file.write_text("", encoding="utf-8")
            reset_ws2_proc = subprocess.run(
                [str(RESET_BIN), "ws2", "--yes", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                reset_ws2_proc.returncode,
                0,
                f"reset ws2 failed:\n{reset_ws2_proc.stdout}\n{reset_ws2_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Reset to Workstream 2 Start Point (ws2) complete and verified.",
                reset_ws2_proc.stdout,
            )
            ws2_calls_text = log_file.read_text(encoding="utf-8")
            self.assertIn(
                f"{self.refined_dataset_dir}/raw/hospital_flu_feeds/feeds.csv",
                ws2_calls_text,
            )
            self.assertNotIn("fixtures/mock_dataset", ws2_calls_text)

            # 4. Restore main tables and verify-start-point ws1, ws2, and main using DATASET_LOCATION
            bq_state_path = Path(tmpdir) / "bq_tables.json"
            bq_state_path.write_text(
                json.dumps(_main_end_state_tables()), encoding="utf-8"
            )
            for target in ("ws1", "ws2"):
                v_proc = subprocess.run(
                    [str(VERIFY_START_POINT_BIN), target, "--env", str(env_file)],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(v_proc.returncode, 0, v_proc.stderr)
                self.assertIn("[PASS]", v_proc.stdout)

            v_main_proc = subprocess.run(
                [
                    str(VERIFY_START_POINT_BIN),
                    "main",
                    "--withheld-dir",
                    str(self.refined_withheld_dir),
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
                v_main_proc.returncode,
                0,
                f"verify-start-point main failed:\n{v_main_proc.stdout}\n{v_main_proc.stderr}",
            )
            self.assertIn(
                "[PASS] End-state verification (main) passed",
                v_main_proc.stdout,
            )

        # Case B: Cloud Storage gs:// URI in DATASET_LOCATION (Issue #9 hand-off mechanism)
        with tempfile.TemporaryDirectory() as tmpdir:
            gcs_uri = "gs://demo-staging-bucket/refined_dataset"
            withheld_gcs_uri = "gs://presenter-private-withheld-bucket"
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_location=gcs_uri,
                gcs_dataset_dir=self.refined_dataset_dir,
                gcs_withheld_dir=self.refined_withheld_dir,
                dataset_tables=_main_end_state_tables(),
            )

            setup_gcs_proc = subprocess.run(
                [str(SETUP_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(setup_gcs_proc.returncode, 0, setup_gcs_proc.stderr)
            gcs_calls = log_file.read_text(encoding="utf-8")
            self.assertIn(f"{gcs_uri}/raw/hospital_reference.csv", gcs_calls)
            self.assertIn(f"{gcs_uri}/raw/hospital_flu_feeds/feeds.csv", gcs_calls)
            self.assertIn(f"{gcs_uri}/ops/pipeline_run_log.csv", gcs_calls)

            log_file.write_text("", encoding="utf-8")
            v_main_gcs_proc = subprocess.run(
                [
                    str(VERIFY_START_POINT_BIN),
                    "main",
                    "--withheld-dir",
                    withheld_gcs_uri,
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
                v_main_gcs_proc.returncode,
                0,
                f"verify-start-point main with gs:// DATASET_LOCATION failed:\n{v_main_gcs_proc.stdout}\n{v_main_gcs_proc.stderr}",
            )
            self.assertIn(
                "[PASS] End-state verification (main) passed",
                v_main_gcs_proc.stdout,
            )
            stage_calls = _parse_logged_commands(log_file)
            self.assertTrue(
                any(
                    "gcloud storage cp --project=demo-proj-123" in c
                    and f"{gcs_uri}/raw/hospital_flu_feeds/feeds.csv" in c
                    for c in stage_calls
                ),
                "Expected gcloud storage cp to stage refined dataset from gs:// DATASET_LOCATION",
            )
            self.assertTrue(
                any(
                    "gcloud storage cp --project=demo-proj-123" in c
                    and f"{withheld_gcs_uri}/answer_key.json" in c
                    for c in stage_calls
                ),
                "Expected gcloud storage cp to stage Answer Key from gs:// withheld URI",
            )

        # Case C: Empty DATASET_LOCATION falls back to fixtures/mock_dataset for unit tests
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_location="",
            )
            load_proc = subprocess.run(
                [str(LOAD_RAW_OPS_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(load_proc.returncode, 0, load_proc.stderr)
            default_calls = log_file.read_text(encoding="utf-8")
            self.assertIn(
                "fixtures/mock_dataset/raw/hospital_reference.csv", default_calls
            )

    def test_mock_dataset_fixtures_remain_untouched_for_unit_tests(self) -> None:
        """fixtures/mock_dataset and fixtures/mock_withheld must remain untouched at scale='mini' seed=42."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mini_ds = Path(tmpdir) / "mini_ds"
            mini_wh = Path(tmpdir) / "mini_wh"
            generate_dataset(
                seed=42,
                scale="mini",
                output_dir=mini_ds,
                withheld_dir=mini_wh,
            )

            fixture_pairs = [
                (
                    MOCK_DATASET_DIR / "raw" / "hospital_reference.csv",
                    mini_ds / "raw" / "hospital_reference.csv",
                ),
                (
                    MOCK_DATASET_DIR / "raw" / "hospital_flu_feeds" / "feeds.csv",
                    mini_ds / "raw" / "hospital_flu_feeds" / "feeds.csv",
                ),
                (
                    MOCK_DATASET_DIR / "ops" / "pipeline_run_log.csv",
                    mini_ds / "ops" / "pipeline_run_log.csv",
                ),
                (
                    MOCK_WITHHELD_DIR / "answer_key.json",
                    mini_wh / "answer_key.json",
                ),
                (
                    MOCK_WITHHELD_DIR
                    / "reveal"
                    / "hospital_flu_feeds_reveal"
                    / "reveal.csv",
                    mini_wh / "reveal" / "hospital_flu_feeds_reveal" / "reveal.csv",
                ),
            ]
            for committed, generated in fixture_pairs:
                self.assertTrue(committed.is_file(), f"Missing fixture {committed}")
                self.assertEqual(
                    _sha256(committed),
                    _sha256(generated),
                    f"Committed fixture {committed} was modified; must stay in place for unit tests",
                )

    def test_shell_syntax_and_glossary_compliance_on_updated_files(self) -> None:
        """All modified scripts and docs must pass bash -n and node bin/check-glossary.js."""
        for script_path in (
            LOAD_RAW_OPS_BIN,
            SETUP_BIN,
            RESET_BIN,
            VERIFY_MAIN_BIN,
            LOAD_REVEAL_BIN,
        ):
            chk = subprocess.run(
                ["bash", "-n", str(script_path)],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                chk.returncode,
                0,
                f"bash -n failed on {script_path}:\n{chk.stderr}",
            )

        glossary_chk = subprocess.run(
            [
                "node",
                str(WORKTREE_ROOT / "bin" / "check-glossary.js"),
                str(WORKTREE_ROOT / "demo.env.example"),
                str(WORKTREE_ROOT / "docs" / "reuser-guide.md"),
                str(WORKTREE_ROOT / "docs" / "presenter-runbook.md"),
                str(LOAD_RAW_OPS_BIN),
                str(SETUP_BIN),
                str(RESET_BIN),
                str(VERIFY_MAIN_BIN),
                str(Path(__file__).resolve()),
            ],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            glossary_chk.returncode,
            0,
            f"check-glossary.js failed:\n{glossary_chk.stdout}\n{glossary_chk.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
