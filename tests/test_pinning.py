"""Tests for the shared Pinning shell module (bin/lib/pinning.sh) and JSON helper."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import NamedTuple

from tests.helpers import create_demo_env_file, setup_preflight_test_env

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


def _argv_recording_env(tmpdir: str) -> tuple[dict[str, str], Path]:
    """Env whose bq stub writes each argument NUL-terminated to argv.bin, so multi-line SQL survives intact."""
    bin_dir = Path(tmpdir) / "bin"
    bin_dir.mkdir()
    argv_file = Path(tmpdir) / "argv.bin"
    _write_logging_stub(
        bin_dir,
        "bq",
        Path(tmpdir) / "calls.log",
        f'printf "%s\\0" "$@" > "{argv_file}"',
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
            "PROJECT_ID": "pinned-proj-74",
            "REGION": "us-east4",
        }
    )
    return env, argv_file


def _recorded_argv(argv_file: Path) -> list[str]:
    return argv_file.read_text(encoding="utf-8").split("\0")[:-1]


_PINNED_BQ_FLAGS = ("--project_id=pinned-proj-74", "--location=us-east4")


class TestPinnedBqLeadingDashSql(unittest.TestCase):
    def _bq_argv(self, call: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            env, argv_file = _argv_recording_env(tmpdir)
            proc = _run_bash(call, env=env)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return _recorded_argv(argv_file)

    def test_sql_starting_with_comment_reaches_bq_as_the_query(self) -> None:
        """SQL beginning with a '-- comment' line must reach bq as the query after an end-of-flags '--', not as a flag."""
        argv = self._bq_argv(
            "sql=$'-- comment\\nSELECT 1'\n"
            'pinned_bq query --use_legacy_sql=false --format=json "${sql}"'
        )
        self.assertEqual(
            argv,
            [
                "query",
                "--use_legacy_sql=false",
                "--format=json",
                *_PINNED_BQ_FLAGS,
                "--",
                "-- comment\nSELECT 1",
            ],
        )

    def test_single_line_sql_starting_with_comment_marker_is_the_query(self) -> None:
        """A single-line SQL argument such as '-- note' (dash-dash then a space) is query text, not a flag."""
        argv = self._bq_argv('pinned_bq query --use_legacy_sql=false "-- note"')
        self.assertEqual(
            argv,
            ["query", "--use_legacy_sql=false", *_PINNED_BQ_FLAGS, "--", "-- note"],
        )

    def test_caller_end_of_flags_marker_keeps_pinned_flags_before_it(self) -> None:
        """A caller-supplied '--' must end the flags after --project_id/--location, never before them."""
        argv = self._bq_argv(
            'pinned_bq query --use_legacy_sql=false -- "--x\nSELECT 2"'
        )
        self.assertEqual(
            argv,
            [
                "query",
                "--use_legacy_sql=false",
                *_PINNED_BQ_FLAGS,
                "--",
                "--x\nSELECT 2",
            ],
        )

    def test_plain_positionals_get_no_end_of_flags_marker(self) -> None:
        """Ordinary SQL and table refs keep today's argv exactly: no '--' is inserted."""
        argv = self._bq_argv(
            'pinned_bq query --use_legacy_sql=false "SELECT 1"\n'
            'pinned_bq rm -f -t "pinned-proj-74:staging.t"'
        )
        self.assertEqual(
            argv, ["rm", "-f", "-t", *_PINNED_BQ_FLAGS, "pinned-proj-74:staging.t"]
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


class TestWorkstream2RunnersFailFastWithoutBq(unittest.TestCase):
    def test_runners_fail_before_any_work_when_bq_missing(self) -> None:
        """WS2 runners must reject a missing bq CLI right after loading demo.env, before any bq call or local refresh output."""
        for runner, extra in (
            ("run-ws2-cohorts", []),
            ("run-ws2-forecasts", []),
            ("run-cohort-forecast-refresh", ["--output-json", "{tmp}/refresh.json"]),
        ):
            with self.subTest(runner=runner), tempfile.TemporaryDirectory() as tmpdir:
                env_file, env, log_file = setup_preflight_test_env(tmpdir)
                bin_dir = Path(tmpdir) / "bin"
                (bin_dir / "bq").unlink()
                env["PATH"] = _path_without({"bq"}, bin_dir)
                env["RECORDED_RUNTIMES_FILE"] = str(Path(tmpdir) / "runtimes.json")
                env["COHORT_REFRESH_STATE_FILE"] = str(Path(tmpdir) / "state.json")
                proc = subprocess.run(
                    [
                        str(WORKTREE_ROOT / "bin" / runner),
                        "--env",
                        str(env_file),
                        *(arg.format(tmp=tmpdir) for arg in extra),
                    ],
                    cwd=WORKTREE_ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("[FAIL] bq CLI is not installed", proc.stderr)
                self.assertNotIn("bq ", _read_calls(log_file))
                for artefact in ("runtimes.json", "state.json", "refresh.json"):
                    self.assertFalse((Path(tmpdir) / artefact).exists(), artefact)


class TestPinnedGcloudProfileProbes(unittest.TestCase):
    """Module wrappers for preflight's read-only gcloud profile and ADC probes."""

    def _stub_env(self, tmpdir: str, body: str = "") -> tuple[dict[str, str], Path]:
        bin_dir = Path(tmpdir) / "bin"
        bin_dir.mkdir()
        log_file = Path(tmpdir) / "calls.log"
        _write_logging_stub(
            bin_dir,
            "gcloud",
            log_file,
            'echo "env CORE_PROJECT=${CLOUDSDK_CORE_PROJECT-<unset>}'
            " CORE_ACCOUNT=${CLOUDSDK_CORE_ACCOUNT-<unset>}"
            f' COMPUTE_REGION=${{CLOUDSDK_COMPUTE_REGION-<unset>}}" >> "{log_file}"\n'
            + body,
        )
        env = os.environ.copy()
        env.update(
            {
                "PATH": f"{bin_dir}{os.pathsep}{env['PATH']}",
                "PROJECT_ID": "demo-proj-52",
                "REGION": "us-east4",
                "CLOUDSDK_CORE_PROJECT": "shadow-proj",
                "CLOUDSDK_CORE_ACCOUNT": "shadow@example.com",
                "CLOUDSDK_COMPUTE_REGION": "shadow-region",
            }
        )
        return env, log_file

    def test_profile_reads_active_configuration_with_overrides_unset(self) -> None:
        """pinned_gcloud_profile must read the active configuration's property with CLOUDSDK_* overrides unset."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env, log_file = self._stub_env(tmpdir, 'echo "real-value"')
            for prop, field in (
                ("core/project", "properties.core.project"),
                ("compute/region", "properties.compute.region"),
                ("core/account", "properties.core.account"),
            ):
                with self.subTest(prop=prop):
                    log_file.unlink(missing_ok=True)
                    proc = _run_bash(f"pinned_gcloud_profile {prop}", env=env)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stdout.strip(), "real-value")
                    calls = _read_calls(log_file)
                    self.assertIn(
                        "gcloud config configurations list --filter=is_active=true"
                        f" --format=value({field})",
                        calls,
                    )
                    self.assertIn(
                        "env CORE_PROJECT=<unset> CORE_ACCOUNT=<unset>"
                        " COMPUTE_REGION=<unset>",
                        calls,
                    )

    def test_profile_rejects_malformed_property_and_missing_gcloud(self) -> None:
        """pinned_gcloud_profile must fail with [FAIL] on a malformed property or a missing gcloud CLI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env, log_file = self._stub_env(tmpdir)
            for bad in ("", "project", "core/project;rm"):
                with self.subTest(bad=bad):
                    proc = _run_bash(f'pinned_gcloud_profile "{bad}"', env=env)
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertIn("[FAIL] pinned_gcloud_profile", proc.stderr)
            self.assertEqual(_read_calls(log_file), "")

            env["PATH"] = _path_without({"gcloud"}, Path(tmpdir) / "empty")
            missing = _run_bash("pinned_gcloud_profile core/project", env=env)
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("[FAIL] gcloud CLI is not installed", missing.stderr)

    def test_project_lifecycle_state_is_pinned_to_project_id(self) -> None:
        """pinned_project_lifecycle_state must describe the target project billed to PROJECT_ID and forward failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env, log_file = self._stub_env(
                tmpdir,
                'if [[ "$2" == "describe" && "$3" == "gone" ]]; then exit 1; fi\necho ACTIVE',
            )
            ok = _run_bash("pinned_project_lifecycle_state quota-proj", env=env)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(ok.stdout.strip(), "ACTIVE")
            self.assertIn(
                "gcloud projects describe quota-proj --project=demo-proj-52"
                " --format=value(lifecycleState)",
                _read_calls(log_file),
            )

            gone = _run_bash(
                "pinned_project_lifecycle_state gone", env=env, strict_e=False
            )
            self.assertNotEqual(gone.returncode, 0)

            env["PROJECT_ID"] = "your-project"
            log_file.unlink()
            placeholder = _run_bash(
                "pinned_project_lifecycle_state quota-proj", env=env
            )
            self.assertNotEqual(placeholder.returncode, 0)
            self.assertIn("[FAIL] PROJECT_ID", placeholder.stderr)
            self.assertEqual(_read_calls(log_file), "")

    def test_adc_token_check_is_silent_and_forwards_exit_code(self) -> None:
        """pinned_adc_token_ok must run print-access-token silently and return its exit status."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env, log_file = self._stub_env(
                tmpdir, 'echo "secret-token"\necho "warn" >&2\nexit "${TOKEN_RC:-0}"'
            )
            ok = _run_bash("pinned_adc_token_ok", env=env)
            self.assertEqual(ok.returncode, 0, ok.stderr)
            self.assertEqual(ok.stdout + ok.stderr, "")
            self.assertIn(
                "gcloud auth application-default print-access-token",
                _read_calls(log_file),
            )

            env["TOKEN_RC"] = "1"
            bad = _run_bash("pinned_adc_token_ok", env=env, strict_e=False)
            self.assertNotEqual(bad.returncode, 0)
            self.assertNotIn("secret-token", bad.stdout + bad.stderr)


class TestPinnedHasDemoLabel(unittest.TestCase):
    def test_detects_demo_true_label_in_noisy_bq_show_output(self) -> None:
        """pinned_has_demo_label must succeed only when bq show JSON carries labels.demo == 'true'."""
        cases = (
            ('{"id":"t","labels":{"demo":"true"}}', 0),
            ('Waiting on job [status] DONE\\n{"id":"t","labels":{"demo":"true"}}', 0),
            ('{"id":"t","labels":{"demo":"false"}}', 1),
            ('{"id":"t","labels":{}}', 1),
            ('{"id":"t"}', 1),
            ('[{"labels":{"demo":"true"}}]', 1),
            ("not json at all", 1),
            ("", 1),
        )
        for raw, expected_rc in cases:
            with self.subTest(raw=raw):
                proc = _run_bash(
                    f"raw=$'{raw}'\npinned_has_demo_label \"$raw\"",
                    strict_e=False,
                )
                self.assertEqual(proc.returncode, expected_rc, proc.stderr)


class TestPinnedRequireStagingBucket(unittest.TestCase):
    def test_rejects_missing_or_placeholder_bucket_and_accepts_real_bucket(
        self,
    ) -> None:
        """pinned_require_staging_bucket must reject unset or 'your-' STAGING_BUCKET and pass for a real bucket."""
        for value in ("", "your-staging-bucket"):
            with self.subTest(value=value):
                proc = _run_bash(
                    f'STAGING_BUCKET="{value}"\npinned_require_staging_bucket'
                )
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("[FAIL] STAGING_BUCKET is missing", proc.stderr)

        unset = _run_bash("unset STAGING_BUCKET\npinned_require_staging_bucket")
        self.assertNotEqual(unset.returncode, 0)
        self.assertIn("[FAIL] STAGING_BUCKET", unset.stderr)

        ok = _run_bash('STAGING_BUCKET="real-bucket-49"\npinned_require_staging_bucket')
        self.assertEqual(ok.returncode, 0, ok.stderr)


def _run_start_point_script(
    args: list[str], env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(WORKTREE_ROOT / "bin" / args[0]), *args[1:]],
        cwd=WORKTREE_ROOT,
        env=env,
        input="",
        capture_output=True,
        text=True,
        check=False,
    )


class TestStartPointAndCheckpointScriptsFailFast(unittest.TestCase):
    def test_scripts_fail_before_any_bq_call_when_bq_missing(self) -> None:
        """Start Point and Checkpoint scripts must reject a missing bq CLI before issuing any bq call."""
        with tempfile.TemporaryDirectory() as withheld:
            invocations = (
                ["reset", "ws1", "--yes"],
                ["verify-start-point", "ws1"],
                ["verify-main-end-state", "--withheld-dir", withheld],
                ["checkpoint", "ws1_pipeline_v1"],
            )
            for invocation in invocations:
                with (
                    self.subTest(script=invocation[0]),
                    tempfile.TemporaryDirectory() as tmpdir,
                ):
                    env_file, env, log_file = setup_preflight_test_env(tmpdir)
                    bin_dir = Path(tmpdir) / "bin"
                    (bin_dir / "bq").unlink()
                    env["PATH"] = _path_without({"bq"}, bin_dir)
                    proc = _run_start_point_script(
                        [*invocation, "--env", str(env_file)], env
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertIn("[FAIL] bq CLI is not installed", proc.stderr)
                    calls = (
                        log_file.read_text(encoding="utf-8")
                        if log_file.exists()
                        else ""
                    )
                    self.assertNotIn("bq ", calls)

    def test_verify_main_fails_before_any_call_when_gcloud_missing_for_gs_locations(
        self,
    ) -> None:
        """bin/verify-main-end-state must reject a missing gcloud CLI up front when any location is a gs:// URI."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(tmpdir)
            bin_dir = Path(tmpdir) / "bin"
            (bin_dir / "gcloud").unlink()
            env["PATH"] = _path_without({"gcloud"}, bin_dir)
            proc = _run_start_point_script(
                [
                    "verify-main-end-state",
                    "--answer-key",
                    "gs://fake-bucket-74/a.json",
                    "--reveal",
                    "gs://fake-bucket-74/r.csv",
                    "--env",
                    str(env_file),
                ],
                env,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("[FAIL] gcloud CLI is not installed", proc.stderr)
            self.assertEqual(_read_calls(log_file), "")

    def test_reset_rejects_placeholder_staging_bucket_before_any_bq_call(
        self,
    ) -> None:
        """bin/reset must reject a placeholder STAGING_BUCKET before listing or dropping any table."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, env, log_file = setup_preflight_test_env(tmpdir)
            env_file = create_demo_env_file(
                tmpdir, staging_bucket="your-staging-bucket"
            )
            proc = _run_start_point_script(
                ["reset", "ws1", "--yes", "--env", str(env_file)], env
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("[FAIL] STAGING_BUCKET", proc.stderr)
            calls = log_file.read_text(encoding="utf-8") if log_file.exists() else ""
            self.assertNotIn("bq ", calls)


class TestPinnedRequireStateBucket(unittest.TestCase):
    def test_rejects_missing_or_placeholder_bucket_and_accepts_real_bucket(
        self,
    ) -> None:
        """pinned_require_state_bucket must reject unset or 'your-' STATE_BUCKET and pass for a real bucket."""
        for value in ("", "your-state-bucket"):
            with self.subTest(value=value):
                proc = _run_bash(f'STATE_BUCKET="{value}"\npinned_require_state_bucket')
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("[FAIL] STATE_BUCKET is missing", proc.stderr)

        unset = _run_bash("unset STATE_BUCKET\npinned_require_state_bucket")
        self.assertNotEqual(unset.returncode, 0)
        self.assertIn("[FAIL] STATE_BUCKET", unset.stderr)

        ok = _run_bash('STATE_BUCKET="real-state-50"\npinned_require_state_bucket')
        self.assertEqual(ok.returncode, 0, ok.stderr)


def _write_logging_stub(
    bin_dir: Path, name: str, log_file: Path, body: str = ""
) -> None:
    """Write an executable stub that logs '<name> <args>' and then runs *body* (default: exit 0)."""
    stub = bin_dir / name
    stub.write_text(
        f'#!/usr/bin/env bash\necho "{name} $*" >> "{log_file}"\n{body}\nexit 0\n',
        encoding="utf-8",
    )
    stub.chmod(0o755)


def _read_calls(log_file: Path) -> str:
    return log_file.read_text(encoding="utf-8") if log_file.exists() else ""


def _run_bootstrap(
    tmpdir: str,
    *,
    gcloud_body: str | None = "",
    state_bucket: str = "demo-state-bucket",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run bin/bootstrap-tf-state with logging gcloud/terraform stubs; gcloud_body=None removes gcloud from PATH."""
    bin_dir = Path(tmpdir) / "bin"
    bin_dir.mkdir()
    log_file = Path(tmpdir) / "calls.log"
    _write_logging_stub(bin_dir, "terraform", log_file)
    env = os.environ.copy()
    if gcloud_body is None:
        env["PATH"] = _path_without({"gcloud"}, bin_dir)
    else:
        _write_logging_stub(bin_dir, "gcloud", log_file, gcloud_body)
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env_file = create_demo_env_file(tmpdir, state_bucket=state_bucket)
    proc = _run_start_point_script(["bootstrap-tf-state", "--env", str(env_file)], env)
    return proc, log_file


class TestLoadersSetupAndBootstrapFailFast(unittest.TestCase):
    def test_loaders_fail_before_any_bq_call_when_bq_missing(self) -> None:
        """bin/load-raw-ops and bin/load-reveal must reject a missing bq CLI before issuing any bq call."""
        with tempfile.TemporaryDirectory() as reveal_dir:
            invocations = (["load-raw-ops"], ["load-reveal", reveal_dir])
            for invocation in invocations:
                with (
                    self.subTest(script=invocation[0]),
                    tempfile.TemporaryDirectory() as tmpdir,
                ):
                    env_file, env, log_file = setup_preflight_test_env(tmpdir)
                    bin_dir = Path(tmpdir) / "bin"
                    (bin_dir / "bq").unlink()
                    env["PATH"] = _path_without({"bq"}, bin_dir)
                    proc = _run_start_point_script(
                        [*invocation, "--env", str(env_file)], env
                    )
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertIn("[FAIL] bq CLI is not installed", proc.stderr)
                    self.assertNotIn(reveal_dir, proc.stdout + proc.stderr)
                    self.assertNotIn("bq ", _read_calls(log_file))

    def test_setup_rejects_placeholder_env_before_running_any_step(self) -> None:
        """bin/setup must reject a placeholder PROJECT_ID before starting Step 1/3."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, env, log_file = setup_preflight_test_env(tmpdir)
            env_file = create_demo_env_file(tmpdir, project_id="your-project-id")
            proc = _run_start_point_script(["setup", "--env", str(env_file)], env)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("[FAIL] PROJECT_ID", proc.stderr)
            self.assertNotIn("Step 1/3", proc.stdout)
            self.assertEqual(_read_calls(log_file), "")

    def test_bootstrap_rejects_placeholder_state_bucket_before_any_gcloud_call(
        self,
    ) -> None:
        """bin/bootstrap-tf-state must reject a placeholder STATE_BUCKET before touching any bucket."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc, log_file = _run_bootstrap(tmpdir, state_bucket="your-state-bucket")
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("[FAIL] STATE_BUCKET", proc.stderr)
            self.assertEqual(_read_calls(log_file), "")

    def test_bootstrap_fails_fast_when_gcloud_missing(self) -> None:
        """bin/bootstrap-tf-state must report a missing gcloud CLI instead of treating it as a missing bucket."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc, log_file = _run_bootstrap(tmpdir, gcloud_body=None)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("[FAIL] gcloud CLI is not installed", proc.stderr)
            self.assertEqual(_read_calls(log_file), "")

    def test_bootstrap_reports_failed_bucket_update_under_strict_mode(self) -> None:
        """Under set -euo pipefail, a failed state-bucket update must print [FAIL] and stop before terraform init."""
        with tempfile.TemporaryDirectory() as tmpdir:
            proc, log_file = _run_bootstrap(
                tmpdir,
                gcloud_body='if [[ "$*" == *"buckets update"* ]]; then exit 1; fi',
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("[FAIL]", proc.stderr)
            self.assertIn("demo-state-bucket", proc.stderr)
            calls = _read_calls(log_file)
            self.assertIn(
                "gcloud storage buckets update gs://demo-state-bucket --project=demo-proj-123",
                calls,
            )
            self.assertNotIn("terraform", calls)


_DIRECT_CALL_PREFIX = (
    r"(?:^|[;&|(\[`{!]|\b(?:then|do|else|elif|if|while|until|exec|time|nohup|xargs)\b"
    r"|\benv(?:\s+-u\s+\w+|\s+-\w+|\s+\w+=\S*)*)"
)


class _ForbiddenPattern(NamedTuple):
    label: str
    pattern: re.Pattern[str]
    marker_exempts: bool  # may the per-line allow marker exempt a match?


_FORBIDDEN_PATTERNS: tuple[_ForbiddenPattern, ...] = (
    _ForbiddenPattern(
        "direct bq/gcloud invocation (use the pinned_* wrappers in bin/lib/pinning.sh)",
        re.compile(
            _DIRECT_CALL_PREFIX
            + r"\s*(?:[\"'](?:bq|gcloud)[\"']|(?:bq|gcloud)(?=$|[\s;|&)]))"
            + r"|\bcommand\s+(?:-\w+\s+)*(?:bq|gcloud)\b"
            + r"|\b(?:os\.system|os\.popen|subprocess\.\w+|Popen)\(\s*\[?\s*[\"'](?:bq|gcloud)\b"
        ),
        False,
    ),
    _ForbiddenPattern(
        "bq/gcloud command text",
        re.compile(
            r"(?<![\w-])(?:bq\s+(?:--project_id|--location|--format|query|show|ls|rm|cp|load|update|mk|head)\b"
            r"|gcloud\s+(?:storage|dataproc)\b)"
        ),
        True,
    ),
    _ForbiddenPattern(
        "self-sourcing of ENV_FILE or demo.env (use pinned_load_env)",
        re.compile(
            r"(?:^|[;&|(\s])(?:source|\.)\s+[\"']?[^\s;]*(?:ENV_FILE|demo\.env)"
            r"|<\s*[\"']?[^\s;]*(?:ENV_FILE|demo\.env)"
            r"|\b(?:eval|cat|grep|sed|awk|xargs)\b[^|;]*(?:ENV_FILE|demo\.env)"
            r"|\bopen\([^)]*(?:ENV_FILE|env_file|demo\.env)"
        ),
        False,
    ),
    _ForbiddenPattern(
        "inline 'your-' placeholder check or missing env message (use pinned_require_*)",
        re.compile(r"\byour-|Environment file not found:"),
        False,
    ),
    _ForbiddenPattern(
        "inline JSON-parsing copy (use pinned_bq_json / lib/bq_json.py)",
        re.compile(
            r"\braw_decode\b|JSONDecoder\(|JSONDecodeError"
            r"|\bin\s+[\"']\[\{[\"']|\.(?:find|index)\(\s*[\"'][\[{][\"']\s*\)"
        ),
        False,
    ),
)


# Explicit per-line escape hatch for text that matches the bq/gcloud command-text
# pattern but is data, not an invocation (e.g. preflight's guardrail-hook probe
# payloads). State the reason. It never exempts a real invocation, an env-file
# source, a placeholder check, or an inline JSON parser.
_ALLOW_MARKER = re.compile(r"# pinning-guard: allow \(.+\)")


def _scan_script_violations(script_path: Path) -> list[str]:
    violations: list[str] = []
    for lineno, raw_line in enumerate(
        script_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        allowed = bool(_ALLOW_MARKER.search(stripped))
        for rule in _FORBIDDEN_PATTERNS:
            if (allowed and rule.marker_exempts) or not rule.pattern.search(stripped):
                continue
            violations.append(f"L{lineno} ({rule.label}): {stripped}")
            break  # one violation per line keeps the report readable
    return violations


class TestPinningSourceScanGuard(unittest.TestCase):
    def test_scanner_flags_direct_calls_unless_line_carries_allow_marker(
        self,
    ) -> None:
        """The guard must flag a direct bq call but skip a line marked as non-invocation data with a stated reason."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "script"
            script.write_text(
                'bq query --use_legacy_sql=false "SELECT 1"\n'
                "payload='bq query \"SELECT 1\"'  # pinning-guard: allow (hook probe payload)\n"
                "payload='bq query \"SELECT 1\"'  # pinning-guard: allow\n",
                encoding="utf-8",
            )
            violations = _scan_script_violations(script)
        self.assertEqual(len(violations), 2, violations)
        self.assertTrue(violations[0].startswith("L1 "), violations)
        self.assertTrue(violations[1].startswith("L3 "), violations)

    def test_scanner_is_strict_for_every_direct_call_env_source_placeholder_and_parser(
        self,
    ) -> None:
        """Any direct bq/gcloud call, env-file self-source, placeholder check or inline JSON parser is flagged, even with an allow marker."""
        flagged = (
            'active=$(env -u CLOUDSDK_CORE_PROJECT gcloud config configurations list --format="value(x)")',
            "if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then",
            'state=$(gcloud projects describe "${p}" --format="value(lifecycleState)")',
            "gcloud compute instances list",
            "bq version",
            'if ! bq --headless query "SELECT 1"; then',
            "cmd=(gcloud dataproc batches submit pyspark x)",
            'subprocess.run(["bq", "show", ref], check=True)',
            "command -v gcloud >/dev/null",
            "x=1; bq ls  # pinning-guard: allow (not really data)",
            'source "${ENV_FILE}"',
            '. "${REPO_ROOT}/demo.env"',
            "set -a && source ./demo.env && set +a",
            'while IFS== read -r k v; do :; done < "${ENV_FILE}"',
            'eval "$(cat "${ENV_FILE}")"',
            "source <(grep -v '^#' \"${ENV_FILE}\")",
            "with open(env_file) as fh:",
            'os.system("bq ls")  # pinning-guard: allow (sneaky)',
            'subprocess.check_output(["gcloud", "config", "list"])',
            'if [[ "${PROJECT_ID}" == your-* ]]; then',
            'if value.startswith("your-"):',
            "decoder = json.JSONDecoder()",
            "obj, _ = decoder.raw_decode(raw[idx:])",
            "except json.JSONDecodeError:",
            'if ch in "[{":',
            "start = raw.find('{')",
        )
        clean = (
            'echo "Run: gcloud config set project ${PROJECT_ID}"',
            'echo "No active gcloud account configured."',
            'echo "BigQuery MCP must authenticate as the presenter. Run: gcloud auth login"',
            'source "${SCRIPT_DIR}/lib/pinning.sh"',
            "if ! pinned_require_cli gcloud bq; then",
            "active=$(pinned_gcloud_profile core/project 2>/dev/null || true)",
            'if ! pinned_bq query --use_legacy_sql=false "${SQL}"; then',
            'if ! pinned_load_env "${ENV_FILE}"; then',
            'ENV_FILE="${REPO_ROOT}/demo.env"',
            'echo "  -e, --env <path>  Path to environment file (default: demo.env)"',
            "rows = json.loads(sys.argv[1])",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "script"
            script.write_text("\n".join(flagged + clean) + "\n", encoding="utf-8")
            violations = _scan_script_violations(script)
        flagged_lines = {int(v.split(" ", 1)[0][1:]) for v in violations}
        self.assertEqual(
            flagged_lines, set(range(1, len(flagged) + 1)), "\n".join(violations)
        )

    def test_bin_scripts_use_pinning_module(self) -> None:
        """Every bin/* file (shell, Python, JS) must use bin/lib/pinning.sh instead of direct bq/gcloud or inline env checks."""
        bin_dir = WORKTREE_ROOT / "bin"
        unexpected: dict[str, list[str]] = {}

        for path in sorted(bin_dir.iterdir()):
            if not path.is_file():
                continue
            violations = _scan_script_violations(path)
            if violations:
                unexpected[f"bin/{path.name}"] = violations

        self.assertEqual(
            unexpected,
            {},
            f"Scripts have unmigrated bq/gcloud/env calls: {unexpected}",
        )


# A script that calls any wrapper on the left must fail fast with
# `pinned_require_cli <cli>` so a missing CLI is reported up front, not mid-run.
_CLI_REQUIREMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:pinned_bq|pinned_bq_json|pinned_label)\b"), "bq"),
    (re.compile(r"\b(?:pinned_storage|pinned_dataproc_\w+)\b"), "gcloud"),
)


def _scan_cli_requirement_violations(script_path: Path) -> list[str]:
    code = [
        "" if line.lstrip().startswith("#") else line.split(" #", 1)[0]
        for line in script_path.read_text(encoding="utf-8").splitlines()
    ]
    required = {
        cli
        for line in code
        if (match := re.search(r"\bpinned_require_cli\b([^;&|#)]*)", line))
        for cli in match.group(1).split()
    }
    violations: list[str] = []
    for wrapper, cli in _CLI_REQUIREMENTS:
        if cli in required:
            continue
        for lineno, line in enumerate(code, start=1):
            if wrapper.search(line):
                violations.append(
                    f"calls {wrapper.search(line).group(0)} (L{lineno}) "
                    f"without `pinned_require_cli {cli}`"
                )
                break
    return violations


class TestPinningCliRequirementGuard(unittest.TestCase):
    def _violations(self, body: str) -> list[str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            script = Path(tmpdir) / "script"
            script.write_text(body, encoding="utf-8")
            return _scan_cli_requirement_violations(script)

    def test_scanner_flags_wrapper_use_without_matching_require_cli(self) -> None:
        """A script calling a bq or gcloud wrapper without `pinned_require_cli <cli>` is flagged."""
        cases = {
            'pinned_bq query "SELECT 1"\n': ["bq"],
            'pinned_label "staging.t"\n': ["bq"],
            'x=$(pinned_bq_json show "t")\n': ["bq"],
            'pinned_storage cp "gs://b/o" .\n': ["gcloud"],
            'pinned_dataproc_submit "p.py" "b1"\n': ["gcloud"],
            "pinned_require_cli gcloud\npinned_bq ls\n": ["bq"],
            "pinned_require_cli bq\npinned_dataproc_delete b1\n": ["gcloud"],
            "# pinned_require_cli bq\npinned_bq ls\n": ["bq"],
            "echo x  # pinned_require_cli bq\npinned_bq ls\n": ["bq"],
            "pinned_require_cli bq\npinned_bq ls\npinned_storage ls gs://b\n": [
                "gcloud"
            ],
        }
        for body, missing in cases.items():
            with self.subTest(body=body):
                violations = self._violations(body)
                self.assertEqual(len(violations), len(missing), violations)
                for violation, cli in zip(violations, missing, strict=True):
                    self.assertIn(f"`pinned_require_cli {cli}`", violation)

    def test_scanner_accepts_matching_require_cli_and_unrelated_wrappers(self) -> None:
        """Matching requirements in any form pass; env/label-check wrappers and comments need no CLI requirement."""
        for body in (
            "if ! pinned_require_cli bq; then exit 1; fi\npinned_bq ls\n",
            "pinned_require_cli gcloud bq || return 1\npinned_label t\npinned_storage ls gs://b\n",
            "pinned_require_cli gcloud\npinned_require_cli bq\npinned_dataproc_describe b\npinned_bq_json x\n",
            "pinned_load_env\npinned_require_project_region\npinned_has_demo_label x\n",
            "# pinned_bq query is mentioned only in a comment\n",
            "",
        ):
            with self.subTest(body=body):
                self.assertEqual(self._violations(body), [])

    def test_bin_scripts_require_the_clis_their_wrappers_need(self) -> None:
        """Every bin/* script using a bq or gcloud wrapper must call `pinned_require_cli` for that CLI."""
        unexpected = {
            f"bin/{path.name}": violations
            for path in sorted((WORKTREE_ROOT / "bin").iterdir())
            if path.is_file() and (violations := _scan_cli_requirement_violations(path))
        }
        self.assertEqual(unexpected, {}, unexpected)


_PUBLIC_FUNCTION = re.compile(r"^(pinned_\w+)\(\)\s*\{", re.MULTILINE)
_GLOBALS_ENTRY = re.compile(
    r"^#\s+(pinned_\w+)\s*\n#\s+reads:\s*(?P<reads>.+)\n#\s+writes:\s*(?P<writes>.+)$",
    re.MULTILINE,
)


class TestPinningGlobalsHeader(unittest.TestCase):
    def test_header_documents_reads_and_writes_for_every_public_function(
        self,
    ) -> None:
        """pinning.sh must list, for every public pinned_* function, the globals it reads and writes."""
        text = PINNING_SH.read_text(encoding="utf-8")
        defined = set(_PUBLIC_FUNCTION.findall(text))
        documented = {m.group(1): m for m in _GLOBALS_ENTRY.finditer(text)}
        self.assertTrue(defined)
        self.assertEqual(set(documented), defined)

        load_env = documented["pinned_load_env"]
        for name in ("CLI_DATASET_SET", "DATASET_LOCATION", "ENV_FILE"):
            self.assertIn(name, load_env.group("reads"))
        for name in ("DATASET_DIR", "ENV_FILE", "PROJECT_ID", "REGION", "REPO_ROOT"):
            self.assertIn(name, load_env.group("writes"))


if __name__ == "__main__":
    unittest.main()
