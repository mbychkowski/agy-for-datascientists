"""Evidence Board 4: reset returns the board to locked (#93).

`./reset ws1|ws2` runs from the presenter repo while the hooks record events
into the stage-clone workspace, so reset appends a `reset` event to each stage
clone's event log. Seams: `bin/reset` as a process with fake `bq`/`gcloud`
(offline, temp workspaces), and the board's `GET /api/tiles` with a fake
table catalog.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import (
    PLUGIN_DIR,
    RESET_BIN,
    WORKTREE_ROOT,
    setup_preflight_test_env,
)

BOARD_DIR = PLUGIN_DIR / "sidecars" / "evidence-board"
MANIFEST_PATH = BOARD_DIR / "tiles.json"
MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"

if str(BOARD_DIR) not in sys.path:
    sys.path.insert(0, str(BOARD_DIR))

from board.app import create_app
from board.catalog import FakeCatalog
from board.events import EventLog, event_log_path
from board.manifest import load_manifest
from board.service import Board
from fastapi.testclient import TestClient

TABLES = {
    "raw": {
        "hospital_reference": {"demo": "true"},
        "hospital_flu_feeds": {"demo": "true"},
    },
    "ops": {"pipeline_run_log": {"demo": "true"}},
    "staging": {
        "hospital_flu": {"demo": "true"},
        "hospital_flu_clean": {"demo": "true"},
        "ws1_attribution": {"demo": "true"},
    },
    "features": {"hospital_cohorts": {"demo": "true"}},
    "ml": {"forecast_leaderboard": {"demo": "true"}},
    "checkpoint": {"ws1_staging_hospital_flu": {"demo": "true"}},
}
TRIAGE_EVENT = {
    "ts": "2026-11-06T00:10:00Z",
    "phase": "pre",
    "tool": "invoke_subagent",
    "summary": "distribution-triage",
}


class ResetCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env_file, self.env, _ = setup_preflight_test_env(
            str(self.tmp),
            project_id="demo-proj-123",
            region="us-central1",
            dataset_tables=TABLES,
        )

    def workspace(self, name: str) -> Path:
        path = self.tmp / name
        path.mkdir()
        return path

    def reset(self, target: str, *extra: str) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [
                str(RESET_BIN),
                target,
                "--env",
                str(self.env_file),
                "--dataset-dir",
                str(MOCK_DATASET_DIR),
                "--yes",
                *extra,
            ],
            cwd=WORKTREE_ROOT,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        self.assertEqual(
            proc.returncode, 0, f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
        return proc

    def events(self, workspace: Path) -> list[dict]:
        path = event_log_path(workspace)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


class ResetEventTest(ResetCase):
    def test_reset_appends_a_reset_event_to_the_stage_clone_log(self) -> None:
        clone = self.workspace("agy-ws1")

        self.reset("ws1", "--stage-clone", str(clone))

        (event,) = self.events(clone)
        self.assertEqual(event["phase"], "reset")
        self.assertEqual(event["summary"], "reset ws1")
        self.assertRegex(event["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_missing_stage_clone_is_skipped_with_a_message(self) -> None:
        missing = self.tmp / "agy-gone"
        clone = self.workspace("agy-ws2")

        proc = self.reset(
            "ws2", "--stage-clone", str(missing), "--stage-clone", str(clone)
        )

        self.assertIn(f"[SKIP] Stage clone {missing} not found", proc.stdout)
        self.assertFalse(missing.exists())
        self.assertEqual([e["summary"] for e in self.events(clone)], ["reset ws2"])

    def test_default_targets_the_conventional_stage_clones(self) -> None:
        stage_dir = self.workspace("demo-stage")
        ws2_clone = stage_dir / "agy-ws2"
        ws2_clone.mkdir()
        self.env["DEMO_STAGE_DIR"] = str(stage_dir)

        proc = self.reset("ws1")

        self.assertIn(
            f"[SKIP] Stage clone {stage_dir / 'agy-ws1'} not found", proc.stdout
        )
        self.assertEqual([e["phase"] for e in self.events(ws2_clone)], ["reset"])


class BoardAfterResetTest(ResetCase):
    def tiles(self, workspace: Path, catalog: FakeCatalog) -> dict[str, dict]:
        board = Board(
            load_manifest(MANIFEST_PATH),
            catalog,
            refresh_interval=0.0,
            events=EventLog(event_log_path(workspace)),
            event_interval=0.0,
        )
        response = TestClient(create_app(board)).get("/api/tiles")
        self.assertEqual(response.status_code, 200, response.text)
        return {tile["id"]: tile for tile in response.json()["tiles"]}

    def test_after_reset_with_tables_removed_all_eight_tiles_are_locked(self) -> None:
        clone = self.workspace("agy-ws1")
        log = event_log_path(clone)
        log.parent.mkdir()
        log.write_text(json.dumps(TRIAGE_EVENT) + "\n", encoding="utf-8")
        self.assertEqual(self.tiles(clone, FakeCatalog())["1b"]["state"], "in_progress")

        self.reset("ws1", "--stage-clone", str(clone))
        tiles = self.tiles(clone, FakeCatalog())

        self.assertEqual(len(tiles), 8)
        self.assertEqual({t["state"] for t in tiles.values()}, {"locked"})
        self.assertTrue(all(not t.get("activity") for t in tiles.values()))


if __name__ == "__main__":
    unittest.main()
