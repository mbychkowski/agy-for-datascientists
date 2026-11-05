"""Tests for the shared Pinning shell module (bin/lib/pinning.sh) and JSON helper."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import setup_preflight_test_env

WORKTREE_ROOT = Path(__file__).resolve().parents[1]
PINNING_SH = WORKTREE_ROOT / "bin" / "lib" / "pinning.sh"


def _run_bash(
    script: str,
    *,
    env: dict[str, str] | None = None,
    strict_e: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a bash snippet that sources bin/lib/pinning.sh."""
    header = "set -euo pipefail" if strict_e else "set -uo pipefail"
    full_script = f'{header}\nsource "{PINNING_SH}"\n{script}\n'
    return subprocess.run(
        ["bash", "-c", full_script],
        cwd=WORKTREE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


class TestPinningModuleFile(unittest.TestCase):
    def test_pinning_sh_exists_and_is_non_executable_with_shellcheck_directive(
        self,
    ) -> None:
        """bin/lib/pinning.sh must exist, not be executable, and start with '# shellcheck shell=bash'."""
        self.assertTrue(PINNING_SH.is_file(), f"Missing {PINNING_SH}")
        self.assertFalse(
            os.access(PINNING_SH, os.X_OK),
            "bin/lib/pinning.sh is a sourced library and must not have the executable bit set",
        )
        first_line = PINNING_SH.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first_line, "# shellcheck shell=bash")


class TestPinnedLoadEnv(unittest.TestCase):
    def test_missing_env_file_reports_exact_fail_message_and_returns_nonzero(
        self,
    ) -> None:
        """pinned_load_env must fail with '[FAIL] Environment file not found: <path>' and return 1 without exiting caller."""
        missing_path = "/tmp/nonexistent-demo-env-046.env"
        proc = _run_bash(
            f"""
if pinned_load_env "{missing_path}"; then
  echo "UNEXPECTED_SUCCESS"
  exit 0
else
  rc=$?
  echo "RETURNED_NONZERO:$rc"
  exit "$rc"
fi
""",
            strict_e=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("RETURNED_NONZERO:1", proc.stdout)
        self.assertIn(
            f"[FAIL] Environment file not found: {missing_path}",
            proc.stderr,
        )

    def test_placeholder_or_missing_project_and_region_rejected(self) -> None:
        """pinned_load_env and pinned_require_project_region must reject unset or 'your-' PROJECT_ID and REGION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)

            bad_proj = tmp / "bad_proj.env"
            bad_proj.write_text(
                'PROJECT_ID="your-gcp-project-id"\nREGION="us-central1"\n',
                encoding="utf-8",
            )
            proc1 = _run_bash(f'pinned_load_env "{bad_proj}"')
            self.assertNotEqual(proc1.returncode, 0)
            self.assertIn("[FAIL]", proc1.stderr)
            self.assertIn("PROJECT_ID", proc1.stderr)

            bad_region = tmp / "bad_region.env"
            bad_region.write_text(
                'PROJECT_ID="demo-proj-123"\nREGION="your-gcp-region"\n',
                encoding="utf-8",
            )
            proc2 = _run_bash(f'pinned_load_env "{bad_region}"')
            self.assertNotEqual(proc2.returncode, 0)
            self.assertIn("[FAIL]", proc2.stderr)
            self.assertIn("REGION", proc2.stderr)

            # Preflight guard function re-validates already-loaded vars without reloading file
            proc3 = _run_bash(
                'PROJECT_ID="demo-proj-123"\nREGION=""\npinned_require_project_region'
            )
            self.assertNotEqual(proc3.returncode, 0)
            self.assertIn("[FAIL]", proc3.stderr)
            self.assertIn("REGION", proc3.stderr)

    def test_valid_env_loads_vars_resolves_repo_root_and_applies_dataset_location(
        self,
    ) -> None:
        """pinned_load_env must export PROJECT_ID/REGION, set REPO_ROOT, and apply DATASET_LOCATION unless CLI_DATASET_SET=true."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "demo.env"
            env_file.write_text(
                'PROJECT_ID="pinned-proj-46"\n'
                'REGION="us-east4"\n'
                'DATASET_LOCATION="gs://custom-dataset-bucket/v2"\n',
                encoding="utf-8",
            )

            proc = _run_bash(
                f"""
DATASET_DIR="default/dir"
CLI_DATASET_SET=false
pinned_load_env "{env_file}"
echo "PROJ=$PROJECT_ID"
echo "REG=$REGION"
echo "ROOT=$REPO_ROOT"
echo "DS=$DATASET_DIR"
"""
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("PROJ=pinned-proj-46", proc.stdout)
            self.assertIn("REG=us-east4", proc.stdout)
            self.assertIn(f"ROOT={WORKTREE_ROOT}", proc.stdout)
            self.assertIn("DS=gs://custom-dataset-bucket/v2", proc.stdout)

            # When CLI_DATASET_SET=true, DATASET_DIR must not be overwritten
            proc_cli = _run_bash(
                f"""
DATASET_DIR="/cli/explicit/dir"
CLI_DATASET_SET=true
pinned_load_env "{env_file}"
echo "DS=$DATASET_DIR"
"""
            )
            self.assertEqual(proc_cli.returncode, 0, proc_cli.stderr)
            self.assertIn("DS=/cli/explicit/dir", proc_cli.stdout)


class TestPinnedBqAndLabel(unittest.TestCase):
    def test_pinned_bq_fails_when_bq_missing_from_path(self) -> None:
        """pinned_bq must report [FAIL] and return 1 when bq is not on PATH."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="pinned-proj-46",
                region="us-east4",
            )
            bin_dir = Path(tmpdir) / "bin"
            (bin_dir / "bq").unlink()
            proc = _run_bash(
                f'pinned_load_env "{env_file}"\nPATH="{bin_dir}" pinned_bq show "pinned-proj-46:raw.hospital_reference"',
                env=env,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("[FAIL]", proc.stderr)
            self.assertIn("bq", proc.stderr)

    def test_pinned_bq_injects_project_and_location_and_forwards_exit_code(
        self,
    ) -> None:
        """pinned_bq must inject --project_id and --location and preserve bq exit status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="pinned-proj-46",
                region="us-east4",
            )
            proc = _run_bash(
                f"""
pinned_load_env "{env_file}"
pinned_bq show "pinned-proj-46:ops._preflight_hello_test"
pinned_bq rm -f -t "pinned-proj-46:ops._preflight_hello_test"
pinned_bq query --use_legacy_sql=false "SELECT 1"
""",
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            calls = log_file.read_text(encoding="utf-8")
            self.assertIn(
                "bq show --project_id=pinned-proj-46 --location=us-east4 pinned-proj-46:ops._preflight_hello_test",
                calls,
            )
            self.assertIn(
                "bq rm -f -t --project_id=pinned-proj-46 --location=us-east4 pinned-proj-46:ops._preflight_hello_test",
                calls,
            )
            self.assertIn(
                "bq query --use_legacy_sql=false --project_id=pinned-proj-46 --location=us-east4 SELECT 1",
                calls,
            )

            # Verify non-zero exit code propagation
            env_fail, env_vars_fail, _ = setup_preflight_test_env(
                tmpdir,
                project_id="pinned-proj-46",
                region="us-east4",
                bq_show_fails=True,
            )
            proc_fail = _run_bash(
                f'pinned_load_env "{env_fail}"\npinned_bq show "pinned-proj-46:raw.missing"',
                env=env_vars_fail,
            )
            self.assertNotEqual(proc_fail.returncode, 0)

    def test_pinned_label_applies_demo_true_label_and_normalizes_table_ref(
        self,
    ) -> None:
        """pinned_label must apply demo:true label whether passed dataset.table or project:dataset.table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="pinned-proj-46",
                region="us-east4",
                dataset_tables={"features": {"t1": {}, "t2": {}}},
            )
            proc = _run_bash(
                f"""
pinned_load_env "{env_file}"
pinned_label "features.t1"
pinned_label "pinned-proj-46:features.t2"
""",
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            calls = log_file.read_text(encoding="utf-8")
            self.assertIn(
                "bq update --set_label demo:true --project_id=pinned-proj-46 --location=us-east4 pinned-proj-46:features.t1",
                calls,
            )
            self.assertIn(
                "bq update --set_label demo:true --project_id=pinned-proj-46 --location=us-east4 pinned-proj-46:features.t2",
                calls,
            )


class TestPinnedStorageAndDataproc(unittest.TestCase):
    def test_pinned_storage_injects_project_flag(self) -> None:
        """pinned_storage must inject --project=${PROJECT_ID} for cp, ls, and buckets subcommands."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="pinned-proj-46",
                region="us-east4",
            )
            proc = _run_bash(
                f"""
pinned_load_env "{env_file}"
pinned_storage ls "gs://my-staging-bucket"
pinned_storage buckets create "gs://my-state-bucket" --location="us-east4"
""",
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            calls = log_file.read_text(encoding="utf-8")
            self.assertIn(
                "gcloud storage ls --project=pinned-proj-46 gs://my-staging-bucket",
                calls,
            )
            self.assertIn(
                "gcloud storage buckets create gs://my-state-bucket --project=pinned-proj-46 --location=us-east4",
                calls,
            )

    def test_pinned_dataproc_submit_pins_runtime_flags_and_blocks_service_account(
        self,
    ) -> None:
        """pinned_dataproc_submit must pin runtime 3.0/deps-bucket/subnet/project/region, support --async, and reject --service-account (ADR 0002)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                project_id="pinned-proj-46",
                region="us-east4",
            )
            proc = _run_bash(
                f"""
pinned_load_env "{env_file}"
STAGING_BUCKET="pinned-staging-46"
pinned_dataproc_submit "pipelines/pipeline_clean.py" "batch-sync-1" -- --project_id "$PROJECT_ID" --region "$REGION"
pinned_dataproc_submit --async "pipelines/pipeline_v1.py" "batch-async-2" -- --project_id "$PROJECT_ID"
pinned_dataproc_describe "batch-sync-1" --format="value(state)"
pinned_dataproc_delete "batch-sync-1"
""",
                env=env,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            calls = log_file.read_text(encoding="utf-8")
            self.assertIn(
                "gcloud dataproc batches submit pyspark pipelines/pipeline_clean.py "
                "--project=pinned-proj-46 --region=us-east4 --batch=batch-sync-1 "
                "--version=3.0 --deps-bucket=gs://pinned-staging-46 --subnet=demo-dataproc-subnet "
                "-- --project_id pinned-proj-46 --region us-east4",
                calls,
            )
            self.assertIn(
                "gcloud dataproc batches submit pyspark pipelines/pipeline_v1.py "
                "--project=pinned-proj-46 --region=us-east4 --batch=batch-async-2 "
                "--version=3.0 --deps-bucket=gs://pinned-staging-46 --subnet=demo-dataproc-subnet --async "
                "-- --project_id pinned-proj-46",
                calls,
            )
            self.assertIn(
                "gcloud dataproc batches describe batch-sync-1 --project=pinned-proj-46 --region=us-east4 --format=value(state)",
                calls,
            )
            self.assertIn(
                "gcloud dataproc batches delete batch-sync-1 --project=pinned-proj-46 --region=us-east4 --quiet",
                calls,
            )

            # Reject --service-account before gcloud is ever invoked (ADR 0002)
            log_file.write_text("", encoding="utf-8")
            proc_sa = _run_bash(
                f"""
pinned_load_env "{env_file}"
pinned_dataproc_submit --service-account=sa@proj.iam.gserviceaccount.com "pipelines/pipeline_v1.py" "batch-bad"
""",
                env=env,
            )
            self.assertNotEqual(proc_sa.returncode, 0)
            self.assertIn("[FAIL]", proc_sa.stderr)
            self.assertEqual(log_file.read_text(encoding="utf-8").strip(), "")

            # Reject placeholder STAGING_BUCKET
            proc_bad_bucket = _run_bash(
                f"""
pinned_load_env "{env_file}"
STAGING_BUCKET="your-staging-bucket"
pinned_dataproc_submit "pipelines/pipeline_v1.py" "batch-bad-bucket"
""",
                env=env,
            )
            self.assertNotEqual(proc_bad_bucket.returncode, 0)
            self.assertIn("[FAIL]", proc_bad_bucket.stderr)
            self.assertIn("STAGING_BUCKET", proc_bad_bucket.stderr)


class TestPinnedBqJsonReader(unittest.TestCase):
    def test_bq_json_reader_handles_noisy_status_lines_multiple_docs_and_invalid_output(
        self,
    ) -> None:
        """pinned_bq_json and lib.bq_json must skip noisy status lines before [ or {, return first valid JSON doc, and fail on non-JSON."""
        # 1. Noisy status lines before JSON (including non-JSON brackets in status lines)
        noisy = (
            "Waiting on bqjob_r123456_000001 ... (2s)\n"
            "[status] Job running in us-central1\n"
            '[{"hospital_id": "H001", "duplicate_groups": 0}]\n'
            '{"trailing_second_doc": true}\n'
        )
        proc1 = _run_bash(
            f"""
pinned_bq_json <<'EOF'
{noisy}
EOF
"""
        )
        self.assertEqual(proc1.returncode, 0, proc1.stderr)
        self.assertEqual(
            proc1.stdout.strip(),
            '[{"hospital_id": "H001", "duplicate_groups": 0}]',
        )

        # 2. Wrapping a pinned_bq command directly
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="pinned-proj-46",
                region="us-east4",
            )
            proc2 = _run_bash(
                f"""
pinned_load_env "{env_file}"
pinned_bq_json show --format=prettyjson "pinned-proj-46:staging.hospital_flu"
""",
                env=env,
            )
            self.assertEqual(proc2.returncode, 0, proc2.stderr)
            self.assertIn('"demo": "true"', proc2.stdout)

        # 3. Output with no JSON document fails non-zero
        proc3 = _run_bash(
            """
pinned_bq_json <<'EOF'
Waiting on bqjob_r999 ...
BigQuery error in query operation: syntax error
EOF
"""
        )
        self.assertNotEqual(proc3.returncode, 0)


def _path_without(tools: set[str], extra_first: Path) -> str:
    """Build a PATH that shadows every system tool except *tools*, with *extra_first* first."""
    shadow = extra_first.parent / "sysbin"
    shadow.mkdir(exist_ok=True)
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        directory = Path(entry)
        if not directory.is_dir():
            continue
        for tool in directory.iterdir():
            link = shadow / tool.name
            if tool.name in tools or link.exists() or link.is_symlink():
                continue
            link.symlink_to(tool)
    return f"{extra_first}{os.pathsep}{shadow}"


class TestPinnedRequireCli(unittest.TestCase):
    def test_reports_each_missing_cli_and_passes_when_all_present(self) -> None:
        """pinned_require_cli must fail with [FAIL] naming a missing CLI and succeed when all are on PATH."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, env, _ = setup_preflight_test_env(tmpdir)
            bin_dir = Path(tmpdir) / "bin"
            (bin_dir / "bq").unlink()
            env["PATH"] = _path_without({"bq"}, bin_dir)
            missing = _run_bash("pinned_require_cli gcloud bq", env=env)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn(
                "[FAIL] bq CLI is not installed or not on PATH", missing.stderr
            )

            present = _run_bash("pinned_require_cli gcloud", env=env)
            self.assertEqual(present.returncode, 0, present.stderr)


class TestWorkstream1RunnersFailFastWithoutBq(unittest.TestCase):
    def test_runners_fail_before_dataproc_submit_when_bq_missing(self) -> None:
        """WS1 runners must reject a missing bq CLI before submitting a Dataproc batch, not at the label step."""
        for runner in ("run-pipeline-v1", "run-pipeline-clean"):
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as tmpdir:
                env_file, env, log_file = setup_preflight_test_env(tmpdir)
                bin_dir = Path(tmpdir) / "bin"
                (bin_dir / "bq").unlink()
                env["PATH"] = _path_without({"bq"}, bin_dir)
                proc = subprocess.run(
                    [str(WORKTREE_ROOT / "bin" / runner), "--env", str(env_file)],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("[FAIL] bq CLI is not installed", proc.stderr)
                calls = (
                    log_file.read_text(encoding="utf-8") if log_file.exists() else ""
                )
                self.assertNotIn("dataproc batches submit", calls)


UNMIGRATED_PINNING_ALLOWLIST: frozenset[str] = frozenset(
    {
        "bin/bootstrap-tf-state",
        "bin/checkpoint",
        "bin/load-raw-ops",
        "bin/load-reveal",
        "bin/preflight",
        "bin/reset",
        "bin/setup",
        "bin/verify-main-end-state",
        "bin/verify-start-point",
    }
)

_FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "direct bq CLI invocation",
        re.compile(
            r"(?<![\w-])(?:bq\s+(?:--project_id|--location|--format|query|show|ls|rm|cp|load|update|mk|head)\b|command\s+-v\s+bq\b)"
        ),
    ),
    (
        "direct gcloud CLI invocation",
        re.compile(
            r"(?<![\w-])(?:gcloud\s+(?:storage|dataproc)\b|command\s+-v\s+gcloud\b)"
        ),
    ),
    (
        "direct source of ENV_FILE or demo.env",
        re.compile(r"(?:^|[;\s])(?:source|\.)\s+[\"']?\$\{?ENV_FILE\}?"),
    ),
    (
        "inline 'your-' placeholder check or missing env message",
        re.compile(r"\*\s*[\"']?your-|Environment file not found:"),
    ),
)


def _scan_script_violations(script_path: Path) -> list[str]:
    violations: list[str] = []
    for lineno, raw_line in enumerate(
        script_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for label, pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(stripped):
                violations.append(f"L{lineno} ({label}): {stripped}")
    return violations


class TestPinningSourceScanGuard(unittest.TestCase):
    def test_bin_scripts_use_pinning_module_unless_allowlisted(self) -> None:
        """Every non-allowlisted bin/* script must use bin/lib/pinning.sh instead of direct bq/gcloud or inline env checks."""
        bin_dir = WORKTREE_ROOT / "bin"
        unexpected: dict[str, list[str]] = {}
        stale_allowlist: list[str] = []

        for path in sorted(bin_dir.iterdir()):
            if not path.is_file():
                continue
            if path.suffix in {".js", ".py"}:
                continue
            rel = f"bin/{path.name}"
            violations = _scan_script_violations(path)
            if rel in UNMIGRATED_PINNING_ALLOWLIST:
                if not violations:
                    stale_allowlist.append(rel)
            elif violations:
                unexpected[rel] = violations

        self.assertEqual(
            unexpected,
            {},
            f"Scripts not on UNMIGRATED_PINNING_ALLOWLIST have unmigrated bq/gcloud/env calls: {unexpected}",
        )
        self.assertEqual(
            stale_allowlist,
            [],
            f"Remove already-migrated scripts from UNMIGRATED_PINNING_ALLOWLIST: {stale_allowlist}",
        )


if __name__ == "__main__":
    unittest.main()
