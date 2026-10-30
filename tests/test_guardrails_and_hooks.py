import json
import os
import subprocess
import unittest

from tests.helpers import WORKTREE_ROOT

HOOKS_JSON = WORKTREE_ROOT / ".agents" / "hooks.json"
HOOK_BIN = WORKTREE_ROOT / "bin" / "agent-pre-command-hook"
PRE_COMMIT = WORKTREE_ROOT / ".husky" / "pre-commit"


class TestGuardrailsAndHooks(unittest.TestCase):
    def test_hooks_json_and_scripts_exist_and_executable(self):
        """.agents/hooks.json, bin/agent-pre-command-hook, and .husky/pre-commit must exist and be executable."""
        self.assertTrue(HOOKS_JSON.exists(), ".agents/hooks.json must exist")
        self.assertTrue(HOOK_BIN.exists(), "bin/agent-pre-command-hook must exist")
        self.assertTrue(
            os.access(HOOK_BIN, os.X_OK),
            "bin/agent-pre-command-hook must be executable",
        )
        self.assertTrue(PRE_COMMIT.exists(), ".husky/pre-commit must exist")
        self.assertTrue(
            os.access(PRE_COMMIT, os.X_OK),
            ".husky/pre-commit must be executable",
        )

        hooks_cfg = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.assertIn("command-center-guardrails", hooks_cfg)
        pre_tool = hooks_cfg["command-center-guardrails"]["PreToolUse"]
        self.assertEqual(pre_tool[0]["matcher"], "run_command")
        self.assertEqual(
            pre_tool[0]["hooks"][0]["command"], "../bin/agent-pre-command-hook"
        )

        pre_commit_text = PRE_COMMIT.read_text(encoding="utf-8")
        self.assertIn("uvx ruff check .", pre_commit_text)
        self.assertIn("uvx ruff format --check .", pre_commit_text)
        self.assertIn("make test", pre_commit_text)

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
            cwd=WORKTREE_ROOT / ".agents",
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
