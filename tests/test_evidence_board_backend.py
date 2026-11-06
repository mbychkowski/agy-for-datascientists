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
        self.assertEqual(tiles[6]["awaiting"], ["staging.reveal_forecast_comparison"])


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


class FrontendBundleTest(unittest.TestCase):
    """The backend serves the built frontend bundle beside its JSON API."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _client(self, static_dir: Path) -> TestClient:
        board = Board(load_manifest(MANIFEST_PATH), FakeCatalog(), refresh_interval=0)
        return TestClient(create_app(board, static_dir=static_dir))

    def test_serves_the_built_bundle_at_the_root_and_keeps_the_api(self) -> None:
        dist = self.tmp / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>board</html>", "utf-8")
        (dist / "assets" / "app.js").write_text("console.log(1)", "utf-8")
        client = self._client(dist)

        page = client.get("/")
        asset = client.get("/assets/app.js")

        self.assertEqual(page.status_code, 200)
        self.assertIn("text/html", page.headers["content-type"])
        self.assertIn("board", page.text)
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(asset.text, "console.log(1)")
        self.assertEqual(len(client.get("/api/tiles").json()["tiles"]), 8)

    def test_missing_bundle_names_the_build_command_and_keeps_the_api(self) -> None:
        client = self._client(self.tmp / "not-built")

        page = client.get("/")

        self.assertEqual(page.status_code, 503)
        self.assertIn("make build-frontend", page.text)
        self.assertEqual(client.get("/api/health").json(), {"status": "ok"})


class RehearsalCatalogTest(unittest.TestCase):
    """A fake catalog file is re-read when it changes, so a rehearsal can land a Tile."""

    def test_editing_the_fake_catalog_file_lands_the_opening(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = tmp / "catalog.json"
        path.write_text(json.dumps({"tables": {}}), "utf-8")
        os.utime(path, (1_000, 1_000))
        client = _client(FakeCatalog.from_json(path))
        self.assertEqual(_tiles(client)[0]["state"], "locked")

        path.write_text(
            json.dumps({"tables": {"staging.hospital_flu": {"rows": SPIKE_ROWS}}}),
            "utf-8",
        )
        os.utime(path, (2_000, 2_000))

        opening = _tiles(client)[0]
        self.assertEqual(opening["state"], "landed")
        self.assertEqual(opening["chart"]["rows"], SPIKE_ROWS)


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


STANDALONE_BIN = WORKTREE_ROOT / "bin" / "evidence-board"
STANDALONE_LINK = WORKTREE_ROOT / "evidence-board"


class StandaloneLauncherTest(unittest.TestCase):
    """`./evidence-board`: the repo-root browser-tab fallback for the sidecar."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = {**_env_without_port(), "PYTHON": sys.executable}

    def test_root_wrapper_is_a_symlink_to_bin_like_the_other_root_scripts(
        self,
    ) -> None:
        self.assertTrue(STANDALONE_LINK.is_symlink())
        self.assertEqual(STANDALONE_LINK.resolve(), STANDALONE_BIN.resolve())
        self.assertTrue(os.access(STANDALONE_BIN, os.X_OK))

    def test_help_documents_workspace_and_port(self) -> None:
        result = subprocess.run(
            [str(STANDALONE_LINK), "--help"],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ("--workspace", "--port", "--fake-catalog"):
            self.assertIn(flag, result.stdout)

    def test_serves_the_board_on_the_given_port_from_any_cwd(self) -> None:
        fake = self.tmp / "catalog.json"
        fake.write_text(
            json.dumps({"tables": {"staging.hospital_flu": {"rows": SPIKE_ROWS}}}),
            "utf-8",
        )
        port = _free_port()
        cmd = [
            str(STANDALONE_LINK),
            "--port",
            str(port),
            "--fake-catalog",
            str(fake),
            "--no-build",
        ]
        with subprocess.Popen(
            cmd,
            cwd=self.tmp,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        ) as proc:
            try:
                tiles = self._wait_for_tiles(proc, port)
            finally:
                proc.terminate()
                output, _ = proc.communicate(timeout=10)

        self.assertEqual([t["state"] for t in tiles][:2], ["landed", "locked"])
        self.assertIn(f"http://127.0.0.1:{port}/", output)

    def test_workspace_flag_selects_the_demo_env_the_backend_pins_to(self) -> None:
        create_demo_env_file(self.tmp, project_id="your-project-id")

        result = subprocess.run(
            [
                str(STANDALONE_LINK),
                "--workspace",
                str(self.tmp),
                "--port",
                str(_free_port()),
                "--no-build",
            ],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.tmp / "demo.env"), result.stderr)
        self.assertIn("PROJECT_ID", result.stderr)

    def test_rejects_unknown_arguments(self) -> None:
        result = subprocess.run(
            [str(STANDALONE_LINK), "--bogus"],
            env=self.env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--bogus", result.stderr)

    def _wait_for_tiles(self, proc: subprocess.Popen, port: int) -> list[dict]:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self.fail(f"launcher exited early with {proc.returncode}")
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/tiles", timeout=1
                ) as resp:
                    return json.loads(resp.read())["tiles"]
            except OSError:
                time.sleep(0.2)
        self.fail("launcher never served /api/tiles")


if __name__ == "__main__":
    unittest.main()
