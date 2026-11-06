"""Shared harness for Evidence Board seam tests.

Real hook payloads are piped through the plugin's hook scripts into a temp
workspace's event log, and Tile states are read back through `GET /api/tiles`
with a `FakeCatalog`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import EVIDENCE_BOARD_DIR as BOARD_DIR
from tests.helpers import EVIDENCE_BOARD_WORKSPACE_ENV as WORKSPACE_ENV
from tests.helpers import PLUGIN_DIR, run_plugin_hook

RECORDER = PLUGIN_DIR / "bin" / "event-recorder"
RECORDER_PRE = PLUGIN_DIR / "bin" / "event-recorder-pre"
RECORDER_POST = PLUGIN_DIR / "bin" / "event-recorder-post"
GUARDRAIL = PLUGIN_DIR / "bin" / "guardrail-hook"
MANIFEST_PATH = BOARD_DIR / "tiles.json"

if str(BOARD_DIR) not in sys.path:
    sys.path.insert(0, str(BOARD_DIR))

from board.app import create_app
from board.catalog import FakeCatalog
from board.events import EventLog, event_log_path
from board.manifest import ManifestError, load_manifest, parse_manifest
from board.service import Board
from fastapi.testclient import TestClient

# Board modules re-exported so test modules import them after the sys.path insert.
__all__ = [
    "CONVERSATION",
    "GUARDRAIL",
    "MANIFEST_PATH",
    "RECORDER",
    "RECORDER_POST",
    "RECORDER_PRE",
    "Board",
    "EventLog",
    "FakeCatalog",
    "ManifestError",
    "WorkspaceCase",
    "event_log_path",
    "load_manifest",
    "parse_manifest",
    "payload",
]

CONVERSATION = "ec33ebf9-0cba-4100-8142-c61503f6c587"


def payload(name: str, args: dict, **extra: object) -> str:
    """A hook payload for one tool call, shaped as Antigravity sends it."""
    return json.dumps(
        {
            "toolCall": {"name": name, "args": args},
            "stepIdx": 4,
            "conversationId": CONVERSATION,
            "workspacePaths": ["/workspace/project"],
            **extra,
        }
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

    def board(self) -> Board:
        return Board(
            load_manifest(MANIFEST_PATH),
            self.catalog,
            refresh_interval=0.0,
            events=EventLog(event_log_path(self.workspace)),
            event_interval=0.0,
        )

    def tiles(self, board: Board | None = None) -> dict[str, dict]:
        response = TestClient(create_app(board or self.board())).get("/api/tiles")
        self.assertEqual(response.status_code, 200, response.text)
        return {tile["id"]: tile for tile in response.json()["tiles"]}
