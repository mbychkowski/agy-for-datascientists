import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PREFLIGHT_BIN, WORKTREE_ROOT, setup_preflight_test_env

INFRA_DIR = WORKTREE_ROOT / "infra"
BOOTSTRAP_BIN = WORKTREE_ROOT / "bin" / "bootstrap-tf-state"
HELLO_WORLD_PY = WORKTREE_ROOT / "bin" / "dataproc_hello_world.py"


class TestTerraformFoundation(unittest.TestCase):
    def test_infra_files_exist_and_scripts_executable(self):
        """All Terraform files, bootstrap script, and hello-world script must exist."""
        for fname in (
            "versions.tf",
            "variables.tf",
            "main.tf",
            "outputs.tf",
            "README.md",
        ):
            self.assertTrue((INFRA_DIR / fname).exists(), f"infra/{fname} must exist")
        self.assertTrue(BOOTSTRAP_BIN.exists(), "bin/bootstrap-tf-state must exist")
        self.assertTrue(
            os.access(BOOTSTRAP_BIN, os.X_OK),
            "bin/bootstrap-tf-state must be executable",
        )
        self.assertTrue(
            HELLO_WORLD_PY.exists(), "bin/dataproc_hello_world.py must exist"
        )
        self.assertTrue(
            os.access(HELLO_WORLD_PY, os.X_OK),
            "bin/dataproc_hello_world.py must be executable",
        )

    def test_required_variables_have_no_defaults_except_subnet(self):
        """project_id, region, staging_bucket, and state_bucket must not define defaults."""
        content = (INFRA_DIR / "variables.tf").read_text()
        blocks = re.findall(
            r'variable\s+"([^"]+)"\s*\{(.*?)\n\}', content, flags=re.DOTALL
        )
        var_map = dict(blocks)
        for req_var in ("project_id", "region", "staging_bucket", "state_bucket"):
            self.assertIn(req_var, var_map, f"variable {req_var} must be declared")
            self.assertNotRegex(
                var_map[req_var],
                r"^\s*default\s*=",
                f"variable '{req_var}' must not have a default value",
            )
        self.assertIn("subnet", var_map)
        self.assertRegex(var_map["subnet"], r'default\s*=\s*""')

        outputs_tf = (INFRA_DIR / "outputs.tf").read_text()
        self.assertIn("var.state_bucket", outputs_tf)

    def test_never_creates_projects_billing_folders_org_policies_or_iam(self):
        """Terraform must never create projects, billing, folders, org policies, or SA grants (ADR 0002)."""
        all_tf = "\n".join(p.read_text() for p in INFRA_DIR.glob("*.tf"))
        forbidden_resources = [
            'google_project"',
            "google_folder",
            "google_billing_",
            "google_org_policy",
            "google_organization_policy",
            "google_service_account",
            "google_project_iam_",
            "google_bigquery_dataset_iam_",
            "google_storage_bucket_iam_",
            "aiplatform.googleapis.com",
        ]
        for forbidden in forbidden_resources:
            self.assertNotIn(
                forbidden,
                all_tf,
                f"Forbidden resource or service '{forbidden}' found in Terraform config",
            )

    def test_every_resource_sets_project_explicitly(self):
        """Every resource block in infra/main.tf must set project = var.project_id explicitly."""
        main_tf = (INFRA_DIR / "main.tf").read_text()
        resource_blocks = re.findall(
            r'resource\s+"([^"]+)"\s+"([^"]+)"\s*\{(.*?)\n\}',
            main_tf,
            flags=re.DOTALL,
        )
        self.assertGreaterEqual(len(resource_blocks), 6)
        for r_type, r_name, body in resource_blocks:
            self.assertRegex(
                body,
                r"project\s*=\s*var\.project_id",
                f"Resource {r_type}.{r_name} must set 'project = var.project_id'",
            )

    def test_enables_exact_required_apis_and_creates_six_labelled_datasets(self):
        """Terraform must enable the exact 6 required APIs and create the 6 demo datasets with demo=true."""
        main_tf = (INFRA_DIR / "main.tf").read_text()
        expected_apis = [
            "bigquery.googleapis.com",
            "bigquerystorage.googleapis.com",
            "dataproc.googleapis.com",
            "dataprocrm.googleapis.com",
            "storage.googleapis.com",
            "compute.googleapis.com",
        ]
        for api in expected_apis:
            self.assertIn(f'"{api}"', main_tf, f"Missing required API: {api}")

        expected_datasets = [
            "raw",
            "ops",
            "staging",
            "features",
            "ml",
            "checkpoint",
        ]
        for ds in expected_datasets:
            self.assertIn(f'"{ds}"', main_tf, f"Missing required dataset: {ds}")

        self.assertIn('demo = "true"', main_tf)
        self.assertIn("private_ip_google_access = true", main_tf)

        versions_tf = (INFRA_DIR / "versions.tf").read_text()
        self.assertIn('backend "gcs"', versions_tf)

    def test_terraform_validate_passes(self):
        """terraform init -backend=false && terraform validate must pass if terraform CLI is installed."""
        if not shutil.which("terraform"):
            self.skipTest("terraform CLI not installed in environment")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_infra = Path(tmpdir) / "infra"
            shutil.copytree(INFRA_DIR, tmp_infra)
            init_proc = subprocess.run(
                ["terraform", f"-chdir={tmp_infra}", "init", "-backend=false"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                init_proc.returncode,
                0,
                f"terraform init failed:\n{init_proc.stdout}\n{init_proc.stderr}",
            )
            val_proc = subprocess.run(
                ["terraform", f"-chdir={tmp_infra}", "validate"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                val_proc.returncode,
                0,
                f"terraform validate failed:\n{val_proc.stdout}\n{val_proc.stderr}",
            )

    def test_bootstrap_tf_state_creates_bucket_and_initializes_backend(self):
        """bin/bootstrap-tf-state must create gs://STATE_BUCKET and run terraform init with bucket config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bin_dir = Path(tmpdir) / "bin"
            bin_dir.mkdir()
            log_file = Path(tmpdir) / "calls.log"

            fake_gcloud = bin_dir / "gcloud"
            fake_gcloud.write_text(f"""#!/usr/bin/env bash
echo "gcloud $*" >> "{log_file}"
if [[ "$*" == *"storage buckets describe"* ]]; then
    exit 1
fi
exit 0
""")
            fake_gcloud.chmod(0o755)

            fake_terraform = bin_dir / "terraform"
            fake_terraform.write_text(f"""#!/usr/bin/env bash
echo "terraform $*" >> "{log_file}"
exit 0
""")
            fake_terraform.chmod(0o755)

            env_file = Path(tmpdir) / "demo.env"
            env_file.write_text("""
PROJECT_ID="demo-proj-123"
REGION="us-central1"
STAGING_BUCKET="demo-staging-123"
STATE_BUCKET="demo-tfstate-123"
export PROJECT_ID REGION STAGING_BUCKET STATE_BUCKET
""")

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"

            proc = subprocess.run(
                [str(BOOTSTRAP_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode, 0, f"Output:\n{proc.stdout}\n{proc.stderr}"
            )
            calls = log_file.read_text()
            self.assertIn(
                "gcloud storage buckets create gs://demo-tfstate-123 --project=demo-proj-123 --location=us-central1",
                calls,
            )
            self.assertIn("-backend-config=bucket=demo-tfstate-123", calls)


class TestDataprocPreflightSeam(unittest.TestCase):
    def test_dataproc_preflight_submits_runtime_3_0_as_presenter_and_cleans_up(
        self,
    ):
        """Preflight must submit runtime 3.0 batch without invalid ShieldedVm properties or SA flag, verify BQ write, and clean up."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(
                tmpdir,
                subnet="projects/demo-proj-123/regions/us-central1/subnetworks/custom-sub",
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
                proc.returncode, 0, f"Output:\n{proc.stdout}\n{proc.stderr}"
            )
            self.assertIn(
                "[PASS] Dataproc Serverless runtime 3.0 hello-world batch writes to BigQuery",
                proc.stdout,
            )

            calls = log_file.read_text()
            self.assertIn("--version=3.0", calls)
            self.assertIn(
                "--subnet=projects/demo-proj-123/regions/us-central1/subnetworks/custom-sub",
                calls,
            )
            self.assertNotIn("--properties", calls)
            self.assertNotIn("ShieldedVm", calls)
            self.assertNotIn("--service-account", calls)
            self.assertIn(
                "bq show --project_id=demo-proj-123 --location=us-central1 demo-proj-123:ops._preflight_hello_test",
                calls,
            )
            self.assertIn(
                "bq rm -f -t --project_id=demo-proj-123 --location=us-central1 demo-proj-123:ops._preflight_hello_test",
                calls,
            )
            self.assertIn(
                "gcloud dataproc batches delete preflight-hello-test --project=demo-proj-123 --region=us-central1 --quiet",
                calls,
            )

    def test_dataproc_preflight_fails_and_cleans_up_when_batch_fails(self):
        """Preflight must report [FAIL] and still run cleanup when batch submission fails."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, log_file = setup_preflight_test_env(tmpdir, batch_fails=True)
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
                "[FAIL] Dataproc Serverless runtime 3.0 hello-world batch writes to BigQuery",
                proc.stdout,
            )
            calls = log_file.read_text()
            self.assertIn("--subnet=demo-dataproc-subnet", calls)
            self.assertIn("gcloud dataproc batches delete preflight-hello-test", calls)


if __name__ == "__main__":
    unittest.main()
