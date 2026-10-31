"""Tests for Issue #16: Forecast leaderboard (ARIMA_PLUS vs TimesFM)."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from lib.ws2_forecasting import (
    BACKTEST_END_DATE,
    BACKTEST_FORECAST_START_DATE,
    BACKTEST_FORECAST_WEEKS,
    BACKTEST_HORIZON_DAYS,
    BACKTEST_TRAIN_END_DATE,
    COHORT_IDS,
    MODEL_FAMILIES,
    POST_CUTOFF_END_DATE,
    POST_CUTOFF_FORECAST_WEEKS,
    POST_CUTOFF_START_DATE,
    TRAINING_DATA_VERSIONS,
    TRIAL_COLUMNS,
    build_forecast_leaderboard,
    compute_wape,
    forecast_post_cutoff_six_weeks,
    infer_hospital_cohorts,
    load_ws2_forecast_checkpoint_manifests,
    run_backtest_trials,
)
from tests.helpers import (
    CHECKPOINT_BIN,
    CHECKPOINT_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
MOCK_REVEAL_CSV = (
    WORKTREE_ROOT
    / "fixtures"
    / "mock_withheld"
    / "reveal"
    / "hospital_flu_feeds_reveal"
    / "reveal.csv"
)
RUN_WS2_FORECASTS_BIN = WORKTREE_ROOT / "bin" / "run-ws2-forecasts"
RUN_WS2_FORECASTS_SYMLINK = WORKTREE_ROOT / "run-ws2-forecasts"
SQL_TRIALS_FILE = WORKTREE_ROOT / "sql" / "ws2_forecasts_and_trials.sql"
SQL_LEADERBOARD_FILE = WORKTREE_ROOT / "sql" / "ws2_leaderboard.sql"
RECORDED_RUNTIMES_DOC = WORKTREE_ROOT / "docs" / "recorded_runtimes.json"
GUARDRAIL_HOOK = (
    WORKTREE_ROOT
    / ".agents"
    / "plugins"
    / "ds-command-center"
    / "bin"
    / "guardrail-hook"
)


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


class TestWs2ForecastsAndLeaderboard(unittest.TestCase):
    def test_backtest_window_and_sixteen_trials_schema_and_values(self) -> None:
        """2025-26 8-week backtest must train <= 2026-01-03, forecast 8 weeks, and log all 16 trials across Cohorts, families, and data versions."""
        self.assertEqual(BACKTEST_TRAIN_END_DATE, "2026-01-03")
        self.assertEqual(BACKTEST_FORECAST_START_DATE, "2026-01-04")
        self.assertEqual(BACKTEST_FORECAST_WEEKS, 8)
        self.assertEqual(BACKTEST_HORIZON_DAYS, 56)
        self.assertEqual(BACKTEST_END_DATE, "2026-02-28")
        self.assertEqual(MODEL_FAMILIES, ("ARIMA_PLUS", "TimesFM"))
        self.assertEqual(TRAINING_DATA_VERSIONS, ("clean", "uncleaned"))

        # Verify WAPE helper
        self.assertAlmostEqual(
            compute_wape([100.0, 200.0], [90.0, 220.0]),
            10.0,
            places=4,
        )
        self.assertEqual(compute_wape([0.0, 0.0], [5.0, 5.0]), 0.0)
        with self.assertRaises(ValueError):
            compute_wape([10.0], [10.0, 20.0])
        with self.assertRaises(ValueError):
            compute_wape([], [])

        # Ensure production module never references mock_withheld, answer_key.json, or reveal.csv
        forecasting_src = (WORKTREE_ROOT / "lib" / "ws2_forecasting.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("mock_withheld", forecasting_src)
        self.assertNotIn("answer_key.json", forecasting_src)
        self.assertNotIn("reveal.csv", forecasting_src)

        trials = run_backtest_trials(dataset_dir=MOCK_DATASET_DIR)
        self.assertEqual(len(trials), 16)

        seen_combos: set[tuple[str, str, str]] = set()
        wape_lookup: dict[tuple[str, str, str], float] = {}

        for trial in trials:
            self.assertEqual(tuple(trial.keys()), TRIAL_COLUMNS)
            self.assertTrue(str(trial["trial_id"]).startswith("trial-2025-26-peak-8w-"))
            self.assertTrue(str(trial["logged_at"]))
            self.assertIn(trial["model_family"], MODEL_FAMILIES)
            self.assertIn(trial["cohort_id"], COHORT_IDS)
            self.assertIn(trial["training_data_version"], TRAINING_DATA_VERSIONS)
            self.assertGreater(float(trial["backtest_wape"]), 0.0)
            self.assertGreater(float(trial["training_runtime_sec"]), 0.0)

            params = json.loads(str(trial["parameters"]))
            self.assertEqual(params["horizon_days"], 56)
            self.assertEqual(params["train_end_date"], "2026-01-03")
            if trial["model_family"] == "ARIMA_PLUS":
                self.assertEqual(params["model_type"], "ARIMA_PLUS")
                self.assertTrue(params["auto_arima"])
                self.assertEqual(params["data_frequency"], "DAILY")
                self.assertEqual(params["time_series_id_col"], "hospital_id")
            else:
                self.assertEqual(params["model"], "TimesFM 2.0")
                self.assertEqual(params["mode"], "zero_shot")
                self.assertEqual(params["confidence_level"], 0.8)

            combo = (
                str(trial["cohort_id"]),
                str(trial["model_family"]),
                str(trial["training_data_version"]),
            )
            seen_combos.add(combo)
            wape_lookup[combo] = float(trial["backtest_wape"])

        self.assertEqual(len(seen_combos), 16)

        # Clean training data version must achieve strictly lower backtest WAPE than uncleaned
        for cohort_id in COHORT_IDS:
            for family in MODEL_FAMILIES:
                clean_wape = wape_lookup[(cohort_id, family, "clean")]
                uncleaned_wape = wape_lookup[(cohort_id, family, "uncleaned")]
                self.assertLess(
                    clean_wape,
                    uncleaned_wape,
                    f"Expected clean WAPE ({clean_wape}) < uncleaned WAPE ({uncleaned_wape}) "
                    f"for {cohort_id} {family}",
                )
                self.assertLess(clean_wape, 15.0)
                self.assertGreater(uncleaned_wape - clean_wape, 5.0)

    def test_forecast_leaderboard_ranking_and_sql_definitions(self) -> None:
        """build_forecast_leaderboard and sql/ws2_leaderboard.sql must rank families across Cohorts by backtest WAPE."""
        trials = run_backtest_trials(dataset_dir=MOCK_DATASET_DIR)
        leaderboard = build_forecast_leaderboard(trials)
        self.assertEqual(len(leaderboard), 16)

        by_cohort: dict[str, list[dict[str, object]]] = {}
        for row in leaderboard:
            cid = str(row["cohort_id"])
            by_cohort.setdefault(cid, []).append(row)

        self.assertEqual(tuple(sorted(by_cohort.keys())), COHORT_IDS)
        for cid, rows in by_cohort.items():
            self.assertEqual(len(rows), 4)
            ranks = [int(r["cohort_rank"]) for r in rows]  # type: ignore[arg-type]
            self.assertEqual(ranks, [1, 2, 3, 4])
            wapes = [float(r["backtest_wape"]) for r in rows]  # type: ignore[arg-type]
            self.assertEqual(wapes, sorted(wapes))
            # Top 2 in every Cohort must be trained on clean data
            self.assertEqual(rows[0]["training_data_version"], "clean")
            self.assertEqual(rows[1]["training_data_version"], "clean")
            self.assertEqual(rows[2]["training_data_version"], "uncleaned")
            self.assertEqual(rows[3]["training_data_version"], "uncleaned")
            # Overall rank 1 and 2 across Cohorts must also be clean data versions
            self.assertIn(rows[0]["overall_family_rank"], (1, 2))
            self.assertIn(rows[2]["overall_family_rank"], (3, 4))

        # Verify SQL files exist and contain required BigQuery constructs
        self.assertTrue(SQL_TRIALS_FILE.is_file())
        self.assertTrue(SQL_LEADERBOARD_FILE.is_file())

        trials_sql = SQL_TRIALS_FILE.read_text(encoding="utf-8")
        for token in (
            "model_type='ARIMA_PLUS'",
            "time_series_timestamp_col='feed_date'",
            "time_series_data_col='positive_flu_tests'",
            "time_series_id_col='hospital_id'",
            "auto_arima=TRUE",
            "data_frequency='DAILY'",
            "AI.FORECAST",
            "model => 'TimesFM 2.0'",
            "horizon => 56",
            "confidence_level => 0.8",
            "DATE '2026-01-03'",
            "DATE '2026-01-04'",
            "DATE '2026-02-28'",
            "staging.hospital_flu_clean",
            "staging.hospital_flu",
            "trial_id",
            "logged_at",
            "model_family",
            "cohort_id",
            "parameters",
            "training_data_version",
            "backtest_wape",
            "training_runtime_sec",
        ):
            self.assertIn(token, trials_sql)

        leaderboard_sql = SQL_LEADERBOARD_FILE.read_text(encoding="utf-8")
        for token in (
            "ml.experiment_trials",
            "RANK() OVER (PARTITION BY cohort_id ORDER BY backtest_wape ASC) AS cohort_rank",
            "mean_wape_across_cohorts",
            "overall_family_rank",
        ):
            self.assertIn(token, leaderboard_sql)

    def test_post_cutoff_six_weeks_forecast_clean_vs_uncleaned_overshoot(self) -> None:
        """forecast_post_cutoff_six_weeks must project 6 weeks (2026-11-01..2026-12-12) where uncleaned visibly overshoots clean and the Reveal."""
        forecast_bundle = forecast_post_cutoff_six_weeks(dataset_dir=MOCK_DATASET_DIR)
        self.assertEqual(forecast_bundle["forecast_start_date"], POST_CUTOFF_START_DATE)
        self.assertEqual(forecast_bundle["forecast_end_date"], POST_CUTOFF_END_DATE)
        self.assertEqual(forecast_bundle["horizon_weeks"], POST_CUTOFF_FORECAST_WEEKS)
        self.assertEqual(forecast_bundle["horizon_days"], 42)

        clean_weekly = forecast_bundle["clean"]["weekly_northeast_positives"]
        uncleaned_weekly = forecast_bundle["uncleaned"]["weekly_northeast_positives"]
        self.assertEqual(len(clean_weekly), 6)
        self.assertEqual(len(uncleaned_weekly), 6)

        for wk_idx in range(6):
            self.assertGreater(
                uncleaned_weekly[wk_idx],
                clean_weekly[wk_idx] * 1.25,
                f"Week {wk_idx + 1} uncleaned forecast must exceed clean forecast by >25%",
            )

        self.assertGreaterEqual(forecast_bundle["overshoot_pct"], 25.0)

        # Compare against the withheld 6-week Reveal in fixtures/mock_withheld
        with MOCK_REVEAL_CSV.open("r", encoding="utf-8", newline="") as f:
            reveal_rows = list(csv.DictReader(f))

        reveal_ne_weekly = [0.0] * 6
        post_start = date.fromisoformat(POST_CUTOFF_START_DATE)
        for row in reveal_rows:
            if not str(row["hospital_id"]).startswith("HOSP_NE_"):
                continue
            fdate = date.fromisoformat(str(row["feed_date"]))
            wk_idx = (fdate - post_start).days // 7
            if 0 <= wk_idx < 6:
                reveal_ne_weekly[wk_idx] += float(row["positive_flu_tests"])

        clean_reveal_wape = compute_wape(reveal_ne_weekly, clean_weekly)
        uncleaned_reveal_wape = compute_wape(reveal_ne_weekly, uncleaned_weekly)
        self.assertLess(clean_reveal_wape, 3.0)
        self.assertGreater(uncleaned_reveal_wape, 25.0)

        # Also verify infer_hospital_cohorts separates Outbreak hospitals into COHORT_1
        cohorts = infer_hospital_cohorts(forecast_bundle["clean"]["daily_forecasts"])
        self.assertEqual(len(cohorts), 20)

    def test_run_ws2_forecasts_cli_checkpoints_and_recorded_runtimes(self) -> None:
        """bin/run-ws2-forecasts, Checkpoints, recorded_runtimes.json, guardrail-hook, and check-glossary.js must all pass."""
        for path in (
            RUN_WS2_FORECASTS_BIN,
            RUN_WS2_FORECASTS_SYMLINK,
            RECORDED_RUNTIMES_DOC,
        ):
            self.assertTrue(path.exists(), f"{path} must exist")
        self.assertTrue(os.access(RUN_WS2_FORECASTS_BIN, os.X_OK))
        self.assertTrue(os.access(RUN_WS2_FORECASTS_SYMLINK, os.X_OK))

        # Check committed docs/recorded_runtimes.json
        doc_runtimes = json.loads(RECORDED_RUNTIMES_DOC.read_text(encoding="utf-8"))
        for key, expected_family in (
            ("ws2_arima_plus_cohort_training", "ARIMA_PLUS"),
            ("ws2_timesfm_ai_forecast", "TimesFM"),
        ):
            self.assertIn(key, doc_runtimes)
            entry = doc_runtimes[key]
            self.assertEqual(entry["model_family"], expected_family)
            self.assertEqual(entry["runner"], "bin/run-ws2-forecasts")
            self.assertEqual(entry["target_table"], "ml.experiment_trials")
            self.assertGreater(int(entry["baseline_observed_seconds"]), 0)
            self.assertGreater(int(entry["last_observed_seconds"]), 0)

        # Check Checkpoint descriptors
        manifests = load_ws2_forecast_checkpoint_manifests(WORKTREE_ROOT)
        self.assertIn("ws2_experiment_trials", manifests)
        self.assertIn("ws2_forecast_leaderboard", manifests)
        self.assertEqual(
            manifests["ws2_experiment_trials"]["target_table"],
            "ml.experiment_trials",
        )
        self.assertEqual(
            manifests["ws2_forecast_leaderboard"]["target_table"],
            "ml.forecast_leaderboard",
        )

        # Run bin/run-ws2-forecasts and verify bq query + demo:true labels + runtime recording
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
                [str(RUN_WS2_FORECASTS_SYMLINK), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"run-ws2-forecasts failed:\n{proc.stdout}\n{proc.stderr}",
            )
            self.assertIn("[PASS]", proc.stdout)

            final_state = json.loads(
                (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                final_state["ml"].get("experiment_trials"),
                {"demo": "true"},
            )
            self.assertEqual(
                final_state["ml"].get("forecast_leaderboard"),
                {"demo": "true"},
            )

            recorded = json.loads(
                Path(env["RECORDED_RUNTIMES_FILE"]).read_text(encoding="utf-8")
            )
            self.assertIn("ws2_arima_plus_cohort_training", recorded)
            self.assertIn("ws2_timesfm_ai_forecast", recorded)

            forecast_calls = _parse_logged_commands(log_file)
            self.assertTrue(
                any(
                    "--destination_table=demo-proj-123:ml.experiment_trials" in c
                    for c in forecast_calls
                )
            )
            self.assertTrue(
                any(
                    "--destination_table=demo-proj-123:ml.forecast_leaderboard" in c
                    for c in forecast_calls
                )
            )
            for cmd_line in forecast_calls:
                cmd_payload = {
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": cmd_line},
                    },
                    "stepIdx": 1,
                }
                hook_proc = subprocess.run(
                    [str(GUARDRAIL_HOOK)],
                    cwd=WORKTREE_ROOT,
                    input=json.dumps(cmd_payload),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(hook_proc.returncode, 0)
                self.assertEqual(json.loads(hook_proc.stdout).get("decision"), "allow")

            # Verify bin/checkpoint --list, --build, and swap for both ws2 Checkpoints
            list_proc = subprocess.run(
                [str(CHECKPOINT_SYMLINK), "--list"],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(list_proc.returncode, 0)
            self.assertIn("ws2_experiment_trials", list_proc.stdout)
            self.assertIn("ws2_forecast_leaderboard", list_proc.stdout)

            for cid, ckpt_tbl, target_tbl in (
                (
                    "ws2_experiment_trials",
                    "ws2_experiment_trials",
                    "experiment_trials",
                ),
                (
                    "ws2_forecast_leaderboard",
                    "ws2_forecast_leaderboard",
                    "forecast_leaderboard",
                ),
            ):
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

                updated_state = json.loads(
                    (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    updated_state["checkpoint"].get(ckpt_tbl),
                    {"demo": "true"},
                )
                self.assertEqual(
                    updated_state["ml"].get(target_tbl),
                    {"demo": "true"},
                )

            # Verify every logged CLI command from bin/run-ws2-forecasts (before checkpoint calls)
            # and both SQL files pass guardrail-hook when executed by an agent
            for sql_path in (SQL_TRIALS_FILE, SQL_LEADERBOARD_FILE):
                sql_payload = {
                    "toolCall": {
                        "name": "execute_sql",
                        "args": {"sql": sql_path.read_text(encoding="utf-8")},
                    },
                    "stepIdx": 1,
                }
                hook_proc = subprocess.run(
                    [str(GUARDRAIL_HOOK)],
                    cwd=WORKTREE_ROOT,
                    input=json.dumps(sql_payload),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(hook_proc.returncode, 0)
                self.assertEqual(json.loads(hook_proc.stdout).get("decision"), "allow")

        # Verify all Issue #16 files pass node bin/check-glossary.js
        issue_16_files = [
            "sql/ws2_forecasts_and_trials.sql",
            "sql/ws2_leaderboard.sql",
            "lib/ws2_forecasting.py",
            "bin/run-ws2-forecasts",
            "checkpoints/manifest.d/ws2_experiment_trials.json",
            "checkpoints/manifest.d/ws2_forecast_leaderboard.json",
            "docs/recorded_runtimes.json",
            "tests/test_ws2_forecasts_and_leaderboard.py",
        ]
        glossary_proc = subprocess.run(
            ["node", "bin/check-glossary.js", *issue_16_files],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            glossary_proc.returncode,
            0,
            f"check-glossary.js failed:\n{glossary_proc.stdout}\n{glossary_proc.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
