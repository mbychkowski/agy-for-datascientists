"""Tests for Issue #17: Reveal load and end-state verification."""

from __future__ import annotations

import csv
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from lib.reveal_chart import (
    REVEAL_HORIZON_WEEKS,
    build_reveal_comparison_series,
    evaluate_reveal_overshoot,
    load_reveal_feeds,
    render_reveal_chart_ascii,
    render_reveal_chart_svg,
    resolve_answer_key_path,
    resolve_reveal_csv_path,
)
from tests.helpers import (
    RESET_BIN,
    VERIFY_START_POINT_BIN,
    VERIFY_START_POINT_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

LOAD_REVEAL_BIN = WORKTREE_ROOT / "bin" / "load-reveal"
LOAD_REVEAL_SYMLINK = WORKTREE_ROOT / "load-reveal"
VERIFY_MAIN_BIN = WORKTREE_ROOT / "bin" / "verify-main-end-state"
REVEAL_SQL_FILE = WORKTREE_ROOT / "sql" / "ws2_reveal_comparison.sql"
REVEAL_CHART_LIB = WORKTREE_ROOT / "lib" / "reveal_chart.py"
MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
MOCK_WITHHELD_DIR = WORKTREE_ROOT / "fixtures" / "mock_withheld"
GUARDRAIL_HOOK = (
    WORKTREE_ROOT
    / ".agents"
    / "plugins"
    / "ds-command-center"
    / "bin"
    / "guardrail-hook"
)


def _parse_logged_commands(log_file: Path) -> list[str]:
    """Group multi-line logged CLI invocations into full commands."""
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
    """Return a stateful BigQuery table map representing the completed main end-state."""
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


class TestRevealAndVerifyMain(unittest.TestCase):
    def test_executables_symlinks_and_adr_0001_no_hardcoded_withheld_paths(
        self,
    ) -> None:
        """Issue #17 scripts and symlinks must exist, be executable, and never hardcode mock_withheld (ADR 0001)."""
        for path in (
            LOAD_REVEAL_BIN,
            LOAD_REVEAL_SYMLINK,
            VERIFY_MAIN_BIN,
            VERIFY_START_POINT_BIN,
            VERIFY_START_POINT_SYMLINK,
            REVEAL_SQL_FILE,
            REVEAL_CHART_LIB,
        ):
            self.assertTrue(path.exists(), f"{path} must exist")

        for exec_path in (
            LOAD_REVEAL_BIN,
            LOAD_REVEAL_SYMLINK,
            VERIFY_MAIN_BIN,
            VERIFY_START_POINT_BIN,
        ):
            self.assertTrue(
                os.access(exec_path, os.X_OK), f"{exec_path} must be executable"
            )

        self.assertEqual(LOAD_REVEAL_SYMLINK.resolve(), LOAD_REVEAL_BIN.resolve())

        # ADR 0001: neither load-reveal, verify-main-end-state, nor lib/reveal_chart.py may hardcode mock_withheld
        for source_file in (LOAD_REVEAL_BIN, VERIFY_MAIN_BIN, REVEAL_CHART_LIB):
            content = source_file.read_text(encoding="utf-8")
            self.assertNotIn(
                "mock_withheld",
                content,
                f"{source_file} must never hardcode fixtures/mock_withheld (ADR 0001)",
            )

    def test_reveal_chart_series_overshoot_svg_and_ascii_on_mock_dataset(self) -> None:
        """lib/reveal_chart.py must show Reveal observed counts against clean and uncleaned forecasts, with uncleaned visibly overshooting."""
        reveal_csv = resolve_reveal_csv_path(MOCK_WITHHELD_DIR)
        self.assertTrue(reveal_csv.is_file())
        ak_json = resolve_answer_key_path(MOCK_WITHHELD_DIR)
        self.assertTrue(ak_json.is_file())

        reveal_rows = load_reveal_feeds(MOCK_WITHHELD_DIR)
        self.assertEqual(len(reveal_rows), 20 * 42)

        series = build_reveal_comparison_series(MOCK_DATASET_DIR, MOCK_WITHHELD_DIR)
        self.assertEqual(len(series), REVEAL_HORIZON_WEEKS)
        self.assertEqual(series[0]["week_start"], "2026-11-01")
        self.assertEqual(series[-1]["week_end"], "2026-12-12")

        metrics = evaluate_reveal_overshoot(series)
        self.assertTrue(metrics["every_week_overshoots"])
        self.assertTrue(metrics["uncleaned_visibly_overshoots"])
        self.assertLess(metrics["clean_wape"], 1.0)
        self.assertGreater(metrics["uncleaned_wape"], metrics["clean_wape"] + 25.0)
        self.assertGreaterEqual(metrics["uncleaned_mean_overshoot_pct"], 30.0)

        svg_out = render_reveal_chart_svg(series)
        self.assertIn("<svg", svg_out)
        self.assertIn("Reveal Observed", svg_out)
        self.assertIn("Clean Forecast", svg_out)
        self.assertIn("Uncleaned Forecast (Overshoots)", svg_out)

        ascii_out = render_reveal_chart_ascii(series)
        self.assertIn("Reveal Observed", ascii_out)
        self.assertIn("Clean Forecast", ascii_out)
        self.assertIn("Uncleaned Forecast", ascii_out)
        self.assertIn("Mean Uncleaned Overshoot", ascii_out)

    def test_load_reveal_requires_runtime_location_never_persists_and_reset_removes_table(
        self,
    ) -> None:
        """bin/load-reveal must require <reveal_location> at runtime, never persist it, load raw.hospital_flu_feeds_reveal with demo:true, and reset must drop it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables=_main_end_state_tables(),
            )
            env_before = env_file.read_text(encoding="utf-8")

            # 1. Missing <reveal_location> fails fast
            missing_proc = subprocess.run(
                [str(LOAD_REVEAL_SYMLINK), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(missing_proc.returncode, 0)
            self.assertIn(
                "[FAIL] Missing required Reveal location argument",
                missing_proc.stderr,
            )

            # 2. Supplying runtime <reveal_location> loads raw.hospital_flu_feeds_reveal and staging.reveal_forecast_comparison
            svg_file = Path(tmpdir) / "reveal_chart.svg"
            load_proc = subprocess.run(
                [
                    str(LOAD_REVEAL_SYMLINK),
                    "--env",
                    str(env_file),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                    "--chart-out",
                    str(svg_file),
                    str(MOCK_WITHHELD_DIR),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                load_proc.returncode,
                0,
                f"load-reveal failed:\nSTDOUT:\n{load_proc.stdout}\nSTDERR:\n{load_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Loaded demo-proj-123:raw.hospital_flu_feeds_reveal and materialised demo-proj-123:staging.reveal_forecast_comparison with label demo:true.",
                load_proc.stdout,
            )
            self.assertIn("Uncleaned Forecast", load_proc.stdout)
            self.assertTrue(svg_file.is_file())
            self.assertIn("<svg", svg_file.read_text(encoding="utf-8"))

            # Verify ADR 0001: demo.env was never modified or polluted with the Reveal path
            env_after = env_file.read_text(encoding="utf-8")
            self.assertEqual(env_before, env_after)
            self.assertNotIn(str(MOCK_WITHHELD_DIR), env_after)

            # Verify BigQuery state has raw.hospital_flu_feeds_reveal and staging.reveal_forecast_comparison with demo:true
            bq_state_path = Path(tmpdir) / "bq_tables.json"
            state_after_load = json.loads(bq_state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                state_after_load["raw"].get("hospital_flu_feeds_reveal"),
                {"demo": "true"},
            )
            self.assertEqual(
                state_after_load["staging"].get("reveal_forecast_comparison"),
                {"demo": "true"},
            )

            # 3. Running bin/reset ws1 --yes removes raw.hospital_flu_feeds_reveal and staging.reveal_forecast_comparison
            reset_proc = subprocess.run(
                [
                    str(RESET_BIN),
                    "ws1",
                    "--yes",
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
                reset_proc.returncode,
                0,
                f"reset ws1 failed:\n{reset_proc.stdout}\n{reset_proc.stderr}",
            )
            self.assertIn(
                "demo-proj-123:raw.hospital_flu_feeds_reveal", reset_proc.stdout
            )
            self.assertIn(
                "demo-proj-123:staging.reveal_forecast_comparison", reset_proc.stdout
            )

            state_after_reset = json.loads(bq_state_path.read_text(encoding="utf-8"))
            self.assertNotIn("hospital_flu_feeds_reveal", state_after_reset["raw"])
            self.assertNotIn("reveal_forecast_comparison", state_after_reset["staging"])

            # 4. Also verify gs:// URI resolution in bin/load-reveal
            gs_proc = subprocess.run(
                [
                    str(LOAD_REVEAL_BIN),
                    "--env",
                    str(env_file),
                    "gs://presenter-private-withheld-bucket",
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(gs_proc.returncode, 0, gs_proc.stderr)
            calls = _parse_logged_commands(log_file)
            self.assertTrue(
                any(
                    "load --replace" in c
                    and "gs://presenter-private-withheld-bucket/reveal/hospital_flu_feeds_reveal/reveal.csv"
                    in c
                    for c in calls
                )
            )

    def test_verify_start_point_main_passes_on_mock_dataset_and_is_read_only(
        self,
    ) -> None:
        """bin/verify-start-point main must verify Attribution vs Answer Key and Reveal overshoot read-only."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables=_main_end_state_tables(),
            )

            proc = subprocess.run(
                [
                    str(VERIFY_START_POINT_SYMLINK),
                    "main",
                    "--withheld-dir",
                    str(MOCK_WITHHELD_DIR),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
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
                proc.returncode,
                0,
                f"verify-start-point main failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
            )
            self.assertIn(
                "[PASS] End-state verification (main) passed: Attribution matches Answer Key within tolerance and uncleaned forecast visibly overshoots in the Reveal.",
                proc.stdout,
            )

            # Confirm every BigQuery CLI invocation is strictly read-only and allowed by guardrail-hook
            calls = _parse_logged_commands(log_file)
            self.assertGreater(len(calls), 0)
            for cmd_line in calls:
                self.assertNotIn(" load ", cmd_line)
                self.assertNotIn(" rm ", cmd_line)
                self.assertNotIn(" cp ", cmd_line)
                self.assertNotIn(" update ", cmd_line)
                self.assertNotIn("checkpoint", cmd_line)
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

    def test_verify_start_point_main_fails_on_missing_runtime_args_bad_answer_key_or_no_overshoot(
        self,
    ) -> None:
        """bin/verify-start-point main must fail if runtime withheld paths are omitted, Attribution mismatches Answer Key, or uncleaned forecast does not overshoot."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables=_main_end_state_tables(),
            )

            # 1. Omitting --withheld-dir / --answer-key fails fast
            no_arg_proc = subprocess.run(
                [str(VERIFY_START_POINT_BIN), "main", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(no_arg_proc.returncode, 0)
            self.assertIn(
                "[FAIL] Missing required runtime Answer Key / Reveal location",
                no_arg_proc.stderr,
            )

            # 2. Tampered Answer Key where pipeline_defect target_points is 25.0 instead of 15.0 fails tolerance check
            bad_ak_path = Path(tmpdir) / "bad_answer_key.json"
            ak_data = json.loads(
                (MOCK_WITHHELD_DIR / "answer_key.json").read_text(encoding="utf-8")
            )
            ak_data["attribution"][0]["target_points"] = 25.0
            bad_ak_path.write_text(json.dumps(ak_data), encoding="utf-8")

            bad_ak_proc = subprocess.run(
                [
                    str(VERIFY_START_POINT_BIN),
                    "main",
                    "--answer-key",
                    str(bad_ak_path),
                    "--reveal",
                    str(MOCK_WITHHELD_DIR),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                    "--env",
                    str(env_file),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(bad_ak_proc.returncode, 0)
            self.assertIn(
                "[FAIL] Attribution does not match Answer Key within tolerance",
                bad_ak_proc.stderr,
            )

            # 3. Inflated Reveal CSV where observed counts exceed the uncleaned forecast fails overshoot check
            inflated_reveal_csv = Path(tmpdir) / "inflated_reveal.csv"
            src_reveal_csv = resolve_reveal_csv_path(MOCK_WITHHELD_DIR)
            with (
                src_reveal_csv.open("r", encoding="utf-8", newline="") as src_f,
                inflated_reveal_csv.open("w", encoding="utf-8", newline="") as dst_f,
            ):
                reader = csv.DictReader(src_f)
                assert reader.fieldnames is not None
                writer = csv.DictWriter(dst_f, fieldnames=reader.fieldnames)
                writer.writeheader()
                for row in reader:
                    row["positive_flu_tests"] = str(int(row["positive_flu_tests"]) * 3)
                    row["total_flu_tests"] = str(int(row["total_flu_tests"]) * 3)
                    writer.writerow(row)

            no_overshoot_proc = subprocess.run(
                [
                    str(VERIFY_START_POINT_BIN),
                    "main",
                    "--answer-key",
                    str(MOCK_WITHHELD_DIR / "answer_key.json"),
                    "--reveal",
                    str(inflated_reveal_csv),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                    "--env",
                    str(env_file),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(no_overshoot_proc.returncode, 0)
            self.assertIn(
                "[FAIL] Uncleaned forecast does not visibly overshoot in the Reveal",
                no_overshoot_proc.stderr,
            )

    def test_none_of_issue_017_files_exist_on_workstream_1_start_branch(self) -> None:
        """None of the Issue #17 files may exist on the workstream-1-start branch."""
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
            fetch_chk = subprocess.run(
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
            if fetch_chk.returncode == 0:
                branch_ref = "origin/workstream-1-start"

        self.assertIsNotNone(branch_ref, "Expected workstream-1-start branch to exist")
        ls_proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", str(branch_ref)],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        branch_files = set(ls_proc.stdout.splitlines())

        issue_017_files = (
            "lib/reveal_chart.py",
            "sql/ws2_reveal_comparison.sql",
            "bin/load-reveal",
            "load-reveal",
            "bin/verify-main-end-state",
            "tests/test_reveal_and_verify_main.py",
        )
        for rel_path in issue_017_files:
            self.assertNotIn(
                rel_path,
                branch_files,
                f"{rel_path} must NOT exist on {branch_ref}",
            )


if __name__ == "__main__":
    unittest.main()
