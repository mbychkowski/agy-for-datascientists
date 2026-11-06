"""Evidence Board pieces the stage clone needs (#117).

The stage clone (Window 1) is a clone of this Start Point branch, so the agent
only runs the hooks and rules committed here. The board itself installs from
the presenter repo on `main`; this branch carries just the event recorder hook,
the guardrail's `blocked` recording, rule §6 and the Tile manifest it names.
Real hook payloads are piped through the plugin's hook scripts into a temp
workspace's event log (`<workspace>/.evidence-board/events.jsonl`).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (
    EVIDENCE_BOARD_WORKSPACE_ENV,
    PLUGIN_DIR,
    WORKTREE_ROOT,
    run_plugin_hook,
)

RECORDER = PLUGIN_DIR / "bin" / "event-recorder"
RECORDER_PRE = PLUGIN_DIR / "bin" / "event-recorder-pre"
RECORDER_POST = PLUGIN_DIR / "bin" / "event-recorder-post"
GUARDRAIL = PLUGIN_DIR / "bin" / "guardrail-hook"
RULES = PLUGIN_DIR / "rules" / "AGENTS.md"
MANIFEST_REL = ".agents/plugins/ds-command-center/sidecars/evidence-board/tiles.json"
CONVERSATION = "ec33ebf9-0cba-4100-8142-c61503f6c587"
TRUNCATE_OPS = 'bq query --nouse_legacy_sql "TRUNCATE TABLE ops.pipeline_run_log"'


def payload(name: str, args: dict) -> str:
    """A hook payload for one tool call, shaped as Antigravity sends it."""
    return json.dumps(
        {
            "toolCall": {"name": name, "args": args},
            "stepIdx": 4,
            "conversationId": CONVERSATION,
            "workspacePaths": ["/workspace/project"],
        }
    )


class StageHookCase(unittest.TestCase):
    """A temp workspace the plugin hooks record into."""

    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.env = {**os.environ, EVIDENCE_BOARD_WORKSPACE_ENV: str(self.workspace)}

    def hook(self, script: Path, body: str) -> dict:
        result = run_plugin_hook(script, body, self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def events(self) -> list[dict]:
        path = self.workspace / ".evidence-board" / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


class EventRecorderTest(StageHookCase):
    def test_pre_and_post_record_a_subagent_dispatch_and_always_allow(self) -> None:
        dispatch = payload(
            "invoke_subagent",
            {"TypeName": "pipeline-triage", "Prompt": "Quantify the Pipeline Defect."},
        )

        self.assertEqual(self.hook(RECORDER_PRE, dispatch), {"decision": "allow"})
        self.assertEqual(self.hook(RECORDER_POST, dispatch), {})

        events = self.events()
        self.assertEqual([e["phase"] for e in events], ["pre", "post"])
        self.assertTrue(events[0]["summary"].startswith("pipeline-triage"))
        self.assertEqual(events[0]["conversationId"], CONVERSATION)

    def test_malformed_payloads_are_allowed(self) -> None:
        for body in ("", "not json", "[1, 2]", "{"):
            with self.subTest(body=body):
                self.assertEqual(self.hook(RECORDER_PRE, body), {"decision": "allow"})
                self.assertEqual(self.hook(RECORDER_POST, body), {})


class GuardrailBlockedEventTest(StageHookCase):
    def test_guardrail_deny_is_recorded_as_a_blocked_event(self) -> None:
        decision = self.hook(
            GUARDRAIL, payload("run_command", {"CommandLine": TRUNCATE_OPS})
        )

        self.assertEqual(decision["decision"], "deny")
        [event] = self.events()
        self.assertEqual(event["phase"], "blocked")
        self.assertIn("raw and ops are strictly read-only", event["reason"])

    def test_allowed_calls_record_nothing_from_the_guardrail(self) -> None:
        decision = self.hook(
            GUARDRAIL, payload("run_command", {"CommandLine": "bq ls staging"})
        )

        self.assertEqual(decision["decision"], "allow")
        self.assertEqual(self.events(), [])


class StageContractTest(unittest.TestCase):
    def test_recorder_is_registered_for_pre_and_post_tool_use(self) -> None:
        hooks = json.loads((PLUGIN_DIR / "hooks.json").read_text("utf-8"))
        recorder = hooks["ds-command-center-evidence-board"]

        self.assertEqual(
            recorder["PreToolUse"][0]["hooks"][0]["command"], "./bin/event-recorder-pre"
        )
        self.assertEqual(
            recorder["PostToolUse"][0]["hooks"][0]["command"],
            "./bin/event-recorder-post",
        )
        for script in (RECORDER_PRE, RECORDER_POST):
            self.assertTrue(os.access(script, os.X_OK), script)
            self.assertEqual(script.resolve(), RECORDER, "one script serves both")

    def test_event_log_is_gitignored(self) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".evidence-board/events.jsonl"],
            cwd=WORKTREE_ROOT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, ".evidence-board/ must be gitignored")

    def test_rule_6_names_a_tile_manifest_that_exists(self) -> None:
        rules = RULES.read_text("utf-8")

        self.assertIn("## 6. Evidence Board", rules)
        self.assertIn(MANIFEST_REL, rules)
        tiles = json.loads((WORKTREE_ROOT / MANIFEST_REL).read_text("utf-8"))["tiles"]
        self.assertEqual(
            [t["id"] for t in tiles],
            ["opening", "1a", "1b", "1c", "2a", "2b", "2c", "2d"],
        )

    def test_segment_2d_skill_is_not_shipped(self) -> None:
        """The agent writes cohort-forecast-refresh live in Segment 2D, on both Start Points."""
        skill = PLUGIN_DIR / "skills" / "cohort-forecast-refresh"
        self.assertFalse(skill.exists(), skill)
        plugin = json.loads((PLUGIN_DIR / "plugin.json").read_text("utf-8"))
        self.assertNotIn("skills", plugin)


if __name__ == "__main__":
    unittest.main()
