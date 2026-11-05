"""Guardrail hook text checks stay strict except for text-only commands (#55, #67).

The checkpoint and raw/ops checks run on every shell command by default. They are
skipped only when every command in the line is on a small text-only allowlist
(git, gh, echo, cat, ...) and nothing in the line can reach BigQuery, so prose in
commit messages, PR/issue bodies, heredocs into files, and echo/printf is allowed.

The Dataproc --service-account and ShieldedVm checks are skipped for the same
text-only lines, so prose can name the batch-submit command with those flags; a
real submit, chained or wrapped, is still denied.
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

# Prose that names the Dataproc batch-submit command next to a flag the ADR 0002
# and ShieldedVm checks deny, as in the #64-#66 ticket bodies.
DATAPROC_SA_PROSE = (
    "The agent runs gcloud dataproc batches submit as the presenter, "
    "never with --service-account (ADR 0002)."
)
DATAPROC_SHIELDED_PROSE = (
    "gcloud dataproc batches submit rejects spark.dataproc.ShieldedVm.enableSecureBoot, "
    "so never pass it."
)

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

    def _assert_allowed(self, command_lines: list[str]):
        for command_line in command_lines:
            with self.subTest(command_line=command_line):
                resp = self._run_command(command_line)
                self.assertEqual(resp.get("decision"), "allow", resp)

    def _assert_denied(self, command_lines: list[str], reason_substr: str):
        for command_line in command_lines:
            with self.subTest(command_line=command_line):
                resp = self._run_command(command_line)
                self.assertEqual(resp.get("decision"), "deny", resp)
                self.assertIn(reason_substr, resp.get("reason", "").lower())

    def _assert_mcp_denied(
        self, mcp_cases: list[tuple[str, dict[str, Any]]], reason_substr: str
    ):
        for tool_name, args in mcp_cases:
            with self.subTest(tool=tool_name, args=args):
                resp = self._invoke(tool_name, args)
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

        self._assert_allowed(allowed)

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

        self._assert_mcp_denied(
            [
                ("execute_sql", {"projectId": "demo-proj", "query": CHECKPOINT_SQL}),
                (
                    "execute_sql_readonly",
                    {"sql": "SELECT * FROM `demo-proj.checkpoint.clean_feeds`"},
                ),
                (
                    "list_table_ids",
                    {"projectId": "demo-proj", "datasetId": "checkpoint"},
                ),
                (
                    "call_mcp_tool",
                    {
                        "ServerName": "dak-bigquery",
                        "ToolName": "execute_sql",
                        "Arguments": {"query": CHECKPOINT_SQL},
                    },
                ),
            ],
            "checkpoint",
        )

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

        self._assert_mcp_denied(
            [
                (
                    "execute_sql",
                    {"query": "INSERT INTO raw.hospital_reference VALUES (1)"},
                ),
                (
                    "execute_sql",
                    {"sql": "MERGE INTO ops.pipeline_run_log t USING s ON true"},
                ),
            ],
            "read-only",
        )

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
                f'echo hi # <<EOF\nb""q query "{CHECKPOINT_SQL}"\nEOF',
                f'git -c alias.x=\'!b""q query "{CHECKPOINT_SQL}"\' x',
                f"git -c alias.x='!$BQ query \"{CHECKPOINT_SQL}\"' x",
                f'git rebase -x \'b""q query "{CHECKPOINT_SQL}"\' HEAD~1',
                f'gh alias set -s x \'b""q query "{CHECKPOINT_SQL}"\'',
                f"printf '%s\\n' 'b\"\"q query \"{CHECKPOINT_SQL}\"' >> .husky/pre-commit && git commit -m x",
                f'echo hi && b\\q query "{CHECKPOINT_SQL}"',
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

    def test_allows_dataproc_flags_named_in_text_only_prose(self):
        """Prose naming the batch-submit command with --service-account or ShieldedVm is allowed (#67)."""
        allowed = []
        for prose in (DATAPROC_SA_PROSE, DATAPROC_SHIELDED_PROSE):
            allowed += [
                f'gh issue create --title "Two-window demo" --body "## Context\\n{prose}"',
                f'gh pr create --title "x" --body "Summary:\\n\\n{prose}\\nDone; ok | fine."',
                f'git commit -m "docs: runbook" -m "{prose}"',
                f"cat > notes.md <<'EOF'\n# Notes\n{prose}\nEOF",
                f'echo "{prose}"',
                f'git add -A && git commit -m "{prose}"',
            ]

        self._assert_allowed(allowed)

    def test_denies_real_dataproc_submits_with_blocked_flags(self):
        """Real batch submits with --service-account or ShieldedVm stay denied when chained or wrapped (#67)."""
        for flag, reason_substr in (
            ("--service-account=sa@p.iam.gserviceaccount.com", "adr 0002"),
            (
                "--properties=spark.dataproc.ShieldedVm.enableSecureBoot=true",
                "shieldedvm",
            ),
        ):
            submit = f"gcloud dataproc batches submit pyspark job.py {flag}"
            self._assert_denied(
                [
                    submit,
                    f'git commit -m "x" && {submit}',
                    f'echo "starting"; {submit}',
                    f"cd /repo || {submit}",
                    f"bash -c '{submit}'",
                    f"echo '{submit}' | bash",
                    f'echo "$({submit})"',
                    f"git config alias.x '!{submit}'",
                    f"echo $'a\\'' ; {submit} #'",
                    f"git rebase -x'{submit}' HEAD~1",
                    f"git difftool --extcmd='{submit}' HEAD",
                    f"git grep -O'{submit}' foo",
                    f"git ls-remote --upload-pack='{submit}; git-upload-pack' .",
                    f"gh codespace ssh -- {submit}",
                    f"cat <<'EOF'\nx\\\nEOF\n{submit}\nEOF",
                    f"cat <<EOF\nx\\\nEOF\n{submit}\nEOF",
                    f"echo '{submit}' > .hu\\sky/pre-commit && git commit -m x",
                    f"cat > .hu''sky/pre-commit <<'EOF'\n{submit}\nEOF\ngit commit -m x",
                ],
                reason_substr,
            )

    def test_other_guardrails_still_inspect_the_whole_command(self):
        """git push to main is unchanged, and plain Dataproc submits with blocked flags stay denied."""
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
