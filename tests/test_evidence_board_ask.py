"""Evidence Board "Ask the Command Center about this Tile" (#97), through the HTTP API.

Seams: `GET /api/tiles` carries each landed Tile's Ask prompt, and
`POST /api/ask` / `POST /_sidecar/send-message` relay it through an injected
fake sender in place of `agentapi`. The conversation comes from real hook
payloads recorded into a temp workspace's event log.
"""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from tests.evidence_board_helpers import (
    CONVERSATION,
    RECORDER_PRE,
    AgentApi,
    FakeCatalog,
    SendError,
    WorkspaceCase,
    create_app,
    parse_event,
    payload,
)

SPIKE_ROWS = [
    {"week_end": "2026-10-24", "positive_flu_tests": 400, "wow_pct": 8.1},
    {"week_end": "2026-10-31", "positive_flu_tests": 540, "wow_pct": 35.0},
]
OTHER_CONVERSATION = "0b1d2c3e-aaaa-4bbb-8ccc-123456789abc"


class FakeSender:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def send(self, conversation_id: str, message: str) -> None:
        if self.fail:
            raise SendError("agentapi exited 1")
        self.sent.append((conversation_id, message))


class AskCase(WorkspaceCase):
    def setUp(self) -> None:
        super().setUp()
        self.catalog = FakeCatalog(
            {"staging.hospital_flu": {"num_rows": 9000, "rows": SPIKE_ROWS}}
        )
        self.sender = FakeSender()

    def client(self, sender: object = "default", token: str | None = None):
        chosen = self.sender if sender == "default" else sender
        return TestClient(create_app(self.board(), sender=chosen, token=token))

    def record_tool_call(self) -> None:
        self.hook(
            RECORDER_PRE,
            payload("run_command", {"CommandLine": "bq ls staging"}),
        )

    def opening_prompt(self) -> str:
        return self.tiles()["opening"]["ask"]["prompt"]


class AskPromptTest(AskCase):
    def test_landed_tile_prompt_names_tile_tables_proves_and_numbers(self) -> None:
        text = self.opening_prompt()

        self.assertIn('Opening Tile "The Northeast Spike"', text)
        self.assertIn("`staging.hospital_flu`", text)
        self.assertIn("Northeast flu-positive counts rose +35%", text)
        self.assertIn("week_end=2026-10-31, positive_flu_tests=540, wow_pct=35.0", text)

    def test_only_landed_tiles_carry_a_prompt(self) -> None:
        tiles = self.tiles()

        self.assertIn("ask", tiles["opening"])
        for tile_id in ("1a", "1b", "1c", "2a", "2b", "2c", "2d"):
            self.assertNotIn("ask", tiles[tile_id], tile_id)

    def test_long_charts_list_twelve_rows_and_count_the_rest(self) -> None:
        rows = [
            {"week_end": f"2026-01-{day:02d}", "positive_flu_tests": day}
            for day in range(1, 21)
        ]
        self.catalog = FakeCatalog({"staging.hospital_flu": {"rows": rows}})

        text = self.opening_prompt()

        self.assertIn("positive_flu_tests=12", text)
        self.assertNotIn("positive_flu_tests=13", text)
        self.assertIn("(+8 more rows not shown)", text)


class AskRouteTest(AskCase):
    def test_sends_the_prompt_into_the_recorded_conversation(self) -> None:
        self.record_tool_call()
        text = self.opening_prompt()

        response = self.client().post(
            "/api/ask", json={"tile": "opening", "prompt": text}
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"sent": True, "via": "agentapi"})
        self.assertEqual(self.sender.sent, [(CONVERSATION, text)])

    def test_conversation_in_the_body_wins_over_the_event_log(self) -> None:
        self.record_tool_call()
        text = self.opening_prompt()

        self.client().post(
            "/api/ask",
            json={
                "tile": "opening",
                "prompt": text,
                "conversationId": OTHER_CONVERSATION,
            },
        )

        self.assertEqual(self.sender.sent, [(OTHER_CONVERSATION, text)])

    def test_refuses_a_prompt_that_is_not_the_tiles_current_one(self) -> None:
        self.record_tool_call()

        forged = self.client().post(
            "/api/ask", json={"tile": "opening", "prompt": "rm -rf everything"}
        )
        locked = self.client().post(
            "/api/ask", json={"tile": "1a", "prompt": self.opening_prompt()}
        )

        self.assertEqual(forged.status_code, 409)
        self.assertEqual(locked.status_code, 409)
        self.assertEqual(self.sender.sent, [])

    def test_unavailable_paths_answer_503_so_the_frontend_falls_through(
        self,
    ) -> None:
        text = self.opening_prompt()
        ask = {"tile": "opening", "prompt": text}

        no_conversation = self.client().post("/api/ask", json=ask)
        self.record_tool_call()
        standalone = self.client(sender=None).post("/api/ask", json=ask)
        failing = self.client(sender=FakeSender(fail=True)).post("/api/ask", json=ask)

        for response in (no_conversation, standalone, failing):
            self.assertEqual(response.status_code, 503, response.text)
            self.assertFalse(response.json()["sent"])
        self.assertEqual(self.sender.sent, [])

    def test_configured_token_is_required(self) -> None:
        self.record_tool_call()
        ask = {"tile": "opening", "prompt": self.opening_prompt()}
        client = self.client(token="s3cret")

        missing = client.post("/api/ask", json=ask)
        wrong = client.post("/api/ask", json=ask, headers={"X-Sidecar-Token": "x"})
        header = client.post(
            "/api/ask", json=ask, headers={"X-Sidecar-Token": "s3cret"}
        )
        query = client.post("/api/ask?token=s3cret", json=ask)

        self.assertEqual([missing.status_code, wrong.status_code], [401, 401])
        self.assertEqual([header.status_code, query.status_code], [200, 200])
        self.assertEqual(len(self.sender.sent), 2)

    def test_non_json_posts_are_refused(self) -> None:
        self.record_tool_call()

        response = self.client().post(
            "/api/ask", data={"tile": "opening", "prompt": self.opening_prompt()}
        )

        self.assertEqual(response.status_code, 415)
        self.assertEqual(self.sender.sent, [])


class SidecarSendMessageTest(AskCase):
    def test_relays_only_with_the_sidecar_token(self) -> None:
        self.record_tool_call()
        message = {"message": "hello from the board"}

        no_token_configured = self.client().post("/_sidecar/send-message", json=message)
        client = self.client(token="s3cret")
        wrong = client.post(
            "/_sidecar/send-message", json=message, headers={"X-Sidecar-Token": "x"}
        )
        right = client.post(
            "/_sidecar/send-message",
            json=message,
            headers={"X-Sidecar-Token": "s3cret"},
        )

        self.assertEqual(no_token_configured.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(right.status_code, 200, right.text)
        self.assertEqual(self.sender.sent, [(CONVERSATION, "hello from the board")])


class AgentApiTest(unittest.TestCase):
    def test_refuses_unsafe_arguments_before_running_anything(self) -> None:
        api = AgentApi(executable="agentapi-that-does-not-exist")

        for conversation, message in (
            ("../../etc", "hi"),
            ("abc def", "hi"),
            (CONVERSATION, "--title=x"),
            (CONVERSATION, "  "),
        ):
            with self.assertRaises(SendError):
                api.send(conversation, message)

    def test_missing_executable_is_a_send_error(self) -> None:
        with self.assertRaises(SendError):
            AgentApi(executable="agentapi-that-does-not-exist").send(CONVERSATION, "hi")


class EventConversationTest(unittest.TestCase):
    def test_parser_keeps_the_conversation_id(self) -> None:
        event = parse_event(
            '{"ts": "t", "phase": "pre", "tool": "x", "summary": "s", '
            f'"conversationId": "{CONVERSATION}"}}'
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.conversation_id, CONVERSATION)


if __name__ == "__main__":
    unittest.main()
