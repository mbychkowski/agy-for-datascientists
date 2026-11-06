"""Evidence Board event recorder hook and in-progress Tiles (#92).

Primary seam from spec #88: real hook payloads are piped through the event
recorder hook (and the guardrail hook, for denies) into a temp workspace's
event log, and Tile states are asserted through `GET /api/tiles` with a fake
table catalog. Hook safety is tested at the hook seam: the recorder as a
process, fed malformed, huge and hostile payloads.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import EVIDENCE_BOARD_WORKSPACE_ENV as WORKSPACE_ENV
from tests.helpers import PLUGIN_DIR, WORKTREE_ROOT, run_plugin_hook

RECORDER = PLUGIN_DIR / "bin" / "event-recorder"
RECORDER_PRE = PLUGIN_DIR / "bin" / "event-recorder-pre"
RECORDER_POST = PLUGIN_DIR / "bin" / "event-recorder-post"
GUARDRAIL = PLUGIN_DIR / "bin" / "guardrail-hook"
BOARD_DIR = PLUGIN_DIR / "sidecars" / "evidence-board"
MANIFEST_PATH = BOARD_DIR / "tiles.json"

if str(BOARD_DIR) not in sys.path:
    sys.path.insert(0, str(BOARD_DIR))

from board.app import create_app
from board.catalog import FakeCatalog
from board.events import EventLog, event_log_path
from board.manifest import ManifestError, load_manifest, parse_manifest
from board.service import Board
from fastapi.testclient import TestClient

CONVERSATION = "ec33ebf9-0cba-4100-8142-c61503f6c587"
TRIAGE = ["distribution-triage", "sampling-triage", "pipeline-triage"]
SPIKE_ROWS = [{"week_end": "2026-10-31", "positive_flu_tests": 540, "wow_pct": 35.0}]


def _payload(name: str, args: dict, **extra: object) -> str:
    return json.dumps(
        {
            "toolCall": {"name": name, "args": args},
            "stepIdx": 4,
            "conversationId": CONVERSATION,
            "workspacePaths": ["/workspace/project"],
            **extra,
        }
    )


def _triage_payload(type_name: str) -> str:
    return _payload(
        "invoke_subagent",
        {
            "TypeName": type_name,
            "Role": type_name.replace("-", " ").title(),
            "Prompt": "Investigate the +35% Northeast Spike in staging.hospital_flu.",
        },
    )


class WorkspaceCase(unittest.TestCase):
    """A temp workspace that hooks record into and the board reads from."""

    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.env = {**os.environ, WORKSPACE_ENV: str(self.workspace)}
        self.catalog = FakeCatalog()

    def hook(
        self, script: Path, payload: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess:
        result = run_plugin_hook(script, payload, env or self.env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def events(self) -> list[dict]:
        path = event_log_path(self.workspace)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text("utf-8").splitlines()]

    def tiles(self) -> dict[str, dict]:
        board = Board(
            load_manifest(MANIFEST_PATH),
            self.catalog,
            refresh_interval=0.0,
            events=EventLog(event_log_path(self.workspace)),
            event_interval=0.0,
        )
        response = TestClient(create_app(board)).get("/api/tiles")
        self.assertEqual(response.status_code, 200, response.text)
        return {tile["id"]: tile for tile in response.json()["tiles"]}


class TriageLanesTest(WorkspaceCase):
    def test_three_triage_dispatches_put_1b_in_progress_with_three_lanes(self) -> None:
        for type_name in TRIAGE:
            self.hook(RECORDER_PRE, _triage_payload(type_name))

        tile = self.tiles()["1b"]

        self.assertEqual(tile["state"], "in_progress")
        self.assertEqual(tile["awaiting"], ["staging.ws1_attribution"])
        lanes = tile["activity"]["lanes"]
        self.assertEqual([lane["label"] for lane in lanes], TRIAGE)
        for lane in lanes:
            self.assertRegex(lane["since"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_wrapped_payload_is_unwrapped_like_the_guardrail_does(self) -> None:
        for type_name in TRIAGE:
            wrapped = json.dumps(
                {"preToolHookArgs": json.loads(_triage_payload(type_name))}
            )
            self.hook(RECORDER_PRE, wrapped)

        self.assertEqual(self.tiles()["1b"]["state"], "in_progress")
        self.assertEqual(self.events()[0]["conversationId"], CONVERSATION)

    def test_without_override_events_go_to_the_payload_workspace(self) -> None:
        env = {k: v for k, v in self.env.items() if k != WORKSPACE_ENV}
        payload = json.loads(_triage_payload(TRIAGE[0]))
        payload["workspacePaths"] = [str(self.workspace)]
        self.hook(RECORDER_PRE, json.dumps(payload), env=env)

        self.assertEqual(
            [e["summary"].split(":")[0] for e in self.events()], [TRIAGE[0]]
        )


TRUNCATE_OPS = 'bq query --nouse_legacy_sql "TRUNCATE TABLE ops.pipeline_run_log"'


class GuardrailBlockTest(WorkspaceCase):
    def test_guardrail_deny_shows_a_blocked_item_on_the_landed_opening(self) -> None:
        self.catalog.put_table("staging.hospital_flu", rows=SPIKE_ROWS)

        decision = json.loads(
            self.hook(
                GUARDRAIL, _payload("run_command", {"CommandLine": TRUNCATE_OPS})
            ).stdout
        )

        self.assertEqual(decision["decision"], "deny")
        opening = self.tiles()["opening"]
        self.assertEqual(opening["state"], "landed")
        [blocked] = opening["activity"]["blocked"]
        self.assertEqual(blocked["tool"], "run_command")
        self.assertIn("TRUNCATE TABLE ops.pipeline_run_log", blocked["summary"])
        self.assertIn("raw and ops are strictly read-only", blocked["reason"])

    def test_blocked_event_carries_the_conversation_id(self) -> None:
        self.hook(GUARDRAIL, _payload("run_command", {"CommandLine": TRUNCATE_OPS}))

        [event] = self.events()

        self.assertEqual(event["phase"], "blocked")
        self.assertEqual(event["conversationId"], CONVERSATION)

    def test_allowed_calls_record_nothing_from_the_guardrail(self) -> None:
        decision = json.loads(
            self.hook(
                GUARDRAIL,
                _payload("run_command", {"CommandLine": "bq ls staging"}),
            ).stdout
        )

        self.assertEqual(decision["decision"], "allow")
        self.assertEqual(self.events(), [])


class StateMachineTest(WorkspaceCase):
    def test_checkpoint_swap_goes_locked_to_landed_with_no_events(self) -> None:
        self.assertEqual(self.tiles()["opening"]["state"], "locked")

        self.catalog.put_table("staging.hospital_flu", rows=SPIKE_ROWS)
        opening = self.tiles()["opening"]

        self.assertEqual(opening["state"], "landed")
        self.assertNotIn("activity", opening)
        self.assertEqual(self.events(), [])

    def test_landed_wins_over_in_progress_once_the_table_appears(self) -> None:
        for type_name in TRIAGE:
            self.hook(RECORDER_PRE, _triage_payload(type_name))
        self.catalog.put_table("staging.ws1_attribution", rows=[{"cause": "x"}])
        manifest = {
            "tiles": [
                {
                    **json.loads(MANIFEST_PATH.read_text("utf-8"))["tiles"][2],
                    "readiness": {"rule": "non_empty"},
                }
            ]
        }
        board = Board(
            parse_manifest(manifest),
            self.catalog,
            refresh_interval=0.0,
            events=EventLog(event_log_path(self.workspace)),
        )

        [tile] = board.tiles()

        self.assertEqual(tile["state"], "landed")

    def test_events_before_the_last_reset_are_ignored(self) -> None:
        self.hook(GUARDRAIL, _payload("run_command", {"CommandLine": TRUNCATE_OPS}))
        for type_name in TRIAGE:
            self.hook(RECORDER_PRE, _triage_payload(type_name))
        with event_log_path(self.workspace).open("a", encoding="utf-8") as log:
            log.write(json.dumps({"ts": "2026-11-06T00:00:00Z", "phase": "reset"}))
            log.write("\n")
        self.hook(RECORDER_PRE, _triage_payload("sampling-triage"))

        tiles = self.tiles()

        self.assertEqual(tiles["opening"]["state"], "locked")
        self.assertEqual(
            [lane["label"] for lane in tiles["1b"]["activity"]["lanes"]],
            ["sampling-triage"],
        )

    def test_post_events_record_success_and_unrelated_calls_leave_tiles_locked(
        self,
    ) -> None:
        self.hook(
            RECORDER_POST,
            _payload("run_command", {"CommandLine": "ls -la"}, error="exit status 1"),
        )
        self.hook(RECORDER_POST, _payload("view_file", {"AbsolutePath": "/x/y.py"}))

        failed, viewed = self.events()

        self.assertEqual((failed["phase"], failed["ok"]), ("post", False))
        self.assertEqual((viewed["tool"], viewed["ok"]), ("view_file", True))
        self.assertEqual({t["state"] for t in self.tiles().values()}, {"locked"})


class EventTailingTest(WorkspaceCase):
    def test_board_tails_the_event_log_every_second(self) -> None:
        now = [0.0]
        board = Board(
            load_manifest(MANIFEST_PATH),
            self.catalog,
            refresh_interval=5.0,
            clock=lambda: now[0],
            events=EventLog(event_log_path(self.workspace)),
        )
        board.tiles()
        for type_name in TRIAGE:
            self.hook(RECORDER_PRE, _triage_payload(type_name))

        now[0] = 0.9
        self.assertEqual(board.tiles()[2]["state"], "locked")
        now[0] = 1.0
        self.assertEqual(board.tiles()[2]["state"], "in_progress")

    def test_partial_lines_wait_for_their_newline(self) -> None:
        path = event_log_path(self.workspace)
        path.parent.mkdir(parents=True)
        log = EventLog(path)
        line = json.dumps({"ts": "t", "phase": "blocked", "tool": "run_command"})

        path.write_text(line[:10], "utf-8")
        self.assertEqual(log.read(), [])
        with path.open("a", encoding="utf-8") as f:
            f.write(line[10:] + "\nnot json\n")

        [event] = log.read()
        self.assertEqual(event.phase, "blocked")


SECRET = "s3cr3t-value-0123456789"
LONG_SQL = "CREATE OR REPLACE TABLE staging.ws1_attribution AS " + " UNION ALL ".join(
    f"SELECT '{cause}' AS cause, {n} AS points FROM staging.hospital_flu"
    for cause, n in (("pipeline", 15), ("sampling", 8), ("outbreak", 7))
)


class HookSafetyTest(WorkspaceCase):
    """The recorder always allows, exits 0 and records only short, redacted summaries."""

    def assert_allows(self, payload: str, env: dict[str, str] | None = None) -> None:
        for script, response in (
            (RECORDER_PRE, {"decision": "allow"}),
            (RECORDER_POST, {}),
        ):
            with self.subTest(script=script.name):
                result = self.hook(script, payload, env)
                self.assertEqual(json.loads(result.stdout), response)

    def test_malformed_payloads_are_allowed(self) -> None:
        for payload in ("", "not json", "[1, 2]", '"text"', "{", '{"toolCall": 7}'):
            with self.subTest(payload=payload):
                self.assert_allows(payload)

    def test_unwritable_log_is_allowed(self) -> None:
        blocker = self.workspace / "file"
        blocker.write_text("x", "utf-8")
        env = {**self.env, WORKSPACE_ENV: str(blocker)}

        self.assert_allows(_payload("run_command", {"CommandLine": "ls"}), env)

    def test_huge_args_are_allowed_quickly_with_a_truncated_summary(self) -> None:
        huge = _payload("run_command", {"CommandLine": "echo " + "x" * 2_000_000})

        start = time.monotonic()
        self.assert_allows(huge)

        self.assertLess(time.monotonic() - start, 10)
        for event in self.events():
            self.assertLessEqual(len(event["summary"]), 200)

    def test_summaries_hold_no_full_sql_bodies_or_env_values(self) -> None:
        payloads = [
            _payload("run_command", {"CommandLine": f'bq query "{LONG_SQL}"'}),
            _payload(
                "call_mcp_tool",
                {
                    "ServerName": "dak-bigquery",
                    "ToolName": "execute_sql",
                    "Arguments": {"projectId": "demo", "sql": LONG_SQL},
                },
            ),
            _payload("execute_sql", {"sql": LONG_SQL}),
            _payload(
                "run_command",
                {"CommandLine": f"export API_KEY={SECRET} && PROJECT_ID={SECRET} ./x"},
            ),
            _payload(
                "run_command",
                {
                    "CommandLine": f"curl --token {SECRET} -H 'Authorization: Bearer {SECRET}'"
                },
            ),
        ]
        for payload in payloads:
            self.hook(RECORDER_PRE, payload)
        self.hook(
            GUARDRAIL,
            _payload(
                "run_command",
                {
                    "CommandLine": f'bq query "DELETE FROM raw.hospital_flu_feeds WHERE {LONG_SQL}"'
                },
            ),
        )

        events = self.events()
        self.assertEqual(len(events), len(payloads) + 1)
        for event in events:
            text = json.dumps(event)
            self.assertLessEqual(len(event["summary"]), 200)
            self.assertNotIn(LONG_SQL, text)
            self.assertNotIn(LONG_SQL[:120], text)
            self.assertNotIn(SECRET, text)
        self.assertIn("dak-bigquery/execute_sql", events[1]["summary"])
        self.assertIn("API_KEY=…", events[3]["summary"])


class StaticContractTest(unittest.TestCase):
    def test_event_log_is_gitignored(self) -> None:
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".evidence-board/events.jsonl"],
            cwd=WORKTREE_ROOT,
            check=False,
        )

        self.assertEqual(result.returncode, 0, ".evidence-board/ must be gitignored")

    def test_recorder_is_registered_for_pre_and_post_tool_use(self) -> None:
        hooks = json.loads((PLUGIN_DIR / "hooks.json").read_text("utf-8"))
        registered = {
            event: [
                hook["command"]
                for group in hooks.values()
                for entry in group.get(event, [])
                if entry["matcher"] == "*"
                for hook in entry["hooks"]
            ]
            for event in ("PreToolUse", "PostToolUse")
        }

        self.assertIn("./bin/event-recorder-pre", registered["PreToolUse"])
        self.assertIn("./bin/event-recorder-post", registered["PostToolUse"])
        for script in (RECORDER_PRE, RECORDER_POST):
            self.assertTrue(os.access(script, os.X_OK), script)
            self.assertEqual(
                script.resolve(), RECORDER, "one script serves both phases"
            )

    def test_recorder_and_board_agree_on_the_event_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, WORKSPACE_ENV: tmp}
            result = run_plugin_hook(
                RECORDER_PRE, _payload("run_command", {"CommandLine": "ls"}), env
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            self.assertEqual(len(EventLog(event_log_path(tmp)).read()), 1)

    def test_matchers_are_validated_when_the_manifest_loads(self) -> None:
        tile = json.loads(MANIFEST_PATH.read_text("utf-8"))["tiles"][0]
        for matcher in (
            {"kind": "timer", "tool": ".*"},
            {"kind": "lane", "tool": ".*"},
            {"kind": "blocked"},
            {"kind": "blocked", "tool": "("},
        ):
            with self.subTest(matcher=matcher), self.assertRaises(ManifestError):
                parse_manifest({"tiles": [{**tile, "matchers": [matcher]}]})


if __name__ == "__main__":
    unittest.main()
