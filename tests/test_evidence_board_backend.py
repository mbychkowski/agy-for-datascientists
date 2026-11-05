"""Evidence Board backend, driven through its HTTP API with a fake table catalog.

Primary seam from spec #88: `GET /api/tiles` with an injected stand-in for the
BigQuery catalog, so no GCP access is needed. Static checks cover the Tile
manifest's dataset boundaries, and the launcher is exercised as a process for
its loopback bind.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from tests.helpers import WORKTREE_ROOT, create_demo_env_file

BOARD_DIR = (
    WORKTREE_ROOT
    / ".agents"
    / "plugins"
    / "ds-command-center"
    / "sidecars"
    / "evidence-board"
)
MANIFEST_PATH = BOARD_DIR / "tiles.json"

if str(BOARD_DIR) not in sys.path:
    sys.path.insert(0, str(BOARD_DIR))

from board.app import create_app
from board.catalog import FakeCatalog
from board.manifest import ManifestError, load_manifest, parse_manifest
from board.service import Board
from fastapi.testclient import TestClient

DEMO_ORDER = ["opening", "1a", "1b", "1c", "2a", "2b", "2c", "2d"]


def _client(catalog: FakeCatalog) -> TestClient:
    board = Board(load_manifest(MANIFEST_PATH), catalog, refresh_interval=0.0)
    return TestClient(create_app(board))


def _tiles(client: TestClient) -> list[dict]:
    response = client.get("/api/tiles")
    assert response.status_code == 200, response.text
    return response.json()["tiles"]


class FreshWorkspaceTest(unittest.TestCase):
    def test_all_eight_tiles_locked_in_manifest_order_with_step_and_awaited_table(
        self,
    ) -> None:
        tiles = _tiles(_client(FakeCatalog()))

        self.assertEqual([t["id"] for t in tiles], DEMO_ORDER)
        for tile in tiles:
            self.assertEqual(tile["state"], "locked", tile["id"])
            self.assertTrue(tile["step"], tile["id"])
            self.assertTrue(tile["awaiting"], tile["id"])
        opening = tiles[0]
        self.assertEqual(opening["step"], "Opening")
        self.assertEqual(opening["awaiting"], ["staging.hospital_flu"])
        self.assertEqual(tiles[3]["awaiting"], ["staging.hospital_flu_clean"])
        self.assertEqual(tiles[6]["awaiting"], ["ml.reveal_forecast_evaluation"])


SPIKE_ROWS = [
    {"week_end": "2026-10-24", "positive_flu_tests": 400, "wow_pct": 8.1},
    {"week_end": "2026-10-31", "positive_flu_tests": 540, "wow_pct": 35.0},
]


class OpeningLandsTest(unittest.TestCase):
    def test_opening_lands_with_spike_chart_and_proves_line_once_hospital_flu_exists(
        self,
    ) -> None:
        catalog = FakeCatalog(
            {
                "staging.hospital_flu": {
                    "num_rows": 9000,
                    "modified": "t1",
                    "rows": SPIKE_ROWS,
                }
            }
        )

        tiles = _tiles(_client(catalog))

        opening = tiles[0]
        self.assertEqual(opening["state"], "landed")
        self.assertEqual(opening["chart"]["rows"], SPIKE_ROWS)
        self.assertEqual(
            opening["proves"],
            "Northeast flu-positive counts rose +35% in the week ending on the Cutoff, "
            "in raw counts: the Spike the agents must explain.",
        )
        self.assertNotIn("awaiting", opening)
        self.assertEqual([t["state"] for t in tiles[1:]], ["locked"] * 7)

    def test_empty_hospital_flu_keeps_opening_locked(self) -> None:
        catalog = FakeCatalog(
            {"staging.hospital_flu": {"num_rows": 0, "rows": SPIKE_ROWS}}
        )

        opening = _tiles(_client(catalog))[0]

        self.assertEqual(opening["state"], "locked")
        self.assertEqual(opening["awaiting"], ["staging.hospital_flu"])
        self.assertEqual(catalog.queries_run, 0)

    def test_proves_falls_back_to_plain_text_when_chart_lacks_the_number(self) -> None:
        catalog = FakeCatalog(
            {
                "staging.hospital_flu": {
                    "rows": [{"week_end": "2026-10-31", "wow_pct": None}]
                }
            }
        )

        opening = _tiles(_client(catalog))[0]

        self.assertEqual(
            opening["proves"],
            "Northeast flu-positive counts jumped in the week ending on the Cutoff, "
            "in raw counts: the Spike the agents must explain.",
        )


class QueryCostTest(unittest.TestCase):
    def test_readiness_uses_metadata_only_until_a_table_lands(self) -> None:
        catalog = FakeCatalog()
        client = _client(catalog)

        for _ in range(3):
            _tiles(client)

        self.assertEqual(catalog.queries_run, 0)

    def test_chart_query_runs_once_on_landing_and_again_only_when_table_is_modified(
        self,
    ) -> None:
        catalog = FakeCatalog(
            {"staging.hospital_flu": {"modified": "t1", "rows": SPIKE_ROWS}}
        )
        client = _client(catalog)

        for _ in range(3):
            _tiles(client)
        self.assertEqual(catalog.queries_run, 1)

        new_rows = [
            {"week_end": "2026-10-31", "positive_flu_tests": 600, "wow_pct": 50.0}
        ]
        catalog.put_table("staging.hospital_flu", modified="t2", rows=new_rows)
        opening = _tiles(client)[0]
        _tiles(client)

        self.assertEqual(catalog.queries_run, 2)
        self.assertEqual(opening["chart"]["rows"], new_rows)

    def test_readiness_is_rechecked_at_most_once_per_refresh_interval(self) -> None:
        now = [0.0]
        catalog = FakeCatalog()
        board = Board(
            load_manifest(MANIFEST_PATH),
            catalog,
            refresh_interval=5.0,
            clock=lambda: now[0],
        )
        client = TestClient(create_app(board))
        _tiles(client)

        catalog.put_table("staging.hospital_flu", rows=SPIKE_ROWS)
        now[0] = 4.0
        self.assertEqual(_tiles(client)[0]["state"], "locked")
        now[0] = 5.0
        self.assertEqual(_tiles(client)[0]["state"], "landed")


class TransientErrorTest(unittest.TestCase):
    def test_catalog_error_returns_last_good_state_and_is_logged(self) -> None:
        catalog = FakeCatalog({"staging.hospital_flu": {"rows": SPIKE_ROWS}})
        client = _client(catalog)
        good = _tiles(client)

        catalog.failing = True
        with self.assertLogs("evidence_board", level="WARNING"):
            response = client.get("/api/tiles")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"tiles": good})

    def test_error_before_any_good_state_shows_every_tile_locked(self) -> None:
        catalog = FakeCatalog({"staging.hospital_flu": {"rows": SPIKE_ROWS}})
        catalog.failing = True
        client = _client(catalog)

        with self.assertLogs("evidence_board", level="WARNING"):
            response = client.get("/api/tiles")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([t["state"] for t in response.json()["tiles"]], ["locked"] * 8)

    def test_board_recovers_once_the_catalog_answers_again(self) -> None:
        catalog = FakeCatalog()
        client = _client(catalog)
        _tiles(client)
        catalog.put_table("staging.hospital_flu", rows=SPIKE_ROWS)
        catalog.failing = True
        with self.assertLogs("evidence_board", level="WARNING"):
            self.assertEqual(_tiles(client)[0]["state"], "locked")

        catalog.failing = False

        self.assertEqual(_tiles(client)[0]["state"], "landed")


class HealthTest(unittest.TestCase):
    def test_health_reports_ok(self) -> None:
        response = _client(FakeCatalog()).get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})


def _manifest_with(**overrides: object) -> dict:
    tile = {
        "id": "x",
        "step": "Opening",
        "title": "T",
        "tables": ["staging.hospital_flu"],
        "readiness": {"rule": "non_empty"},
        "chart": {"type": "bar", "query": "SELECT 1 AS n FROM `staging.hospital_flu`"},
        "proves": "p",
        "matchers": [],
    }
    tile.update(overrides)
    return {"tiles": [tile]}


class ManifestContractTest(unittest.TestCase):
    def test_manifest_declares_every_tile_field_in_demo_order(self) -> None:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

        self.assertEqual([t["id"] for t in raw["tiles"]], DEMO_ORDER)
        for tile in raw["tiles"]:
            for field in (
                "id",
                "step",
                "title",
                "tables",
                "readiness",
                "chart",
                "proves",
                "matchers",
            ):
                self.assertIn(field, tile, f"{tile.get('id')} lacks {field}")
            self.assertIn("query", tile["chart"])
        self.assertEqual(len(load_manifest(MANIFEST_PATH).tiles), 8)

    def test_no_manifest_entry_references_raw_ops_or_checkpoint(self) -> None:
        forbidden = re.compile(r"(?i)(?<![\w.])`?(raw|ops|checkpoint)`?\s*\.")

        def strings(node: object):
            if isinstance(node, str):
                yield node
            elif isinstance(node, list):
                for item in node:
                    yield from strings(item)
            elif isinstance(node, dict):
                for value in node.values():
                    yield from strings(value)

        for tile in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["tiles"]:
            for text in strings(tile):
                self.assertIsNone(
                    forbidden.search(text), f"Tile {tile['id']} references {text!r}"
                )
            for table in tile["tables"]:
                self.assertIn(
                    table.split(".")[0], {"staging", "features", "ml"}, tile["id"]
                )

    def test_loading_rejects_tables_outside_the_working_datasets(self) -> None:
        for table in (
            "raw.hospital_flu_feeds",
            "ops.pipeline_run_log",
            "checkpoint.hospital_flu",
            "other.t",
            "t",
        ):
            with self.subTest(table=table), self.assertRaises(ManifestError):
                parse_manifest(_manifest_with(tables=[table]))

    def test_loading_rejects_queries_outside_the_working_datasets_or_not_read_only(
        self,
    ) -> None:
        queries = [
            "SELECT * FROM `raw.hospital_flu_feeds`",
            "SELECT * FROM ops.pipeline_run_log",
            "SELECT * FROM `checkpoint`.hospital_flu",
            "SELECT * FROM `staging.hospital_flu` JOIN raw.hospital_reference USING (hospital_id)",
            "SELECT * FROM `other-project.staging.hospital_flu`",
            "SELECT * FROM `staging.ws1_attribution`",
            "SELECT * FROM `staging.hospital_flu`, `other.t`",
            "SELECT * FROM `staging.hospital_flu` AS h, other.t",
            "SELECT `other.t`.x FROM `staging.hospital_flu`",
            "DELETE FROM `staging.hospital_flu` WHERE TRUE",
            "SELECT 1; DROP TABLE staging.hospital_flu",
        ]
        for query in queries:
            with self.subTest(query=query), self.assertRaises(ManifestError):
                parse_manifest(_manifest_with(chart={"type": "bar", "query": query}))

    def test_loading_accepts_a_read_only_query_over_the_tiles_own_table(self) -> None:
        query = "WITH w AS (SELECT region FROM `staging.hospital_flu`) SELECT region, 'DROP' AS s FROM w"

        manifest = parse_manifest(_manifest_with(chart={"type": "bar", "query": query}))

        self.assertEqual(manifest.tiles[0].chart_query, query)


def _env_without_port() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k != "ANTIGRAVITY_SIDECAR_WEB_PORT"}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LauncherTest(unittest.TestCase):
    """The backend as a process: `python3 -m board` from the sidecar folder."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.fake = self.tmp / "catalog.json"
        self.fake.write_text(
            json.dumps({"tables": {"staging.hospital_flu": {"rows": SPIKE_ROWS}}}),
            "utf-8",
        )

    def _serve(self, args: list[str], env_port: int | None) -> tuple[int, str]:
        """Start the backend, wait for /api/health, return (bound port, log output)."""
        env = _env_without_port()
        if env_port is not None:
            env["ANTIGRAVITY_SIDECAR_WEB_PORT"] = str(env_port)
        cmd = [sys.executable, "-m", "board", "--fake-catalog", str(self.fake), *args]
        with subprocess.Popen(
            cmd,
            cwd=BOARD_DIR,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as proc:
            try:
                port = self._wait_healthy(
                    proc, [env_port, *[int(a) for a in args if a.isdigit()]]
                )
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/tiles", timeout=5
                ) as resp:
                    tiles = json.loads(resp.read())
                self.assertEqual(tiles["tiles"][0]["state"], "landed")
            finally:
                proc.terminate()
                output, _ = proc.communicate(timeout=10)
        return port, output

    def _wait_healthy(
        self, proc: subprocess.Popen, candidates: list[int | None]
    ) -> int:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self.fail(f"backend exited early with {proc.returncode}")
            for port in [p for p in candidates if p]:
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=1
                    ) as resp:
                        if json.loads(resp.read()) == {"status": "ok"}:
                            return port
                except OSError:
                    pass
            time.sleep(0.2)
        self.fail("backend never became healthy")

    def test_binds_loopback_on_the_sidecar_web_port(self) -> None:
        env_port = _free_port()

        port, output = self._serve([], env_port)

        self.assertEqual(port, env_port)
        self.assertIn(f"127.0.0.1:{env_port}", output)

    def test_port_flag_overrides_the_sidecar_web_port(self) -> None:
        env_port, flag_port = _free_port(), _free_port()

        port, output = self._serve(["--port", str(flag_port)], env_port)

        self.assertEqual(port, flag_port)
        self.assertIn(f"127.0.0.1:{flag_port}", output)

    def test_refuses_to_start_without_a_port(self) -> None:
        env = _env_without_port()

        result = subprocess.run(
            [sys.executable, "-m", "board", "--fake-catalog", str(self.fake)],
            cwd=BOARD_DIR,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ANTIGRAVITY_SIDECAR_WEB_PORT", result.stderr)

    def test_refuses_to_start_against_bigquery_without_pinned_project_and_region(
        self,
    ) -> None:
        create_demo_env_file(self.tmp, project_id="your-project-id")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "board",
                "--port",
                str(_free_port()),
                "--workspace",
                str(self.tmp),
            ],
            cwd=BOARD_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PROJECT_ID", result.stderr)

    @unittest.skipIf(
        (WORKTREE_ROOT / "demo.env").exists(),
        "a real demo.env would send the board to BigQuery",
    )
    def test_defaults_to_the_demo_env_at_the_repo_root(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "board", "--port", str(_free_port())],
            cwd=BOARD_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(WORKTREE_ROOT / "demo.env"), result.stderr)


if __name__ == "__main__":
    unittest.main()
