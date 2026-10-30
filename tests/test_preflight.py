import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (
    PREFLIGHT_BIN,
    PREFLIGHT_SYMLINK,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)


class TestEnvironmentTemplate(unittest.TestCase):
    def test_environment_template_exists_and_no_real_ids(self):
        """demo.env.example must exist, and contain no real project IDs or bucket names."""
        template_path = WORKTREE_ROOT / "demo.env.example"
        self.assertTrue(
            template_path.exists(), "demo.env.example must exist in repository root"
        )

        content = template_path.read_text()

        required_vars = [
            "PROJECT_ID",
            "REGION",
            "STAGING_BUCKET",
            "STATE_BUCKET",
            "CLOUDSDK_CORE_PROJECT",
            "CLOUDSDK_COMPUTE_REGION",
            "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_QUOTA_PROJECT",
            "TF_VAR_project_id",
            "TF_VAR_region",
            "TF_VAR_staging_bucket",
            "TF_VAR_state_bucket",
        ]
        for var in required_vars:
            self.assertIn(var, content, f"demo.env.example must define {var}")

        self.assertNotIn("prj-", content)
        self.assertNotIn("altostrat", content)
        self.assertNotIn("mbychkowski", content)

    def test_demo_env_is_gitignored(self):
        """demo.env must be ignored by git."""
        gitignore_path = WORKTREE_ROOT / ".gitignore"
        self.assertTrue(gitignore_path.exists(), ".gitignore must exist")
        lines = [line.strip() for line in gitignore_path.read_text().splitlines()]
        self.assertIn("demo.env", lines, "demo.env must be in .gitignore")

    def test_env_file_exports_in_subshell(self):
        """Sourcing demo.env.example in bash must export all required overrides."""
        cmd = """
        source demo.env.example
        echo "CORE_PROJECT=$CLOUDSDK_CORE_PROJECT"
        echo "COMPUTE_REGION=$CLOUDSDK_COMPUTE_REGION"
        echo "GOOGLE_PROJECT=$GOOGLE_CLOUD_PROJECT"
        echo "QUOTA_PROJECT=$GOOGLE_CLOUD_QUOTA_PROJECT"
        echo "TF_PROJECT=$TF_VAR_project_id"
        echo "TF_REGION=$TF_VAR_region"
        echo "TF_STAGING=$TF_VAR_staging_bucket"
        echo "TF_STATE=$TF_VAR_state_bucket"
        """
        proc = subprocess.run(
            ["bash", "-c", cmd],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("CORE_PROJECT=your-project-id", proc.stdout)
        self.assertIn("COMPUTE_REGION=us-central1", proc.stdout)
        self.assertIn("GOOGLE_PROJECT=your-project-id", proc.stdout)
        self.assertIn("QUOTA_PROJECT=your-project-id", proc.stdout)
        self.assertIn("TF_PROJECT=your-project-id", proc.stdout)
        self.assertIn("TF_REGION=us-central1", proc.stdout)
        self.assertIn("TF_STAGING=your-dataproc-staging-bucket", proc.stdout)
        self.assertIn("TF_STATE=your-terraform-state-bucket", proc.stdout)


class TestPreflightCLI(unittest.TestCase):
    def test_preflight_executable_exists(self):
        """preflight and bin/preflight must exist and be executable."""
        self.assertTrue(PREFLIGHT_BIN.exists(), "bin/preflight must exist")
        self.assertTrue(
            os.access(PREFLIGHT_BIN, os.X_OK), "bin/preflight must be executable"
        )
        self.assertTrue(PREFLIGHT_SYMLINK.exists(), "preflight symlink must exist")
        self.assertTrue(
            os.access(PREFLIGHT_SYMLINK, os.X_OK),
            "preflight symlink must be executable",
        )

    def test_preflight_fails_when_env_file_missing(self):
        """preflight should report [FAIL] and non-zero exit when demo.env is missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_env = Path(tmpdir) / "nonexistent.env"
            proc = subprocess.run(
                [str(PREFLIGHT_BIN), "--env", str(fake_env)],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(
                proc.returncode,
                0,
                "preflight must exit non-zero when env file is missing",
            )
            self.assertIn("[FAIL]", proc.stdout)
            self.assertIn("Environment file not found", proc.stdout)

    def test_preflight_fails_on_unconfigured_placeholders(self):
        """preflight should report [FAIL] if variables still have placeholder values."""
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(Path(WORKTREE_ROOT / "demo.env.example").read_text())
            tmp_env_path = f.name
        try:
            proc = subprocess.run(
                [str(PREFLIGHT_BIN), "--env", tmp_env_path],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(
                proc.returncode, 0, "preflight must exit non-zero on placeholder values"
            )
            self.assertIn("[FAIL]", proc.stdout)
            self.assertIn("placeholder", proc.stdout.lower())
        finally:
            os.remove(tmp_env_path)

    def test_preflight_fails_when_variable_not_exported(self):
        """preflight must fail when required variables are set but not exported."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="test-demo-project",
                exported=False,
            )

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
                "[FAIL] Environment variables and overrides configured", proc.stdout
            )
            self.assertIn("is set but not exported", proc.stdout)

    def test_preflight_fails_when_gcloud_project_mismatches(self):
        """preflight must fail with clear message when active gcloud project doesn't match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="expected-project",
                active_project="different-active-project",
                quota_project="expected-project",
            )

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
                "[FAIL] Active gcloud project and region match environment", proc.stdout
            )
            self.assertIn(
                "Active gcloud project ('different-active-project') does not match environment file PROJECT_ID ('expected-project')",
                proc.stdout,
            )
            self.assertIn("gcloud config set project expected-project", proc.stdout)

    def test_preflight_fails_when_gcloud_region_mismatches(self):
        """preflight must fail when active gcloud compute region doesn't match REGION."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="expected-project",
                region="us-central1",
                active_project="expected-project",
                active_region="us-east1",
                quota_project="expected-project",
            )

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
                "[FAIL] Active gcloud project and region match environment", proc.stdout
            )
            self.assertIn(
                "Active gcloud compute/region ('us-east1') does not match environment file REGION ('us-central1')",
                proc.stdout,
            )
            self.assertIn("gcloud config set compute/region us-central1", proc.stdout)

    def test_preflight_fails_when_adc_quota_project_mismatches(self):
        """preflight must fail with clear message when ADC quota project doesn't match."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="expected-project",
                active_project="expected-project",
                quota_project="old-stale-project",
            )

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
                "[FAIL] ADC quota project matches PROJECT_ID and is active", proc.stdout
            )
            self.assertIn(
                "ADC quota project ('old-stale-project') does not match environment file PROJECT_ID ('expected-project')",
                proc.stdout,
            )
            self.assertIn("BigQuery MCP's opaque Forbidden errors", proc.stdout)
            self.assertIn(
                "gcloud auth application-default set-quota-project expected-project",
                proc.stdout,
            )

    def test_preflight_fails_when_adc_quota_project_is_stale_or_deleted(self):
        """preflight must fail when quota project exists in ADC but is stale or deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="stale-project",
                active_project="stale-project",
                quota_project="stale-project",
                describe_fails=True,
            )

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
                "[FAIL] ADC quota project matches PROJECT_ID and is active", proc.stdout
            )
            self.assertIn("is inaccessible, stale, or deleted", proc.stdout)
            self.assertIn("BigQuery MCP's opaque Forbidden errors", proc.stdout)

    def test_preflight_passes_when_all_match_and_active(self):
        """preflight outputs all [PASS] and exits 0 when config, ADC, and project match and are active."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                project_id="demo-proj-123",
                active_project="demo-proj-123",
                quota_project="demo-proj-123",
                describe_state="ACTIVE",
            )

            proc = subprocess.run(
                [str(PREFLIGHT_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode, 0, f"Output was:\n{proc.stdout}\n{proc.stderr}"
            )
            self.assertIn("[PASS] Environment file exists", proc.stdout)
            self.assertIn(
                "[PASS] Environment variables and overrides configured", proc.stdout
            )
            self.assertIn(
                "[PASS] Active gcloud project and region match environment", proc.stdout
            )
            self.assertIn(
                "[PASS] ADC quota project matches PROJECT_ID and is active", proc.stdout
            )
            self.assertIn(
                "[PASS] Dataproc Serverless runtime 3.0 hello-world batch writes to BigQuery",
                proc.stdout,
            )
            self.assertIn(
                "[PASS] BigQuery MCP authenticates as presenter (no compute metadata fallback)",
                proc.stdout,
            )
            self.assertIn(
                "[PASS] Vendored BigQuery MCP proxy matches installed Data Agent Kit",
                proc.stdout,
            )
            self.assertIn("Summary: 7 passed, 0 failed.", proc.stdout)


if __name__ == "__main__":
    unittest.main()
