import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKTREE_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "dak-bigquery"
WRAPPER_BIN = PLUGIN_DIR / "bin" / "run-bigquery-mcp"
VENDORED_PROXY = PLUGIN_DIR / "mcp" / "bin" / "mcp_proxy_bundle.cjs"
PREFLIGHT_BIN = WORKTREE_ROOT / "bin" / "preflight"


class TestDakBigQueryPlugin(unittest.TestCase):
    def test_workspace_plugin_structure_and_apache_license(self):
        """dak-bigquery must be workspace-scoped, keep its Apache-2.0 header, record DAK version, and omit proprietary bundles."""
        plugins_json = WORKTREE_ROOT / ".agents" / "plugins.json"
        self.assertTrue(plugins_json.exists(), ".agents/plugins.json must exist")

        plugin_manifest = PLUGIN_DIR / "plugin.json"
        self.assertTrue(plugin_manifest.exists(), "plugin.json must exist")
        manifest = json.loads(plugin_manifest.read_text())
        self.assertEqual(manifest.get("name"), "dak-bigquery")
        self.assertEqual(manifest.get("license"), "Apache-2.0")
        self.assertTrue(
            manifest.get("sourceDakVersion"),
            "plugin.json must record sourceDakVersion",
        )

        upstream_md = PLUGIN_DIR / "UPSTREAM.md"
        self.assertTrue(upstream_md.exists(), "UPSTREAM.md must exist")
        self.assertIn(manifest["sourceDakVersion"], upstream_md.read_text())

        self.assertTrue(VENDORED_PROXY.exists(), "mcp_proxy_bundle.cjs must exist")
        proxy_text = VENDORED_PROXY.read_text()
        self.assertIn("Licensed under the Apache License, Version 2.0", proxy_text)

        # Ensure no proprietary Data Agent Kit bundles (such as mcp/dist/index.js) are included
        self.assertFalse(
            (PLUGIN_DIR / "mcp" / "dist").exists(),
            "Proprietary mcp/dist bundle must not be included",
        )

        mcp_config = json.loads((PLUGIN_DIR / "mcp_config.json").read_text())
        self.assertIn("dak-bigquery", mcp_config.get("mcpServers", {}))
        server_cfg = mcp_config["mcpServers"]["dak-bigquery"]
        self.assertIn(
            "https://bigquery.googleapis.com/mcp",
            " ".join(server_cfg.get("args", [])),
        )

    def test_wrapper_reads_env_and_sets_billing_quota_project(self):
        """run-bigquery-mcp must source demo.env, set BILLING_QUOTA_PROJECT_ID, and launch the vendored proxy."""
        self.assertTrue(os.access(WRAPPER_BIN, os.X_OK), "Wrapper must be executable")

        with tempfile.TemporaryDirectory() as tmpdir:
            env_file = Path(tmpdir) / "demo.env"
            env_file.write_text("""
PROJECT_ID="presenter-demo-proj"
REGION="us-central1"
STAGING_BUCKET="presenter-staging"
STATE_BUCKET="presenter-state"
export PROJECT_ID REGION STAGING_BUCKET STATE_BUCKET
""")
            env = os.environ.copy()
            env["DATA_CLOUD_IDE_TYPE"] = "vscode"

            proc = subprocess.run(
                [str(WRAPPER_BIN), "--env", str(env_file), "--print-env"],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode, 0, f"Output:\n{proc.stdout}\n{proc.stderr}"
            )
            self.assertIn("PROJECT_ID=presenter-demo-proj", proc.stdout)
            self.assertIn("BILLING_QUOTA_PROJECT_ID=presenter-demo-proj", proc.stdout)
            self.assertIn("GOOGLE_CLOUD_QUOTA_PROJECT=presenter-demo-proj", proc.stdout)
            self.assertIn("ENDPOINT=https://bigquery.googleapis.com/mcp", proc.stdout)

            # Also verify exec node invocation using a mock node binary
            bin_dir = Path(tmpdir) / "bin"
            bin_dir.mkdir()
            fake_node = bin_dir / "node"
            fake_node.write_text("""#!/usr/bin/env bash
echo "NODE_ARGS=$*"
echo "BILLING=$BILLING_QUOTA_PROJECT_ID"
echo "IDE_TYPE=${DATA_CLOUD_IDE_TYPE:-UNSET}"
""")
            fake_node.chmod(0o755)
            env["PATH"] = f"{bin_dir}:{env['PATH']}"

            exec_proc = subprocess.run(
                [str(WRAPPER_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(exec_proc.returncode, 0)
            self.assertIn(
                "mcp_proxy_bundle.cjs https://bigquery.googleapis.com/mcp",
                exec_proc.stdout,
            )
            self.assertIn("BILLING=presenter-demo-proj", exec_proc.stdout)
            self.assertIn("IDE_TYPE=UNSET", exec_proc.stdout)

    def _setup_preflight_mocks(
        self,
        tmpdir,
        adc_dict=None,
        active_account="presenter@example.com",
        dak_proxy_bytes=None,
    ):
        bin_dir = Path(tmpdir) / "bin"
        bin_dir.mkdir(exist_ok=True)

        fake_gcloud = bin_dir / "gcloud"
        fake_gcloud.write_text(f"""#!/usr/bin/env bash
if [[ "$*" == *"configurations list"* ]]; then
    if [[ "$*" == *"properties.compute.region"* ]]; then
        echo "us-central1"
    elif [[ "$*" == *"properties.core.account"* ]]; then
        echo "{active_account}"
    else
        echo "demo-proj-123"
    fi
    exit 0
fi
if [[ "$*" == *"projects describe"* ]]; then
    echo "ACTIVE"
    exit 0
fi
exit 0
""")
        fake_gcloud.chmod(0o755)

        fake_bq = bin_dir / "bq"
        fake_bq.write_text("""#!/usr/bin/env bash
exit 0
""")
        fake_bq.chmod(0o755)

        if adc_dict is None:
            adc_dict = {
                "type": "authorized_user",
                "client_id": "test-client",
                "client_secret": "test-secret",
                "refresh_token": "test-refresh",
                "quota_project_id": "demo-proj-123",
            }
        adc_file = Path(tmpdir) / "adc.json"
        adc_file.write_text(json.dumps(adc_dict))

        env_file = Path(tmpdir) / "demo.env"
        env_file.write_text("""
PROJECT_ID="demo-proj-123"
REGION="us-central1"
STAGING_BUCKET="demo-staging-bucket"
STATE_BUCKET="demo-state-bucket"
SUBNET=""
export PROJECT_ID REGION STAGING_BUCKET STATE_BUCKET SUBNET
export CLOUDSDK_CORE_PROJECT="${PROJECT_ID}"
export CLOUDSDK_COMPUTE_REGION="${REGION}"
export GOOGLE_CLOUD_PROJECT="${PROJECT_ID}"
export GOOGLE_CLOUD_QUOTA_PROJECT="${PROJECT_ID}"
export TF_VAR_project_id="${PROJECT_ID}"
export TF_VAR_region="${REGION}"
export TF_VAR_staging_bucket="${STAGING_BUCKET}"
export TF_VAR_state_bucket="${STATE_BUCKET}"
export TF_VAR_subnet="${SUBNET}"
""")

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env['PATH']}"
        env["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_file)

        if dak_proxy_bytes is not None:
            dak_dir = Path(tmpdir) / "dak-plugin"
            (dak_dir / "mcp" / "bin").mkdir(parents=True)
            (dak_dir / "mcp" / "bin" / "mcp_proxy_bundle.cjs").write_bytes(
                dak_proxy_bytes
            )
            env["DAK_PLUGIN_DIR"] = str(dak_dir)

        return env_file, env

    def test_preflight_fails_when_adc_triggers_compute_metadata_fallback(self):
        """Preflight must fail if ADC lacks user OAuth fields or is a service_account (preventing silent metadata fallback)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Missing refresh_token/client_id/client_secret causes mcp_proxy_bundle.cjs to fall back to metadata server
            env_file, env = self._setup_preflight_mocks(
                tmpdir,
                adc_dict={
                    "type": "service_account",
                    "quota_project_id": "demo-proj-123",
                },
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
                "[FAIL] BigQuery MCP authenticates as presenter (no compute metadata fallback)",
                proc.stdout,
            )
            self.assertIn("compute metadata service account", proc.stdout)

    def test_preflight_fails_when_active_account_is_compute_service_account(self):
        """Preflight must fail if active gcloud account is a compute service account."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env = self._setup_preflight_mocks(
                tmpdir,
                active_account="123456789-compute@developer.gserviceaccount.com",
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
                "[FAIL] BigQuery MCP authenticates as presenter (no compute metadata fallback)",
                proc.stdout,
            )
            self.assertIn("is a service account rather than the presenter", proc.stdout)

    def test_preflight_warns_when_vendored_proxy_differs_from_installed_dak(self):
        """Preflight must emit [WARN] (without failing exit code) when vendored proxy differs from installed DAK."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env = self._setup_preflight_mocks(
                tmpdir,
                dak_proxy_bytes=b"// Upstream modified DAK proxy bundle\n",
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
                "[WARN] Vendored BigQuery MCP proxy matches installed Data Agent Kit",
                proc.stdout,
            )
            self.assertIn("differs from installed Data Agent Kit proxy", proc.stdout)
            self.assertIn("Summary: 6 passed, 0 failed, 1 warning(s).", proc.stdout)

    def test_vendored_proxy_matches_recorded_upstream_sha256(self):
        """Vendored mcp_proxy_bundle.cjs SHA-256 must match the digest recorded in UPSTREAM.md."""
        digest = hashlib.sha256(VENDORED_PROXY.read_bytes()).hexdigest()
        upstream_text = (PLUGIN_DIR / "UPSTREAM.md").read_text()
        self.assertIn(digest, upstream_text)


if __name__ == "__main__":
    unittest.main()
