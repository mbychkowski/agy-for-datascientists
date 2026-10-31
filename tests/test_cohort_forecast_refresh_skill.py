"""Tests for Issue #18: cohort-forecast-refresh reference skill."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lib.cohort_forecast_refresh import (
    COHORT_IDS,
    build_baseline_trials,
    execute_refresh_for_period,
)
from tests.helpers import WORKTREE_ROOT, setup_preflight_test_env

PLUGIN_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "ds-command-center"
SKILL_FILE = PLUGIN_DIR / "skills" / "cohort-forecast-refresh" / "SKILL.md"
GUARDRAIL_HOOK = PLUGIN_DIR / "bin" / "guardrail-hook"
PRE_COMMAND_HOOK = WORKTREE_ROOT / "bin" / "agent-pre-command-hook"
REFRESH_BIN = WORKTREE_ROOT / "bin" / "run-cohort-forecast-refresh"
REFRESH_SYMLINK = WORKTREE_ROOT / "run-cohort-forecast-refresh"
MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"


def _parse_frontmatter(markdown_text: str) -> tuple[dict[str, str], str]:
    """Parse YAML frontmatter (`--- ... ---`) from a skill markdown file."""
    lines = markdown_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("Missing opening YAML frontmatter delimiter '---'")
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("Missing closing YAML frontmatter delimiter '---'")

    meta: dict[str, str] = {}
    for line in lines[1:end_idx]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, sep, val = stripped.partition(":")
        if not sep:
            raise ValueError(f"Invalid frontmatter line: {line!r}")
        meta[key.strip()] = val.strip()

    body = "\n".join(lines[end_idx + 1 :]).strip()
    return meta, body


class TestCohortForecastRefreshSkill(unittest.TestCase):
    def _invoke_hook(
        self,
        tool_name: str,
        args: dict[str, Any],
        hook_bin: Path = GUARDRAIL_HOOK,
    ) -> dict[str, Any]:
        payload = {
            "toolCall": {
                "name": tool_name,
                "args": args,
            },
            "stepIdx": 1,
        }
        proc = subprocess.run(
            [str(hook_bin)],
            cwd=WORKTREE_ROOT,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"Hook {hook_bin} exited with {proc.returncode}: {proc.stderr}",
        )
        return json.loads(proc.stdout)

    def test_skill_lives_in_ds_command_center_is_readable_markdown_and_assumes_dak(
        self,
    ) -> None:
        """SKILL.md must live in ds-command-center, have valid frontmatter, and assume Data Agent Kit."""
        self.assertTrue(SKILL_FILE.is_file(), f"Missing skill file: {SKILL_FILE}")
        raw_text = SKILL_FILE.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw_text)

        self.assertEqual(meta.get("name"), "cohort-forecast-refresh")
        self.assertTrue(
            meta.get("description"),
            "SKILL.md must define a non-empty description in YAML frontmatter",
        )
        self.assertGreaterEqual(
            len(body.splitlines()),
            40,
            "SKILL.md must contain readable, step-by-step markdown documentation",
        )

        # Must reference Data Agent Kit skills and MCP server
        self.assertIn("Data Agent Kit", body)
        self.assertIn("dak-bigquery", body)
        self.assertIn("bigquery-ai-ml", body)
        self.assertIn("bigquery-sql", body)

        # Must document explicit project and region pinning and dataset boundaries
        self.assertIn("demo.env", body)
        self.assertIn("PROJECT_ID", body)
        self.assertIn("REGION", body)
        self.assertIn("--project_id=", body)
        self.assertIn("--location=", body)
        self.assertIn("features.hospital_seasonal_features", body)
        self.assertIn("features.hospital_cohorts", body)
        self.assertIn("ml.experiment_trials", body)
        self.assertIn("ml.forecast_leaderboard", body)
        self.assertIn("ARIMA_PLUS", body)
        self.assertIn("TimesFM", body)
        self.assertIn("AI.FORECAST", body)
        self.assertIn("bin/run-cohort-forecast-refresh", body)

        # Plugin manifest registration
        plugin_manifest = json.loads(
            (PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertIn(
            "skills/cohort-forecast-refresh/SKILL.md",
            plugin_manifest.get("skills", []),
        )

        # CLI runner and root symlink
        self.assertTrue(
            REFRESH_BIN.is_file(), "bin/run-cohort-forecast-refresh must exist"
        )
        self.assertTrue(
            os.access(REFRESH_BIN, os.X_OK),
            "bin/run-cohort-forecast-refresh must be executable",
        )
        self.assertTrue(
            REFRESH_SYMLINK.is_symlink(),
            "Root symlink run-cohort-forecast-refresh must exist",
        )
        self.assertEqual(REFRESH_SYMLINK.resolve(), REFRESH_BIN.resolve())

    def test_fresh_agent_runs_skill_for_next_period_and_new_trials_appear_in_experiment_trials(
        self,
    ) -> None:
        """Simulating a fresh agent running cohort-forecast-refresh for a next period appends new trials to experiment_trials."""
        baseline_trials = build_baseline_trials(MOCK_DATASET_DIR)
        self.assertEqual(len(baseline_trials), 12)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env_file, env, _ = setup_preflight_test_env(
                tmp_path,
                project_id="demo-proj-018",
                region="us-central1",
                dataset_tables={
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
                    "features": {},
                    "ml": {
                        "experiment_trials": {"demo": "true"},
                    },
                    "checkpoint": {},
                },
            )

            state_file = tmp_path / "experiment_state.json"
            state_file.write_text(
                json.dumps({"experiment_trials": baseline_trials}, indent=2),
                encoding="utf-8",
            )
            env["COHORT_REFRESH_STATE_FILE"] = str(state_file)

            out_w44 = tmp_path / "refresh_w44.json"
            proc_w44 = subprocess.run(
                [
                    str(REFRESH_BIN),
                    "--period",
                    "2026-W44",
                    "--cutoff-date",
                    "2026-11-07",
                    "--env",
                    str(env_file),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                    "--output-json",
                    str(out_w44),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc_w44.returncode,
                0,
                f"Refresh W44 failed:\n{proc_w44.stdout}\n{proc_w44.stderr}",
            )
            self.assertIn("[PASS]", proc_w44.stdout)
            self.assertIn("period=2026-W44", proc_w44.stdout)

            data_w44 = json.loads(out_w44.read_text(encoding="utf-8"))
            self.assertEqual(data_w44["prior_trial_count"], 12)
            self.assertEqual(data_w44["new_trial_count"], 8)
            self.assertEqual(data_w44["total_trial_count"], 20)
            self.assertEqual(len(data_w44["experiment_trials"]), 20)

            # Verify all 4 Cohorts are populated and Outbreak hospitals form cohort_1
            cohorts = data_w44["hospital_cohorts"]
            self.assertEqual(len(cohorts), 20)
            populated_cohorts = {c["cohort_id"] for c in cohorts}
            self.assertEqual(populated_cohorts, set(COHORT_IDS))
            cohort_1_hospitals = sorted(
                c["hospital_id"] for c in cohorts if c["cohort_id"] == "cohort_1"
            )
            self.assertEqual(
                cohort_1_hospitals,
                ["HOSP_NE_001", "HOSP_NE_004", "HOSP_NE_006"],
            )

            # Verify new 2026-W44 trials in experiment_trials
            w44_trials = [
                t for t in data_w44["experiment_trials"] if "2026_w44" in t["trial_id"]
            ]
            self.assertEqual(len(w44_trials), 8)
            families = {t["model_family"] for t in w44_trials}
            self.assertEqual(families, {"ARIMA_PLUS", "TimesFM"})

            for trial in w44_trials:
                self.assertIn(trial["cohort_id"], COHORT_IDS)
                self.assertEqual(trial["training_data_version"], "clean_v2_2026_w44")
                self.assertEqual(
                    trial["logged_at"],
                    "2026-11-07T08:00:00Z"
                    if trial["model_family"] == "ARIMA_PLUS"
                    else "2026-11-07T08:05:00Z",
                )
                self.assertGreater(float(trial["backtest_wape"]), 0.0)
                self.assertLess(float(trial["backtest_wape"]), 0.25)
                self.assertGreater(float(trial["training_runtime_sec"]), 0.0)
                params = json.loads(trial["parameters"])
                self.assertEqual(params["period"], "2026-W44")
                self.assertEqual(params["cutoff_date"], "2026-11-07")

            # Verify cleaned trials beat uncleaned baseline trials in every Cohort
            leaderboard = data_w44["forecast_leaderboard"]
            self.assertEqual(len(leaderboard), 20)
            for cohort_id in COHORT_IDS:
                cohort_rows = [r for r in leaderboard if r["cohort_id"] == cohort_id]
                self.assertEqual(cohort_rows[0]["cohort_rank"], 1)
                self.assertNotIn("uncleaned", cohort_rows[0]["training_data_version"])
                self.assertIn("uncleaned", cohort_rows[-1]["training_data_version"])

            # Run a second consecutive refresh for 2026-W45 and confirm trials accumulate
            out_w45 = tmp_path / "refresh_w45.json"
            proc_w45 = subprocess.run(
                [
                    str(REFRESH_BIN),
                    "--period",
                    "2026-W45",
                    "--cutoff-date",
                    "2026-11-14",
                    "--env",
                    str(env_file),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                    "--output-json",
                    str(out_w45),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_w45.returncode, 0)
            data_w45 = json.loads(out_w45.read_text(encoding="utf-8"))
            self.assertEqual(data_w45["prior_trial_count"], 20)
            self.assertEqual(data_w45["new_trial_count"], 8)
            self.assertEqual(data_w45["total_trial_count"], 28)

            # Verify bq_tables.json state has labeled working tables
            bq_state = json.loads(
                (tmp_path / "bq_tables.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                bq_state["features"].get("hospital_seasonal_features"),
                {"demo": "true"},
            )
            self.assertEqual(
                bq_state["features"].get("hospital_cohorts"),
                {"demo": "true"},
            )
            self.assertEqual(
                bq_state["ml"].get("experiment_trials"),
                {"demo": "true"},
            )
            self.assertEqual(
                bq_state["ml"].get("forecast_leaderboard"),
                {"demo": "true"},
            )

    def test_skill_pins_project_and_region_and_passes_guardrail_hook(self) -> None:
        """Every CLI command and SQL statement executed by the skill must pin project/region and be allowed by guardrail-hook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env_file, env, log_file = setup_preflight_test_env(
                tmp_path,
                project_id="pinned-proj-999",
                region="us-east4",
            )
            proc = subprocess.run(
                [
                    str(REFRESH_BIN),
                    "--period",
                    "2026-W44",
                    "--cutoff-date",
                    "2026-11-07",
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
                f"Output:\n{proc.stdout}\n{proc.stderr}",
            )

            logged_calls = [
                line.strip()
                for line in log_file.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertGreaterEqual(
                len(logged_calls),
                9,
                "Expected 5 bq query calls and 4 bq update --set_label calls",
            )

            for call in logged_calls:
                self.assertIn("--project_id=pinned-proj-999", call)
                self.assertIn("--location=us-east4", call)
                for hook_bin in (GUARDRAIL_HOOK, PRE_COMMAND_HOOK):
                    resp = self._invoke_hook(
                        "run_command",
                        {"CommandLine": call},
                        hook_bin=hook_bin,
                    )
                    self.assertEqual(
                        resp.get("decision"),
                        "allow",
                        f"Hook {hook_bin.name} blocked valid skill command: {call} -> {resp}",
                    )

        # Also validate every generated SQL statement via BigQuery MCP tool payloads
        refresh_artifacts = execute_refresh_for_period(
            period_label="2026-W44",
            cutoff_date="2026-11-07",
            dataset_dir=MOCK_DATASET_DIR,
            project_id="pinned-proj-999",
            region="us-east4",
        )
        for step_name, sql_text in refresh_artifacts["sql_statements"].items():
            self.assertIn("pinned-proj-999", sql_text)
            for hook_bin in (GUARDRAIL_HOOK, PRE_COMMAND_HOOK):
                resp = self._invoke_hook(
                    "execute_sql",
                    {
                        "projectId": "pinned-proj-999",
                        "location": "us-east4",
                        "sql": sql_text,
                    },
                    hook_bin=hook_bin,
                )
                self.assertEqual(
                    resp.get("decision"),
                    "allow",
                    f"Hook {hook_bin.name} blocked SQL step {step_name}: {resp}",
                )

        # Verify placeholder demo.env.example fails fast
        bad_proc = subprocess.run(
            [str(REFRESH_BIN), "--env", str(WORKTREE_ROOT / "demo.env.example")],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(bad_proc.returncode, 0)
        self.assertIn("[FAIL]", bad_proc.stderr)

    def test_glossary_compliance_on_all_issue_18_files(self) -> None:
        """All Issue #18 files must comply with GLOSSARY.md vocabulary."""
        checked_files = [
            ".agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md",
            ".agents/plugins/ds-command-center/plugin.json",
            "lib/cohort_forecast_refresh.py",
            "bin/run-cohort-forecast-refresh",
            "tests/test_cohort_forecast_refresh_skill.py",
        ]
        proc = subprocess.run(
            ["node", "bin/check-glossary.js", *checked_files],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"check-glossary.js failed:\n{proc.stdout}\n{proc.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
