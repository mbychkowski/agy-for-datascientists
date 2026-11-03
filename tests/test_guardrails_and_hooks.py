import json
import os
import subprocess
import unittest

from tests.helpers import WORKTREE_ROOT

PLUGIN_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "ds-command-center"
PLUGIN_HOOKS_JSON = PLUGIN_DIR / "hooks.json"
HOOK_BIN = PLUGIN_DIR / "bin" / "guardrail-hook"
PRE_COMMIT = WORKTREE_ROOT / ".husky" / "pre-commit"


class TestGuardrailsAndHooks(unittest.TestCase):
    def test_pre_commit_exists_and_runs_verification_guardrail(self):
        """.husky/pre-commit must exist, be executable, and run ruff and make test."""
        self.assertTrue(PRE_COMMIT.exists(), ".husky/pre-commit must exist")
        self.assertTrue(
            os.access(PRE_COMMIT, os.X_OK),
            ".husky/pre-commit must be executable",
        )

        pre_commit_text = PRE_COMMIT.read_text(encoding="utf-8")
        self.assertIn("uvx ruff check .", pre_commit_text)
        self.assertIn("uvx ruff format --check .", pre_commit_text)
        self.assertIn("make test", pre_commit_text)

    def test_plugin_guardrail_hook_is_the_only_pre_tool_use_hook(self):
        """The ds-command-center plugin hook is the only PreToolUse hook; no workspace-level duplicate exists."""
        hook_configs = sorted(
            p.relative_to(WORKTREE_ROOT).as_posix()
            for p in (WORKTREE_ROOT / ".agents").rglob("hooks.json")
        )
        self.assertEqual(
            hook_configs,
            [PLUGIN_HOOKS_JSON.relative_to(WORKTREE_ROOT).as_posix()],
            "Only the ds-command-center plugin may register PreToolUse hooks",
        )
        self.assertTrue(HOOK_BIN.exists(), "plugin bin/guardrail-hook must exist")
        self.assertTrue(
            os.access(HOOK_BIN, os.X_OK),
            "plugin bin/guardrail-hook must be executable",
        )

        hooks_cfg = json.loads(PLUGIN_HOOKS_JSON.read_text(encoding="utf-8"))
        pre_tool = hooks_cfg["ds-command-center-guardrails"]["PreToolUse"]
        self.assertEqual(len(pre_tool), 1)
        self.assertEqual(pre_tool[0]["matcher"], "*")
        self.assertEqual(pre_tool[0]["hooks"][0]["command"], "./bin/guardrail-hook")

    def _run_hook(self, command_line: str) -> dict[str, str]:
        payload = json.dumps(
            {
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": command_line},
                }
            }
        )
        proc = subprocess.run(
            [str(HOOK_BIN)],
            cwd=PLUGIN_DIR,
            input=payload,
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(proc.stdout)

    def test_hook_denies_direct_git_push_to_main(self):
        """PreToolUse hook must deny direct git push to origin main."""
        for blocked_cmd in (
            "git push origin main",
            "cd /repo && git -c credential.helper='!gh auth git-credential' push origin main",
        ):
            res = self._run_hook(blocked_cmd)
            self.assertEqual(
                res.get("decision"), "deny", f"Expected deny for {blocked_cmd}"
            )
            self.assertIn("Direct push to main is blocked", res.get("reason", ""))

    def test_hook_allows_feature_branch_git_push(self):
        """PreToolUse hook must allow pushing feature branches."""
        res = self._run_hook("git push -u origin issue005/dataproc-mcp-plugin")
        self.assertEqual(res.get("decision"), "allow")

    def test_hook_denies_service_account_and_shielded_vm_props_on_dataproc_submit(self):
        """PreToolUse hook must deny --service-account and spark.dataproc.ShieldedVm on Dataproc Serverless batches."""
        sa_res = self._run_hook(
            "gcloud dataproc batches submit pyspark job.py --service-account=sa@proj.iam.gserviceaccount.com"
        )
        self.assertEqual(sa_res.get("decision"), "deny")
        self.assertIn("ADR 0002", sa_res.get("reason", ""))

        shielded_res = self._run_hook(
            "gcloud dataproc batches submit pyspark job.py --properties=spark.dataproc.ShieldedVm.enableSecureBoot=true"
        )
        self.assertEqual(shielded_res.get("decision"), "deny")
        self.assertIn("ShieldedVm", shielded_res.get("reason", ""))

        clean_res = self._run_hook(
            "gcloud dataproc batches submit pyspark job.py --version=3.0 --subnet=demo-dataproc-subnet"
        )
        self.assertEqual(clean_res.get("decision"), "allow")


if __name__ == "__main__":
    unittest.main()
