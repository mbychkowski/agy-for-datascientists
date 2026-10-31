"""Tests for Issue #14: Workstream 2 Start Point (reset ws2, verify ws2, and workstream-2-start branch)."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import (
    RESET_BIN,
    RESET_SYMLINK,
    VERIFY_START_POINT_BIN,
    VERIFY_START_POINT_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
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
        if line.startswith(("bq ", "gcloud ", "agy ")) or not commands:
            commands.append(line)
        else:
            commands[-1] = f"{commands[-1]}\n{line}"
    return commands


class TestWorkstream2StartPoint(unittest.TestCase):
    def test_reset_ws2_lists_plan_asks_confirmation_and_aborts_on_no_or_eof(
        self,
    ) -> None:
        """reset ws2 must list tables to drop and rebuild, ask confirmation, and abort before dropping/modifying on 'n' or empty stdin."""
        initial_tables = {
            "raw": {
                "hospital_reference": {"demo": "true"},
                "hospital_flu_feeds": {"demo": "true"},
                "hospital_flu_feeds_reveal": {"demo": "true"},
            },
            "ops": {
                "pipeline_run_log": {"demo": "true"},
            },
            "staging": {
                "hospital_flu": {"demo": "true"},
                "hospital_flu_clean": {"demo": "true"},
                "ws1_attribution": {"demo": "true"},
            },
            "features": {
                "hospital_seasonal_features": {"demo": "true"},
            },
            "ml": {
                "experiment_trials": {"demo": "true"},
            },
            "checkpoint": {
                "ws1_staging_hospital_flu": {"demo": "true"},
                "ws1_staging_hospital_flu_clean": {"demo": "true"},
            },
        }

        for user_input in ("n\n", ""):
            with (
                self.subTest(user_input=user_input),
                tempfile.TemporaryDirectory() as tmpdir,
            ):
                env_file, env, log_file = setup_preflight_test_env(
                    tmpdir,
                    project_id="demo-proj-123",
                    region="us-central1",
                    dataset_tables=initial_tables,
                )

                proc = subprocess.run(
                    [
                        str(RESET_SYMLINK),
                        "ws2",
                        "--env",
                        str(env_file),
                        "--dataset-dir",
                        str(MOCK_DATASET_DIR),
                    ],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    input=user_input,
                    capture_output=True,
                    text=True,
                    check=False,
                )

                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(
                    "Reset Plan for Workstream 2 (ws2) in project demo-proj-123",
                    proc.stdout,
                )
                self.assertIn("Tables to DROP", proc.stdout)
                self.assertIn(
                    "demo-proj-123:raw.hospital_flu_feeds_reveal", proc.stdout
                )
                self.assertIn("demo-proj-123:staging.ws1_attribution", proc.stdout)
                self.assertIn(
                    "demo-proj-123:features.hospital_seasonal_features", proc.stdout
                )
                self.assertIn("demo-proj-123:ml.experiment_trials", proc.stdout)
                self.assertIn("Tables to REBUILD", proc.stdout)
                self.assertIn("demo-proj-123:staging.hospital_flu", proc.stdout)
                self.assertIn("demo-proj-123:staging.hospital_flu_clean", proc.stdout)
                self.assertIn("Proceed with reset to ws2? [y/N]:", proc.stdout)
                self.assertIn("[ABORT] Reset cancelled by user.", proc.stdout)

                calls = _parse_logged_commands(log_file)
                for call in calls:
                    self.assertNotIn(" rm ", call)
                    self.assertNotIn(" load ", call)
                    self.assertNotIn(" cp ", call)
                    self.assertNotIn(" update ", call)
                    self.assertNotIn("dataproc batches submit", call)

    def test_reset_ws2_drops_live_and_reveal_tables_restores_ws2_and_passes_verify(
        self,
    ) -> None:
        """reset ws2 must drop demo:true live Workstream 2/Reveal tables, preserve non-demo tables, restore ws1 + staging.hospital_flu_clean, and pass verify-start-point ws2."""
        for has_checkpoints, confirm_mode in (
            (True, "stdin_yes"),
            (False, "flag_yes"),
        ):
            with (
                self.subTest(
                    has_checkpoints=has_checkpoints, confirm_mode=confirm_mode
                ),
                tempfile.TemporaryDirectory() as tmpdir,
            ):
                initial_tables = {
                    "raw": {
                        "hospital_reference": {"demo": "true"},
                        "hospital_flu_feeds": {"demo": "true"},
                        "hospital_flu_feeds_reveal": {"demo": "true"},
                        "external_audit_table": {},
                    },
                    "ops": {
                        "pipeline_run_log": {"demo": "true"},
                    },
                    "staging": {
                        "hospital_flu": {"demo": "true"},
                        "hospital_flu_clean": {"demo": "true"},
                        "ws1_attribution": {"demo": "true"},
                        "user_scratch_table": {"owner": "analyst"},
                    },
                    "features": {
                        "hospital_seasonal_features": {"demo": "true"},
                        "non_demo_features": {"demo": "false"},
                    },
                    "ml": {
                        "experiment_trials": {"demo": "true"},
                    },
                    "checkpoint": (
                        {
                            "ws1_staging_hospital_flu": {"demo": "true"},
                            "ws1_staging_hospital_flu_clean": {"demo": "true"},
                        }
                        if has_checkpoints
                        else {}
                    ),
                }

                env_file, env, log_file = setup_preflight_test_env(
                    tmpdir,
                    project_id="demo-proj-123",
                    region="us-central1",
                    dataset_tables=initial_tables,
                )

                cmd = [
                    str(RESET_BIN),
                    "ws2",
                    "--env",
                    str(env_file),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                ]
                stdin_text = "y\n"
                if confirm_mode == "flag_yes":
                    cmd.append("--yes")
                    stdin_text = ""

                proc = subprocess.run(
                    cmd,
                    cwd=WORKTREE_ROOT,
                    env=env,
                    input=stdin_text,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    proc.returncode,
                    0,
                    f"reset ws2 failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
                )
                self.assertIn(
                    "[SKIP] Preserving non-demo table demo-proj-123:raw.external_audit_table",
                    proc.stdout,
                )
                self.assertIn(
                    "[SKIP] Preserving non-demo table demo-proj-123:staging.user_scratch_table",
                    proc.stdout,
                )
                self.assertIn(
                    "[SKIP] Preserving non-demo table demo-proj-123:features.non_demo_features",
                    proc.stdout,
                )
                self.assertIn(
                    "[PASS] Workstream 2 Start Point (ws2) verified", proc.stdout
                )
                self.assertIn(
                    "[PASS] Reset to Workstream 2 Start Point (ws2) complete and verified.",
                    proc.stdout,
                )

                calls = _parse_logged_commands(log_file)

                # Live-created and Reveal tables were dropped via bq rm -f -t
                for dropped_tbl in (
                    "demo-proj-123:raw.hospital_flu_feeds_reveal",
                    "demo-proj-123:staging.ws1_attribution",
                    "demo-proj-123:features.hospital_seasonal_features",
                    "demo-proj-123:ml.experiment_trials",
                ):
                    self.assertTrue(
                        any("rm -f -t" in c and dropped_tbl in c for c in calls),
                        f"Expected bq rm -f -t for {dropped_tbl}",
                    )

                # staging.hospital_flu_clean is a core ws2 table so it is rebuilt, not dropped
                self.assertFalse(
                    any(
                        "rm -f -t" in c
                        and "demo-proj-123:staging.hospital_flu_clean" in c
                        for c in calls
                    ),
                    "staging.hospital_flu_clean is in ws2 CORE_TABLES and must be rebuilt rather than dropped",
                )

                # Both staging.hospital_flu and staging.hospital_flu_clean restored via Checkpoint swap or Dataproc fallback
                if has_checkpoints:
                    self.assertTrue(
                        any(
                            "cp -f" in c
                            and "demo-proj-123:checkpoint.ws1_staging_hospital_flu" in c
                            and "demo-proj-123:staging.hospital_flu" in c
                            for c in calls
                        )
                    )
                    self.assertTrue(
                        any(
                            "cp -f" in c
                            and "demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean"
                            in c
                            and "demo-proj-123:staging.hospital_flu_clean" in c
                            for c in calls
                        )
                    )
                else:
                    self.assertTrue(
                        any(
                            "gcloud dataproc batches submit pyspark" in c
                            and "pipeline_v1.py" in c
                            for c in calls
                        )
                    )
                    self.assertTrue(
                        any(
                            "gcloud dataproc batches submit pyspark" in c
                            and "pipeline_clean.py" in c
                            for c in calls
                        )
                    )

                final_state = json.loads(
                    (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    final_state["raw"],
                    {
                        "hospital_reference": {"demo": "true"},
                        "hospital_flu_feeds": {"demo": "true"},
                        "external_audit_table": {},
                    },
                )
                self.assertEqual(
                    final_state["ops"],
                    {"pipeline_run_log": {"demo": "true"}},
                )
                self.assertEqual(
                    final_state["staging"],
                    {
                        "hospital_flu": {"demo": "true"},
                        "hospital_flu_clean": {"demo": "true"},
                        "user_scratch_table": {"owner": "analyst"},
                    },
                )
                self.assertEqual(
                    final_state["features"],
                    {"non_demo_features": {"demo": "false"}},
                )
                self.assertEqual(final_state["ml"], {})

        # Verify reset ws2 refuses to overwrite a non-demo staging.hospital_flu_clean
        with tempfile.TemporaryDirectory() as tmpdir:
            unsafe_tables = {
                "raw": {
                    "hospital_reference": {"demo": "true"},
                    "hospital_flu_feeds": {"demo": "true"},
                },
                "ops": {"pipeline_run_log": {"demo": "true"}},
                "staging": {
                    "hospital_flu": {"demo": "true"},
                    "hospital_flu_clean": {},  # missing demo:true!
                },
                "features": {},
                "ml": {},
                "checkpoint": {},
            }
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables=unsafe_tables,
            )
            proc = subprocess.run(
                [str(RESET_BIN), "ws2", "--yes", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(
                "[FAIL] Refusing to overwrite non-demo table demo-proj-123:staging.hospital_flu_clean",
                proc.stderr,
            )
            calls = _parse_logged_commands(log_file)
            for call in calls:
                self.assertNotIn(" load ", call)
                self.assertNotIn(" rm ", call)

    def test_verify_start_point_ws2_is_readonly_and_passes_guardrail_hook(self) -> None:
        """verify-start-point ws2 must issue only read-only bq commands that are allowed by guardrail-hook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
            )

            proc = subprocess.run(
                [str(VERIFY_START_POINT_SYMLINK), "ws2", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                f"verify-start-point ws2 failed:\n{proc.stdout}\n{proc.stderr}",
            )
            self.assertIn("[PASS] Workstream 2 Start Point (ws2) verified", proc.stdout)

            calls = _parse_logged_commands(log_file)
            self.assertGreaterEqual(len(calls), 6)
            self.assertTrue(
                any(
                    "bq show" in c and "demo-proj-123:staging.hospital_flu_clean" in c
                    for c in calls
                )
            )
            self.assertTrue(
                any(
                    "bq query" in c
                    and "clean_duplicate_groups" in c
                    and "clean_positivity_populated_rows" in c
                    for c in calls
                )
            )

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
                    f"Guardrail hook blocked verify-start-point ws2 command: {cmd_line} -> {decision}",
                )

    def test_verify_start_point_ws2_fails_on_missing_clean_table_label_duplicates_or_missing_positivity(
        self,
    ) -> None:
        """verify-start-point ws2 must fail when staging.hospital_flu_clean is missing, lacks demo:true, has duplicates, or has unpopulated Positivity."""
        failure_cases: list[tuple[dict[str, Any], str]] = [
            (
                {"ws1_missing_table": "staging.hospital_flu_clean"},
                "Required Workstream 2 table missing: demo-proj-123:staging.hospital_flu_clean",
            ),
            (
                {"ws1_missing_label": "staging.hospital_flu_clean"},
                "Table demo-proj-123:staging.hospital_flu_clean is missing required label demo:true",
            ),
            (
                {"ws2_clean_rows": 0},
                "Clean staging table staging.hospital_flu_clean has 0 rows",
            ),
            (
                {"ws2_clean_duplicates": 3},
                "Clean staging table staging.hospital_flu_clean has 3 duplicate (hospital_id, feed_date) groups",
            ),
            (
                {"ws2_clean_missing_positivity": 5},
                "Clean staging table staging.hospital_flu_clean has unpopulated Positivity",
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
                    [str(VERIFY_START_POINT_BIN), "ws2", "--env", str(env_file)],
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

    def test_workstream_2_start_follows_workstream_1_start_linearly_without_ws2_reference_answers(
        self,
    ) -> None:
        """workstream-2-start (or HEAD before branch cut) must follow workstream-1-start in one linear history and contain no Workstream 2 reference answers."""
        ws1_ref = None
        for candidate in ("workstream-1-start", "origin/workstream-1-start"):
            chk = subprocess.run(
                ["git", "rev-parse", "--verify", candidate],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if chk.returncode == 0:
                ws1_ref = candidate
                break

        self.assertIsNotNone(
            ws1_ref,
            "Expected workstream-1-start (or origin/workstream-1-start) branch to exist",
        )

        ws2_ref = "HEAD"
        for candidate in ("workstream-2-start", "origin/workstream-2-start"):
            chk = subprocess.run(
                ["git", "rev-parse", "--verify", candidate],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            if chk.returncode == 0:
                ws2_ref = candidate
                break

        # 1. Verify ws1_ref is an ancestor of ws2_ref
        anc_proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", str(ws1_ref), ws2_ref],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            anc_proc.returncode,
            0,
            f"{ws1_ref} must be an ancestor of {ws2_ref}",
        )

        # 2. Verify linear history (no merge commits between ws1_ref and ws2_ref)
        merges_proc = subprocess.run(
            ["git", "rev-list", "--merges", f"{ws1_ref}..{ws2_ref}"],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(
            merges_proc.stdout.strip(),
            "",
            f"Expected one linear history between {ws1_ref} and {ws2_ref}, found merge commits: {merges_proc.stdout}",
        )

        # 3. Verify no Workstream 2 reference answers exist on ws2_ref
        ls_proc = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ws2_ref],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        ws2_files = set(ls_proc.stdout.splitlines())
        for rel_path in ws2_files:
            self.assertFalse(
                rel_path.startswith(
                    (
                        "checkpoints/manifest.d/ws2_",
                        "sql/ws2_",
                        "sql/features_",
                        "sql/ml_",
                        "lib/ws2_",
                    )
                ),
                f"Workstream 2 reference answer file {rel_path} must NOT exist on {ws2_ref}",
            )


if __name__ == "__main__":
    unittest.main()
