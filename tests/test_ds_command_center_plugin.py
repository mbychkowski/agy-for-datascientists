import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.helpers import PREFLIGHT_BIN, WORKTREE_ROOT, setup_preflight_test_env

PLUGIN_DIR = WORKTREE_ROOT / ".agents" / "plugins" / "ds-command-center"
GUARDRAIL_HOOK = PLUGIN_DIR / "bin" / "guardrail-hook"
PRE_COMMAND_HOOK = WORKTREE_ROOT / "bin" / "agent-pre-command-hook"


class TestDsCommandCenterPlugin(unittest.TestCase):
    def _invoke_hook(
        self,
        tool_name: str,
        args: dict[str, Any],
        hook_bin: Path = GUARDRAIL_HOOK,
    ) -> dict[str, Any]:
        payload = {
            "toolCall": {
                "name": tool_name,
                "args": args,
            },
            "stepIdx": 1,
        }
        proc = subprocess.run(
            [str(hook_bin)],
            cwd=WORKTREE_ROOT,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"Hook {hook_bin} exited with {proc.returncode}: {proc.stderr}",
        )
        return json.loads(proc.stdout)

    def test_plugin_structure_and_distinction_from_dak(self):
        """ds-command-center must exist as a distinct plugin from dak-bigquery with registered skills and guardrail hook."""
        plugin_manifest = PLUGIN_DIR / "plugin.json"
        self.assertTrue(plugin_manifest.exists(), "plugin.json must exist")
        manifest = json.loads(plugin_manifest.read_text(encoding="utf-8"))
        self.assertEqual(manifest.get("name"), "ds-command-center")
        self.assertNotEqual(manifest.get("name"), "dak-bigquery")

        plugins_json = WORKTREE_ROOT / ".agents" / "plugins.json"
        self.assertTrue(plugins_json.exists(), ".agents/plugins.json must exist")
        plugins_cfg = json.loads(plugins_json.read_text(encoding="utf-8"))
        plugin_paths = [e.get("path") for e in plugins_cfg.get("entries", [])]
        self.assertTrue(
            ".agents/plugins" in plugin_paths
            or ".agents/plugins/ds-command-center" in plugin_paths,
            "ds-command-center must be registered via .agents/plugins.json",
        )

        skills_json = WORKTREE_ROOT / ".agents" / "skills.json"
        self.assertTrue(skills_json.exists(), ".agents/skills.json must exist")
        skills_cfg = json.loads(skills_json.read_text(encoding="utf-8"))
        skill_paths = [e.get("path") for e in skills_cfg.get("entries", [])]
        self.assertIn(
            ".agents/plugins/ds-command-center/skills",
            skill_paths,
            ".agents/plugins/ds-command-center/skills must be registered in .agents/skills.json",
        )
        self.assertTrue(
            (PLUGIN_DIR / "skills").is_dir(),
            ".agents/plugins/ds-command-center/skills directory must exist",
        )

        hooks_json = PLUGIN_DIR / "hooks.json"
        self.assertTrue(hooks_json.exists(), "hooks.json must exist in plugin root")
        hooks_cfg = json.loads(hooks_json.read_text(encoding="utf-8"))
        self.assertIn("guardrail-hook", json.dumps(hooks_cfg))

        self.assertTrue(GUARDRAIL_HOOK.exists(), "bin/guardrail-hook must exist")
        self.assertTrue(
            os.access(GUARDRAIL_HOOK, os.X_OK),
            "bin/guardrail-hook must be executable",
        )
        self.assertTrue(
            PRE_COMMAND_HOOK.exists(), "bin/agent-pre-command-hook must exist"
        )
        self.assertTrue(
            os.access(PRE_COMMAND_HOOK, os.X_OK),
            "bin/agent-pre-command-hook must be executable",
        )

    def test_plugin_rules_cover_project_region_skills_and_readonly_datasets(self):
        """rules/AGENTS.md must instruct agents on explicit PROJECT_ID/REGION, skills path, read-only raw/ops, and forbidden checkpoint."""
        rules_file = PLUGIN_DIR / "rules" / "AGENTS.md"
        self.assertTrue(rules_file.exists(), "rules/AGENTS.md must exist")
        content = rules_file.read_text(encoding="utf-8")

        self.assertIn("PROJECT_ID", content)
        self.assertIn("REGION", content)
        self.assertIn(".agents/plugins/ds-command-center/skills", content)
        self.assertIn("raw", content)
        self.assertIn("ops", content)
        self.assertIn("read-only", content.lower())
        self.assertIn("SELECT", content)
        self.assertIn("checkpoint", content)

    def test_hook_blocks_dml_and_ddl_on_raw_and_ops_via_bq_and_mcp_with_readonly_reason(
        self,
    ):
        """Guardrail hook must block DML/DDL against raw and ops across bq CLI and MCP tools with a read-only reason."""
        blocked_cases = [
            (
                "run_command",
                {
                    "CommandLine": 'bq query --use_legacy_sql=false "DROP TABLE raw.hospital_flu_feeds"'
                },
            ),
            (
                "run_command",
                {
                    "CommandLine": 'bq query "DELETE FROM `demo-proj.ops.pipeline_run_log` WHERE true"'
                },
            ),
            (
                "run_command",
                {"CommandLine": "bq rm -f -t demo-proj:raw.hospital_flu_feeds"},
            ),
            (
                "run_command",
                {
                    "CommandLine": "bq load --replace demo-proj:ops.pipeline_run_log data.csv"
                },
            ),
            (
                "mcp_dak-bigquery_execute_sql",
                {
                    "projectId": "demo-proj",
                    "query": "UPDATE raw.hospital_reference SET bed_count = 0 WHERE true",
                },
            ),
            (
                "execute_sql",
                {
                    "projectId": "demo-proj",
                    "query": "INSERT INTO ops.pipeline_run_log VALUES (...)",
                },
            ),
            (
                "call_mcp_tool",
                {
                    "ServerName": "dak-bigquery",
                    "ToolName": "execute_sql",
                    "Arguments": {
                        "projectId": "demo-proj",
                        "query": "TRUNCATE TABLE raw.hospital_flu_feeds",
                    },
                },
            ),
            (
                "execute_sql",
                {
                    "projectId": "demo-proj",
                    "query": "CREATE OR REPLACE TABLE `demo-proj.raw.hospital_flu_feeds` AS SELECT 1",
                },
            ),
            (
                "run_command",
                {"CommandLine": 'bq rm -f -t "${PROJECT_ID}:raw.hospital_flu_feeds"'},
            ),
            (
                "run_command",
                {
                    "CommandLine": 'bq cp "${PROJECT_ID}:staging.t" "${PROJECT_ID}:raw.t"'
                },
            ),
            (
                "run_command",
                {
                    "CommandLine": 'bq query --project_id="${PROJECT_ID}" "DROP TABLE `${PROJECT_ID}.raw.hospital_flu_feeds`"'
                },
            ),
            (
                "run_command",
                {
                    "CommandLine": "bq rm \\\n  -f -t \\\n  demo-proj:raw.hospital_flu_feeds"
                },
            ),
            (
                "run_command",
                {
                    "CommandLine": 'bq --dataset_id=raw query "SELECT 1; DROP TABLE hospital_flu_feeds"'
                },
            ),
            (
                "run_command",
                {
                    "CommandLine": 'bq --dataset_id=raw query "CREATE OR REPLACE\nTABLE hospital_flu_feeds AS SELECT 1"'
                },
            ),
        ]

        for hook_bin in (GUARDRAIL_HOOK, PRE_COMMAND_HOOK):
            for tool_name, args in blocked_cases:
                with self.subTest(hook=hook_bin.name, tool=tool_name, args=args):
                    resp = self._invoke_hook(tool_name, args, hook_bin=hook_bin)
                    self.assertEqual(resp.get("decision"), "deny")
                    reason = resp.get("reason", "")
                    self.assertIn("read-only", reason.lower())
                    self.assertIn("select", reason.lower())

    def test_hook_allows_read_queries_on_raw_and_ops_and_writes_to_working_datasets(
        self,
    ):
        """Guardrail hook must allow SELECT queries on raw/ops and writes to working datasets like staging and features."""
        allowed_cases = [
            (
                "execute_sql",
                {
                    "projectId": "demo-proj",
                    "query": "SELECT hospital_id, COUNT(*) FROM raw.hospital_flu_feeds GROUP BY 1",
                },
            ),
            (
                "execute_sql_readonly",
                {
                    "projectId": "demo-proj",
                    "query": "SELECT * FROM ops.pipeline_run_log WHERE run_type = 'backfill'",
                },
            ),
            (
                "run_command",
                {
                    "CommandLine": 'bq query --use_legacy_sql=false "SELECT * FROM raw.hospital_reference"'
                },
            ),
            (
                "run_command",
                {"CommandLine": "bq show demo-proj:raw.hospital_flu_feeds"},
            ),
            (
                "execute_sql",
                {
                    "projectId": "demo-proj",
                    "query": "CREATE OR REPLACE TABLE staging.cleaned_feeds AS SELECT * FROM raw.hospital_flu_feeds",
                },
            ),
            (
                "execute_sql",
                {
                    "projectId": "demo-proj",
                    "query": "INSERT INTO features.hospital_cohorts SELECT * FROM raw.hospital_reference",
                },
            ),
        ]

        for hook_bin in (GUARDRAIL_HOOK, PRE_COMMAND_HOOK):
            for tool_name, args in allowed_cases:
                with self.subTest(hook=hook_bin.name, tool=tool_name, args=args):
                    resp = self._invoke_hook(tool_name, args, hook_bin=hook_bin)
                    self.assertEqual(resp.get("decision"), "allow")

    def test_hook_blocks_agent_reads_of_checkpoint_dataset_across_mcp_and_bq(self):
        """Guardrail hook must block any agent access to the checkpoint dataset across MCP and bq CLI."""
        checkpoint_cases = [
            (
                "execute_sql",
                {
                    "projectId": "demo-proj",
                    "query": "SELECT * FROM checkpoint.workstream_1",
                },
            ),
            (
                "execute_sql_readonly",
                {
                    "projectId": "demo-proj",
                    "query": "SELECT * FROM `demo-proj.checkpoint.forecasts`",
                },
            ),
            (
                "get_table_info",
                {
                    "projectId": "demo-proj",
                    "datasetId": "checkpoint",
                    "tableId": "workstream_1",
                },
            ),
            (
                "list_table_ids",
                {"projectId": "demo-proj", "datasetId": "checkpoint"},
            ),
            (
                "get_dataset_info",
                {"projectId": "demo-proj", "datasetId": "checkpoint"},
            ),
            (
                "run_command",
                {"CommandLine": 'bq query "SELECT * FROM checkpoint.step1"'},
            ),
            (
                "run_command",
                {"CommandLine": "bq show demo-proj:checkpoint.step1"},
            ),
            (
                "run_command",
                {"CommandLine": "bq ls demo-proj:checkpoint"},
            ),
            (
                "run_command",
                {"CommandLine": 'bq ls "${PROJECT_ID}:checkpoint"'},
            ),
            (
                "run_command",
                {
                    "CommandLine": "bq ls \\\n  --project_id=demo-proj \\\n  demo-proj:checkpoint"
                },
            ),
        ]

        for hook_bin in (GUARDRAIL_HOOK, PRE_COMMAND_HOOK):
            for tool_name, args in checkpoint_cases:
                with self.subTest(hook=hook_bin.name, tool=tool_name, args=args):
                    resp = self._invoke_hook(tool_name, args, hook_bin=hook_bin)
                    self.assertEqual(resp.get("decision"), "deny")
                    reason = resp.get("reason", "")
                    self.assertIn("checkpoint", reason.lower())
                    self.assertIn("read-only", reason.lower())

    def test_preflight_verifies_ds_command_center_guardrails_and_fails_if_broken(self):
        """preflight must verify ds-command-center plugin rules and guardrail hook enforce dataset boundaries."""
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
                proc.returncode, 0, f"Output:\n{proc.stdout}\n{proc.stderr}"
            )
            self.assertIn(
                "[PASS] ds-command-center plugin rules and guardrail hook enforce dataset boundaries",
                proc.stdout,
            )


if __name__ == "__main__":
    unittest.main()
