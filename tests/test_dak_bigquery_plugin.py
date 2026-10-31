import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import PREFLIGHT_BIN, WORKTREE_ROOT, setup_preflight_test_env

PLUGIN_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "dak-bigquery"
WRAPPER_BIN = PLUGIN_DIR / "bin" / "run-bigquery-mcp"
VENDORED_PROXY = PLUGIN_DIR / "mcp" / "bin" / "mcp_proxy_bundle.cjs"


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
        """run-bigquery-mcp must source demo.env, set BILLING_QUOTA_PROJECT_ID and GOOGLE_APPLICATION_CREDENTIALS, and launch the vendored proxy."""
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
            env["CLOUDSDK_CONFIG"] = str(Path(tmpdir) / "custom-gcloud")

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
            self.assertIn(
                f"GOOGLE_APPLICATION_CREDENTIALS={tmpdir}/custom-gcloud/application_default_credentials.json",
                proc.stdout,
            )
            self.assertIn("ENDPOINT=https://bigquery.googleapis.com/mcp", proc.stdout)

    def test_proxy_bundle_stdio_jsonrpc_roundtrip(self):
        """Launching run-bigquery-mcp with mcp_proxy_bundle.cjs must authenticate via presenter ADC and forward JSON-RPC over stdio with X-Goog-User-Project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env_file = tmp_path / "demo.env"
            env_file.write_text("""
PROJECT_ID="presenter-demo-proj"
REGION="us-central1"
STAGING_BUCKET="presenter-staging"
STATE_BUCKET="presenter-state"
export PROJECT_ID REGION STAGING_BUCKET STATE_BUCKET
""")
            adc_file = tmp_path / "adc.json"
            adc_file.write_text(
                json.dumps(
                    {
                        "type": "authorized_user",
                        "client_id": "presenter-client-id",
                        "client_secret": "presenter-client-secret",
                        "refresh_token": "presenter-refresh-token",
                        "quota_project_id": "presenter-demo-proj",
                    }
                )
            )
            fetch_log = tmp_path / "fetch_calls.json"
            preload_cjs = tmp_path / "preload_fetch.cjs"
            preload_cjs.write_text(
                f"""
const fs = require("fs");
const calls = [];
globalThis.fetch = async (url, opts = {{}}) => {{
  const urlStr = String(url);
  calls.push({{ url: urlStr, headers: opts.headers || {{}}, body: opts.body || "" }});
  fs.writeFileSync({json.dumps(str(fetch_log))}, JSON.stringify(calls, null, 2));
  if (urlStr === "https://oauth2.googleapis.com/token") {{
    return {{
      ok: true,
      status: 200,
      json: async () => ({{ access_token: "ya29.presenter-oauth-token", expires_in: 3600 }}),
      text: async () => JSON.stringify({{ access_token: "ya29.presenter-oauth-token", expires_in: 3600 }}),
    }};
  }}
  if (urlStr === "https://bigquery.googleapis.com/mcp") {{
    const req = JSON.parse(opts.body);
    const resp = JSON.stringify({{
      jsonrpc: "2.0",
      id: req.id,
      result: {{ tools: [{{ name: "execute_sql" }}, {{ name: "list_dataset_ids" }}] }},
    }});
    return {{
      ok: true,
      status: 200,
      text: async () => resp,
      json: async () => JSON.parse(resp),
    }};
  }}
  throw new Error("Unexpected URL in test: " + urlStr);
}};
""",
                encoding="utf-8",
            )

            env = os.environ.copy()
            env["GOOGLE_APPLICATION_CREDENTIALS"] = str(adc_file)
            env["NODE_OPTIONS"] = f"--require {preload_cjs}"

            with subprocess.Popen(
                [str(WRAPPER_BIN), "--env", str(env_file)],
                cwd=WORKTREE_ROOT,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as proc:
                assert proc.stdin is not None
                assert proc.stdout is not None
                assert proc.stderr is not None
                request_line = (
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/list",
                            "params": {},
                        }
                    )
                    + "\n"
                )
                proc.stdin.write(request_line)
                proc.stdin.flush()
                response_line = proc.stdout.readline()
                proc.stdin.close()
                proc.stdout.close()
                proc.stderr.close()
                proc.terminate()
                proc.wait(timeout=5)

            resp_obj = json.loads(response_line)
            self.assertEqual(resp_obj["id"], 1)
            tool_names = [t["name"] for t in resp_obj["result"]["tools"]]
            self.assertIn("execute_sql", tool_names)

            recorded_calls = json.loads(fetch_log.read_text(encoding="utf-8"))
            urls = [c["url"] for c in recorded_calls]
            self.assertIn("https://oauth2.googleapis.com/token", urls)
            self.assertIn("https://bigquery.googleapis.com/mcp", urls)
            self.assertFalse(
                any("metadata.google.internal" in u for u in urls),
                "Proxy must never call compute metadata server when presenter ADC is configured",
            )

            mcp_call = next(
                c
                for c in recorded_calls
                if c["url"] == "https://bigquery.googleapis.com/mcp"
            )
            self.assertEqual(
                mcp_call["headers"].get("Authorization"),
                "Bearer ya29.presenter-oauth-token",
            )
            self.assertEqual(
                mcp_call["headers"].get("X-Goog-User-Project"),
                "presenter-demo-proj",
            )

    def test_preflight_fails_when_adc_triggers_compute_metadata_fallback(self):
        """Preflight must fail if ADC lacks user OAuth fields or is a service_account (preventing silent metadata fallback)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
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

    def test_preflight_fails_when_adc_token_refresh_fails(self):
        """Preflight must fail if ADC refresh_token is expired or revoked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                token_fails=True,
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
            self.assertIn("ADC refresh token is expired or revoked", proc.stdout)

    def test_preflight_fails_when_active_account_is_compute_service_account(self):
        """Preflight must fail if active gcloud account is a compute service account."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
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
            env_file, env, _ = setup_preflight_test_env(
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
            self.assertIn("Summary: 12 passed, 0 failed, 1 warning(s).", proc.stdout)

    def test_preflight_warns_when_installed_dak_is_missing(self):
        """Preflight must emit [WARN] when installed Data Agent Kit proxy is absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            env_file, env, _ = setup_preflight_test_env(
                tmpdir,
                missing_dak_proxy=True,
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
            self.assertIn("Installed Data Agent Kit proxy not found", proc.stdout)

    def test_vendored_proxy_matches_recorded_upstream_sha256(self):
        """Vendored mcp_proxy_bundle.cjs SHA-256 must match the digest recorded in UPSTREAM.md."""
        digest = hashlib.sha256(VENDORED_PROXY.read_bytes()).hexdigest()
        upstream_text = (PLUGIN_DIR / "UPSTREAM.md").read_text()
        self.assertIn(digest, upstream_text)


if __name__ == "__main__":
    unittest.main()
