"""Guardrail hook dataset checks stay strict except for text-only commands (#55).

The checkpoint and raw/ops checks run on every shell command by default. They are
skipped only when every command in the line is on a small text-only allowlist
(git, gh, echo, cat, ...) and nothing in the line can reach BigQuery, so prose in
commit messages, PR/issue bodies, heredocs into files, and echo/printf is allowed.
"""

import json
import subprocess
import unittest
from typing import Any

from tests.helpers import WORKTREE_ROOT

GUARDRAIL_HOOK = (
    WORKTREE_ROOT
    / ".agents"
    / "plugins"
    / "ds-command-center"
    / "bin"
    / "guardrail-hook"
)

# Prose that ends a sentence with "checkpoint" plus a period, followed by more
# prose that includes an SQL keyword, so whole-string matching reads it as a
# checkpoint table reference and denies it.
PROSE = "Rebuild the staging tables from the last checkpoint. Then rerun triage."
PROSE_DML = "Explain why DELETE FROM raw.hospital_flu_feeds is blocked."

CHECKPOINT_SQL = "SELECT * FROM checkpoint.clean_feeds"
BQ_PY_CHECKPOINT = f"from google.cloud import bigquery; print(list(bigquery.Client().query('{CHECKPOINT_SQL}').result()))"


class TestGuardrailHookBigQueryScoping(unittest.TestCase):
    def _invoke(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        payload = {"toolCall": {"name": tool_name, "args": args}, "stepIdx": 1}
        proc = subprocess.run(
            [str(GUARDRAIL_HOOK)],
            cwd=WORKTREE_ROOT,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return json.loads(proc.stdout)

    def _run_command(self, command_line: str) -> dict[str, Any]:
        return self._invoke("run_command", {"CommandLine": command_line})

    def _assert_denied(self, command_lines: list[str], reason_substr: str):
        for command_line in command_lines:
            with self.subTest(command_line=command_line):
                resp = self._run_command(command_line)
                self.assertEqual(resp.get("decision"), "deny", resp)
                self.assertIn(reason_substr, resp.get("reason", "").lower())

    def test_allows_prose_in_text_only_commands(self):
        """Prose naming the checkpoint or raw/ops DML is allowed in git, gh, cat heredocs, echo and printf."""
        allowed = []
        for prose in (PROSE, PROSE_DML):
            allowed += [
                f'git commit -m "docs: runbook" -m "{prose}"',
                f'gh pr create --title "x" --body "Summary:\n\n{prose}\nDone; ok | fine."',
                f'gh issue create --title "Checkpoint swap" --body "## Context\n{prose}"',
                f"cat > notes.md <<'EOF'\n# Notes\n{prose}\nEOF",
                f"cat > notes.md <<-EOF\n\t{prose}\n\tEOF\necho done",
                f'echo "{prose}"',
                f"printf '%s\\n' \"{prose}\" >> notes.md",
                f'cd /repo && git commit -m "{prose}" && git push -u origin issue049/x 2>&1 | tail -5',
            ]

        for command_line in allowed:
            with self.subTest(command_line=command_line):
                resp = self._run_command(command_line)
                self.assertEqual(resp.get("decision"), "allow", resp)

    def test_unlisted_or_unparsed_commands_keep_the_strict_check(self):
        """Anything outside the text-only allowlist, or that fails to parse, gets the whole-string check."""
        self._assert_denied(
            [
                f'git commit -m "{PROSE}" && make test',
                f'GIT_EDITOR=true git commit -m "{PROSE}"',
                f"gh pr create --body \"$(cat <<'EOF'\n{PROSE}\nEOF\n)\"",
                f"cat > notes.md <<'EOF'\n{PROSE}\n",
                f'echo "{PROSE}" | tee notes.md',
                f'echo "{PROSE}',
                f'git commit -m "Run bq ls, then restore from the {PROSE}"',
            ],
            "checkpoint",
        )

    def test_denies_checkpoint_access_from_bigquery_commands(self):
        """bq, gcloud, BigQuery client interpreters and MCP SQL against checkpoint stay denied."""
        self._assert_denied(
            [
                f'bq query --use_legacy_sql=false "{CHECKPOINT_SQL}"',
                'bq query --use_legacy_sql=false "SELECT *\nFROM checkpoint.clean_feeds"',
                "bq ls demo-proj:checkpoint",
                "bq show demo-proj:checkpoint.clean_feeds",
                "bq head -n 5 demo-proj:checkpoint.clean_feeds",
                f"cat <<'SQL' | bq query --use_legacy_sql=false\n{CHECKPOINT_SQL}\nSQL",
                f"bq query --use_legacy_sql=false <<'SQL'\n{CHECKPOINT_SQL}\nSQL",
                f'python3 -c "{BQ_PY_CHECKPOINT}"',
                f'uv run python -c "{BQ_PY_CHECKPOINT}"',
                (
                    "python3 - <<'PY'\nfrom google.cloud import bigquery\n"
                    f"bigquery.Client().query('{CHECKPOINT_SQL}').result()\nPY"
                ),
                "gcloud alpha bq tables describe clean_feeds --dataset=checkpoint",
                f'git commit -m "{PROSE}" && bq query "{CHECKPOINT_SQL}"',
                f"bash -c 'bq query \"{CHECKPOINT_SQL}\"'",
                f'echo "$(bq query "{CHECKPOINT_SQL}")"',
                "PROJECT_ID=demo-proj bq ls demo-proj:checkpoint",
                f'(cd /repo && bq query "{CHECKPOINT_SQL}")',
                (
                    "curl -X POST https://bigquery.googleapis.com/bigquery/v2/projects/demo-proj/queries "
                    f'-d \'{{"query": "{CHECKPOINT_SQL}"}}\''
                ),
            ],
            "checkpoint",
        )

        mcp_cases = [
            ("execute_sql", {"projectId": "demo-proj", "query": CHECKPOINT_SQL}),
            (
                "execute_sql_readonly",
                {"sql": "SELECT * FROM `demo-proj.checkpoint.clean_feeds`"},
            ),
            ("list_table_ids", {"projectId": "demo-proj", "datasetId": "checkpoint"}),
            (
                "call_mcp_tool",
                {
                    "ServerName": "dak-bigquery",
                    "ToolName": "execute_sql",
                    "Arguments": {"query": CHECKPOINT_SQL},
                },
            ),
        ]
        for tool_name, args in mcp_cases:
            with self.subTest(tool=tool_name, args=args):
                resp = self._invoke(tool_name, args)
                self.assertEqual(resp.get("decision"), "deny", resp)
                self.assertIn("checkpoint", resp.get("reason", "").lower())

    def test_denies_raw_and_ops_mutations_from_bigquery_commands(self):
        """bq cp into raw, DML via bq/heredoc/BigQuery client, and MCP DML against raw/ops stay denied."""
        self._assert_denied(
            [
                "bq cp demo-proj:staging.hospital_flu demo-proj:raw.hospital_flu_feeds",
                'bq query --use_legacy_sql=false "DELETE FROM raw.hospital_flu_feeds WHERE true"',
                'bq query --use_legacy_sql=false "UPDATE ops.pipeline_run_log SET status = 1 WHERE true"',
                (
                    "cat <<'SQL' | bq --dataset_id=raw query --use_legacy_sql=false\n"
                    "DELETE FROM hospital_flu_feeds WHERE true\nSQL"
                ),
                (
                    'python3 -c "from google.cloud import bigquery; '
                    "bigquery.Client().query('TRUNCATE TABLE ops.pipeline_run_log')\""
                ),
                f'git commit -m "{PROSE_DML}"; bq query "DROP TABLE raw.hospital_reference"',
            ],
            "read-only",
        )

        mcp_cases = [
            ("execute_sql", {"query": "INSERT INTO raw.hospital_reference VALUES (1)"}),
            (
                "execute_sql",
                {"sql": "MERGE INTO ops.pipeline_run_log t USING s ON true"},
            ),
        ]
        for tool_name, args in mcp_cases:
            with self.subTest(tool=tool_name, args=args):
                resp = self._invoke(tool_name, args)
                self.assertEqual(resp.get("decision"), "deny", resp)
                self.assertIn("read-only", resp.get("reason", "").lower())

    def test_denies_bigquery_calls_reached_indirectly(self):
        """bq calls behind variables, wrappers, piped scripts, or heredocs followed by || / && stay denied."""
        self._assert_denied(
            [
                f"bq query --use_legacy_sql=false <<'SQL' || true\n{CHECKPOINT_SQL}\nSQL",
                (
                    "python3 - <<'PY' && echo done\nfrom google.cloud import bigquery\n"
                    f"bigquery.Client().query('{CHECKPOINT_SQL}').result()\nPY"
                ),
                f'Q="{CHECKPOINT_SQL}"; bq query --use_legacy_sql=false "$Q"',
                f"SQL=$(cat <<'EOF'\n{CHECKPOINT_SQL}\nEOF\n); bq query \"$SQL\"",
                f"python3 -c \"import subprocess; subprocess.run(['bq', 'query', '{CHECKPOINT_SQL}'])\"",
                f"node -e \"require('child_process').execSync('bq query \\\"{CHECKPOINT_SQL}\\\"')\"",
                f"echo 'bq query \"{CHECKPOINT_SQL}\"' | bash",
                f"bash <<< 'bq query \"{CHECKPOINT_SQL}\"'",
                f'source <(echo bq query \\"{CHECKPOINT_SQL}\\")',
                f'watch -n 5 bq query "{CHECKPOINT_SQL}"',
                f'flock /tmp/bq.lock bq query "{CHECKPOINT_SQL}"',
                f"ssh bastion 'bq query \"{CHECKPOINT_SQL}\"'",
                "find . -name x -exec bq show demo-proj:checkpoint.clean_feeds \\;",
                f'$BQ query "{CHECKPOINT_SQL}"',
                f'$(which bq) query "{CHECKPOINT_SQL}"',
                f'echo x\\ #; bq query "{CHECKPOINT_SQL}"',
                f"git -c alias.x='!bq query \"{CHECKPOINT_SQL}\"' x",
            ],
            "checkpoint",
        )
        self._assert_denied(
            [
                'Q="DELETE FROM raw.hospital_flu_feeds WHERE true"; bq query --use_legacy_sql=false "$Q"',
                "find . -name x -exec bq rm -f -t demo-proj:raw.hospital_reference \\;",
                "echo 'bq query \"DELETE FROM ops.pipeline_run_log WHERE true\"' | bash",
            ],
            "read-only",
        )

    def test_other_guardrails_still_inspect_the_whole_command(self):
        """git push to main and Dataproc --service-account/ShieldedVm checks are unchanged."""
        for command_line, reason_substr in (
            (f'git commit -m "{PROSE}" && git push origin main', "Direct push to main"),
            (
                "gcloud dataproc batches submit pyspark job.py --service-account=sa@p.iam.gserviceaccount.com",
                "ADR 0002",
            ),
            (
                (
                    "gcloud dataproc batches submit pyspark job.py "
                    "--properties=spark.dataproc.ShieldedVm.enableSecureBoot=true"
                ),
                "ShieldedVm",
            ),
        ):
            with self.subTest(command_line=command_line):
                resp = self._run_command(command_line)
                self.assertEqual(resp.get("decision"), "deny", resp)
                self.assertIn(reason_substr, resp.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
