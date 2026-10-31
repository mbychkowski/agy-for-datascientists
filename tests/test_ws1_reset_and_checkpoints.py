"""Tests for Issue #11: Safe reset to ws1 and one-command Checkpoint swap."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (
    CHECKPOINT_BIN,
    CHECKPOINT_SYMLINK,
    RESET_BIN,
    RESET_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
MANIFEST_DIR = WORKTREE_ROOT / "checkpoints" / "manifest.d"


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


class TestWs1ResetAndCheckpoints(unittest.TestCase):
    def test_executables_and_manifest_exist(self) -> None:
        """bin/reset, reset symlink, bin/checkpoint, checkpoint symlink, and ws1_pipeline_v1.json must exist."""
        for path in (
            RESET_BIN,
            RESET_SYMLINK,
            CHECKPOINT_BIN,
            CHECKPOINT_SYMLINK,
        ):
            self.assertTrue(path.exists(), f"{path} must exist")
            self.assertTrue(os.access(path, os.X_OK), f"{path} must be executable")

        ws1_manifest = MANIFEST_DIR / "ws1_pipeline_v1.json"
        self.assertTrue(ws1_manifest.exists(), "ws1_pipeline_v1.json must exist")
        data = json.loads(ws1_manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["id"], "ws1_pipeline_v1")
        self.assertEqual(data["workstream"], "ws1")
        self.assertEqual(data["source_table"], "checkpoint.ws1_staging_hospital_flu")
        self.assertEqual(data["target_table"], "staging.hospital_flu")

    def test_reset_ws1_lists_plan_asks_confirmation_and_aborts_on_no_or_eof(
        self,
    ) -> None:
        """reset ws1 must list tables to drop and rebuild, ask confirmation, and abort before dropping/modifying on 'n' or empty stdin."""
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
            },
            "features": {
                "hospital_seasonal_features": {"demo": "true"},
            },
            "ml": {},
            "checkpoint": {
                "ws1_staging_hospital_flu": {"demo": "true"},
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
                        "ws1",
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
                self.assertIn("Tables to DROP", proc.stdout)
                self.assertIn(
                    "demo-proj-123:raw.hospital_flu_feeds_reveal", proc.stdout
                )
                self.assertIn("demo-proj-123:staging.hospital_flu_clean", proc.stdout)
                self.assertIn(
                    "demo-proj-123:features.hospital_seasonal_features", proc.stdout
                )
                self.assertIn("Tables to REBUILD", proc.stdout)
                self.assertIn("demo-proj-123:staging.hospital_flu", proc.stdout)
                self.assertIn("Proceed with reset to ws1? [y/N]:", proc.stdout)
                self.assertIn("[ABORT] Reset cancelled by user.", proc.stdout)

                calls = _parse_logged_commands(log_file)
                for call in calls:
                    self.assertNotIn(" rm ", call)
                    self.assertNotIn(" load ", call)
                    self.assertNotIn(" cp ", call)
                    self.assertNotIn(" update ", call)
                    self.assertNotIn("dataproc batches submit", call)

    def test_reset_ws1_drops_live_and_reveal_tables_restores_ws1_and_passes_verify(
        self,
    ) -> None:
        """reset ws1 must drop demo:true live/Reveal tables, reload raw & ops, restore staging.hospital_flu, and pass verify-start-point ws1."""
        for has_checkpoint, confirm_mode in (
            (True, "stdin_yes"),
            (False, "flag_yes"),
        ):
            with (
                self.subTest(has_checkpoint=has_checkpoint, confirm_mode=confirm_mode),
                tempfile.TemporaryDirectory() as tmpdir,
            ):
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
                    },
                    "features": {
                        "hospital_seasonal_features": {"demo": "true"},
                    },
                    "ml": {
                        "experiment_trials": {"demo": "true"},
                    },
                    "checkpoint": (
                        {"ws1_staging_hospital_flu": {"demo": "true"}}
                        if has_checkpoint
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
                    "ws1",
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
                    f"reset ws1 failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
                )
                self.assertIn(
                    "[PASS] Workstream 1 Start Point (ws1) verified", proc.stdout
                )
                self.assertIn(
                    "[PASS] Reset to Workstream 1 Start Point (ws1) complete and verified.",
                    proc.stdout,
                )

                calls = _parse_logged_commands(log_file)

                # Live-created and Reveal tables were dropped via bq rm -f -t
                for dropped_tbl in (
                    "demo-proj-123:raw.hospital_flu_feeds_reveal",
                    "demo-proj-123:staging.hospital_flu_clean",
                    "demo-proj-123:features.hospital_seasonal_features",
                    "demo-proj-123:ml.experiment_trials",
                ):
                    self.assertTrue(
                        any("rm -f -t" in c and dropped_tbl in c for c in calls),
                        f"Expected bq rm -f -t for {dropped_tbl}",
                    )

                # Raw and ops tables were reloaded and labelled demo:true
                for core_raw_ops in (
                    "demo-proj-123:raw.hospital_reference",
                    "demo-proj-123:raw.hospital_flu_feeds",
                    "demo-proj-123:ops.pipeline_run_log",
                ):
                    self.assertTrue(
                        any("load --replace" in c and core_raw_ops in c for c in calls),
                        f"Expected bq load --replace for {core_raw_ops}",
                    )
                    self.assertTrue(
                        any(
                            "update --set_label demo:true" in c and core_raw_ops in c
                            for c in calls
                        ),
                        f"Expected demo:true label on {core_raw_ops}",
                    )

                # staging.hospital_flu restored via Checkpoint swap or Pipeline v1
                if has_checkpoint:
                    self.assertTrue(
                        any(
                            "cp -f" in c
                            and "demo-proj-123:checkpoint.ws1_staging_hospital_flu" in c
                            and "demo-proj-123:staging.hospital_flu" in c
                            for c in calls
                        ),
                        "Expected bq cp -f from checkpoint.ws1_staging_hospital_flu to staging.hospital_flu",
                    )
                else:
                    self.assertTrue(
                        any(
                            "gcloud dataproc batches submit pyspark" in c
                            and "pipeline_v1.py" in c
                            for c in calls
                        ),
                        "Expected Pipeline v1 Dataproc batch when checkpoint table is absent",
                    )

                # Inspect final state in bq_tables.json
                final_state = json.loads(
                    (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
                )
                self.assertEqual(
                    final_state["raw"],
                    {
                        "hospital_reference": {"demo": "true"},
                        "hospital_flu_feeds": {"demo": "true"},
                    },
                )
                self.assertEqual(
                    final_state["ops"],
                    {"pipeline_run_log": {"demo": "true"}},
                )
                self.assertEqual(
                    final_state["staging"],
                    {"hospital_flu": {"demo": "true"}},
                )
                self.assertEqual(final_state["features"], {})
                self.assertEqual(final_state["ml"], {})

    def test_reset_ws1_preserves_non_demo_tables_and_never_touches_checkpoint_or_infra(
        self,
    ) -> None:
        """reset ws1 must preserve non-demo tables, fail fast if a core table lacks demo:true, and never drop/mutate checkpoint or buckets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            initial_tables = {
                "raw": {
                    "hospital_reference": {"demo": "true"},
                    "hospital_flu_feeds": {"demo": "true"},
                    "external_audit_table": {},
                },
                "ops": {
                    "pipeline_run_log": {"demo": "true"},
                },
                "staging": {
                    "hospital_flu": {"demo": "true"},
                    "hospital_flu_clean": {"demo": "true"},
                    "user_scratch_table": {"owner": "analyst"},
                },
                "features": {
                    "non_demo_feature_store": {"demo": "false"},
                },
                "ml": {},
                "checkpoint": {
                    "ws1_staging_hospital_flu": {"demo": "true"},
                    "ws1_clean_hospital_flu": {"demo": "true"},
                },
                "other_dataset": {
                    "unrelated_table": {"demo": "true"},
                },
            }

            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables=initial_tables,
            )

            proc = subprocess.run(
                [
                    str(RESET_SYMLINK),
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
                proc.returncode,
                0,
                f"reset ws1 failed:\n{proc.stdout}\n{proc.stderr}",
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
                "[SKIP] Preserving non-demo table demo-proj-123:features.non_demo_feature_store",
                proc.stdout,
            )

            calls = _parse_logged_commands(log_file)
            for preserved in (
                "raw.external_audit_table",
                "staging.user_scratch_table",
                "features.non_demo_feature_store",
                "other_dataset",
                "checkpoint.ws1_staging_hospital_flu",
                "checkpoint.ws1_clean_hospital_flu",
            ):
                self.assertFalse(
                    any("rm -f -t" in c and preserved in c for c in calls),
                    f"Must never drop {preserved}",
                )

            # Never lists checkpoint or non-demo datasets, and never touches buckets or terraform
            for call in calls:
                self.assertFalse(" ls " in call and "checkpoint" in call)
                self.assertFalse(" ls " in call and "other_dataset" in call)
                self.assertNotIn("terraform", call)
                self.assertNotIn("gsutil", call)
                self.assertNotIn("gcloud storage", call)

            final_state = json.loads(
                (Path(tmpdir) / "bq_tables.json").read_text(encoding="utf-8")
            )
            self.assertIn("external_audit_table", final_state["raw"])
            self.assertIn("user_scratch_table", final_state["staging"])
            self.assertNotIn("hospital_flu_clean", final_state["staging"])
            self.assertIn("non_demo_feature_store", final_state["features"])
            self.assertEqual(
                final_state["checkpoint"],
                {
                    "ws1_staging_hospital_flu": {"demo": "true"},
                    "ws1_clean_hospital_flu": {"demo": "true"},
                },
            )
            self.assertEqual(
                final_state["other_dataset"],
                {"unrelated_table": {"demo": "true"}},
            )

        # Also verify that if a core table exists WITHOUT demo:true, reset refuses to overwrite it
        with tempfile.TemporaryDirectory() as tmpdir:
            unsafe_core_tables = {
                "raw": {
                    "hospital_reference": {},  # missing demo:true!
                    "hospital_flu_feeds": {"demo": "true"},
                },
                "ops": {"pipeline_run_log": {"demo": "true"}},
                "staging": {"hospital_flu": {"demo": "true"}},
                "features": {},
                "ml": {},
                "checkpoint": {},
            }
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables=unsafe_core_tables,
            )
            proc = subprocess.run(
                [str(RESET_BIN), "ws1", "--yes", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(
                "[FAIL] Refusing to overwrite non-demo table demo-proj-123:raw.hospital_reference",
                proc.stderr,
            )
            calls = _parse_logged_commands(log_file)
            for call in calls:
                self.assertNotIn(" load ", call)
                self.assertNotIn(" rm ", call)

    def test_checkpoint_list_swap_build_and_dynamic_registration(self) -> None:
        """checkpoint CLI must list registered Checkpoints, swap from checkpoint into target with demo:true, and discover new descriptors without code changes."""
        # 1. List registered Checkpoints using the committed manifest directory
        list_proc = subprocess.run(
            [str(CHECKPOINT_SYMLINK), "--list"],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(list_proc.returncode, 0, list_proc.stderr)
        self.assertIn("ws1_pipeline_v1", list_proc.stdout)
        self.assertIn(
            "checkpoint.ws1_staging_hospital_flu -> staging.hospital_flu",
            list_proc.stdout,
        )

        # 2. Swap ws1_pipeline_v1 and dynamically register a new Checkpoint descriptor
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_manifest_dir = Path(tmpdir) / "manifest.d"
            custom_manifest_dir.mkdir(parents=True, exist_ok=True)
            for existing_json in MANIFEST_DIR.glob("*.json"):
                (custom_manifest_dir / existing_json.name).write_text(
                    existing_json.read_text(encoding="utf-8"),
                    encoding="utf-8",
                )

            # Drop in a new Checkpoint descriptor (simulating later tickets #12/#13/#15/#16)
            (custom_manifest_dir / "ws1_deduped_staging.json").write_text(
                json.dumps(
                    {
                        "id": "ws1_deduped_staging",
                        "workstream": "ws1",
                        "description": "Deduplicated staging table for Workstream 1",
                        "source_table": "checkpoint.ws1_staging_hospital_flu_clean",
                        "target_table": "staging.hospital_flu_clean",
                    }
                ),
                encoding="utf-8",
            )

            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                region="us-central1",
                dataset_tables={
                    "raw": {},
                    "ops": {},
                    "staging": {},
                    "features": {},
                    "ml": {},
                    "checkpoint": {
                        "ws1_staging_hospital_flu": {"demo": "true"},
                        "ws1_staging_hospital_flu_clean": {"demo": "true"},
                    },
                },
            )
            env["CHECKPOINT_MANIFEST_DIR"] = str(custom_manifest_dir)

            # --list discovers both Checkpoints without changing bin/checkpoint
            dyn_list = subprocess.run(
                [str(CHECKPOINT_BIN), "list"],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(dyn_list.returncode, 0)
            self.assertIn("ws1_pipeline_v1", dyn_list.stdout)
            self.assertIn("ws1_deduped_staging", dyn_list.stdout)

            # Swap the newly registered Checkpoint by ID
            swap_proc = subprocess.run(
                [
                    str(CHECKPOINT_SYMLINK),
                    "ws1_deduped_staging",
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
                f"checkpoint swap failed:\n{swap_proc.stdout}\n{swap_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Swapped Checkpoint 'ws1_deduped_staging': demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean -> demo-proj-123:staging.hospital_flu_clean",
                swap_proc.stdout,
            )

            calls = _parse_logged_commands(log_file)
            self.assertTrue(
                any(
                    "cp -f" in c
                    and "demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean" in c
                    and "demo-proj-123:staging.hospital_flu_clean" in c
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

            # Unknown Checkpoint ID fails with available IDs listed
            bad_proc = subprocess.run(
                [str(CHECKPOINT_BIN), "nonexistent_ckpt", "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(bad_proc.returncode, 0)
            self.assertIn(
                "[FAIL] Unknown Checkpoint: nonexistent_ckpt", bad_proc.stderr
            )
            self.assertIn("ws1_pipeline_v1", bad_proc.stderr)
            self.assertIn("ws1_deduped_staging", bad_proc.stderr)

            # --build copies target_table into checkpoint source_table and labels it demo:true
            build_proc = subprocess.run(
                [
                    str(CHECKPOINT_BIN),
                    "--build",
                    "ws1_deduped_staging",
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
                f"checkpoint --build failed:\n{build_proc.stdout}\n{build_proc.stderr}",
            )
            self.assertIn(
                "[PASS] Built Checkpoint 'ws1_deduped_staging': demo-proj-123:checkpoint.ws1_staging_hospital_flu_clean",
                build_proc.stdout,
            )


if __name__ == "__main__":
    unittest.main()
