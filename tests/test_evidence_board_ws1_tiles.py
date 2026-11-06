"""Evidence Board Workstream 1 Tiles: 1A heatmap, 1B Attribution, 1C deduplication (#94).

Seams from spec #88: real hook payloads are piped through
`bin/event-recorder-pre` / `-post` into a temp workspace's event log, and
Tile states are asserted through `GET /api/tiles` with a `FakeCatalog` whose
rows stand in for each Tile's chart query result.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import EVIDENCE_BOARD_WORKSPACE_ENV as WORKSPACE_ENV
from tests.helpers import PLUGIN_DIR, run_plugin_hook

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

TRIAGE = ["distribution-triage", "sampling-triage", "pipeline-triage"]
PIPELINE_PATH = (
    "/home/presenter/demo-stage/agy-ws1/a-rather-long/checkout/path/"
    "pipelines/pipeline_clean.py"
)
SUBMIT = (
    'gcloud dataproc batches submit pyspark pipelines/pipeline_clean.py --project="demo-proj"'
    ' --region="us-central1" --version=3.0 --batch=ws1-clean-0038'
    " -- --source staging.hospital_flu --target staging.hospital_flu_clean"
)
PROFILE_SQL = (
    "SELECT hospital_id, DATE_TRUNC(feed_date, WEEK(SUNDAY)) AS week_start,"
    " SUM(positive_flu_tests) AS positives, SUM(total_flu_tests) AS tests,"
    " COUNT(*) AS feed_rows FROM `staging.hospital_flu` WHERE region = 'Northeast'"
    " GROUP BY 1, 2 ORDER BY 1, 2"
)


def _heatmap_rows() -> list[dict]:
    """Chart-query rows for 1A: two hospitals x two weeks, cross-joined totals."""
    totals = {
        "ne_hospitals": 25,
        "spike_hospitals": 17,
        "other_hospitals": 8,
        "spike_share_pct": 91.7,
    }
    rows = []
    for hospital, share, weeks in (
        ("HOSP_NE_001", 6.86, [(28, 0.06, None), (76, 0.163, 171.4)]),
        ("HOSP_NE_008", 1.0, [(145, 0.12, None), (152, 0.12, 4.8)]),
    ):
        for week_end, (positives, positivity, wow) in zip(
            ("2026-10-24", "2026-10-31"), weeks, strict=True
        ):
            rows.append(
                {
                    "hospital_id": hospital,
                    "week_end": week_end,
                    "positive_flu_tests": positives,
                    "positivity": positivity,
                    "wow_pct": wow,
                    "share_of_ne_spike_pct": share,
                    **totals,
                }
            )
    return rows


ATTRIBUTION_ROWS = [
    {
        "cause": cause,
        "contributed_points": points,
        "evidence": f"{cause} evidence",
        "spike_points": 35.0,
        "real_points": 12.0,
    }
    for cause, points in (
        ("pipeline_defect", 15.0),
        ("sampling_artifact", 8.0),
        ("outbreak", 7.0),
        ("seasonal_ramp", 5.0),
    )
]
DEDUP_ROWS = [
    {
        "before_rows": 101470,
        "before_duplicate_keys": 40,
        "after_rows": 101430,
        "after_duplicate_keys": 0,
        "rows_removed": 40,
    }
]
SOURCES = {
    "1a": ("staging.ws1_eda_heatmap", _heatmap_rows()),
    "1b": ("staging.ws1_attribution", ATTRIBUTION_ROWS),
    "1c": ("staging.hospital_flu_clean", DEDUP_ROWS),
}
PROVES = {
    "1a": "17 of 25 Northeast hospitals carry 92% of the Spike in the week ending on the Cutoff; the other 8 barely moved.",
    "1b": "The four causes add up to the +35% Spike; only 12 of those points are real disease (Outbreak plus Seasonal Ramp), the rest is the Pipeline Defect and the Sampling Artifact.",
    "1c": "Deduplicating by hospital and feed date removes 40 Hospital Feed rows across 40 duplicate keys, leaving 0 duplicate keys in staging.hospital_flu_clean.",
}


def _payload(name: str, args: dict, **extra: object) -> str:
    return json.dumps(
        {
            "toolCall": {"name": name, "args": args},
            "conversationId": "ec33ebf9-0cba-4100-8142-c61503f6c587",
            "workspacePaths": ["/workspace/project"],
            **extra,
        }
    )


def _subagent(type_name: str) -> str:
    return _payload(
        "invoke_subagent",
        {"TypeName": type_name, "Role": "Reviewer", "Prompt": "Challenge it."},
    )


class WorkspaceCase(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workspace, ignore_errors=True)
        self.env = {**os.environ, WORKSPACE_ENV: str(self.workspace)}
        self.catalog = FakeCatalog()

    def hook(self, script: Path, payload: str) -> None:
        result = run_plugin_hook(script, payload, self.env)
        self.assertEqual(result.returncode, 0, result.stderr)

    def events(self) -> list[dict]:
        path = event_log_path(self.workspace)
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


class ProfilingActivityTest(WorkspaceCase):
    """1A is in progress while the agent profiles staging.hospital_flu."""

    def test_bq_query_against_staging_hospital_flu_starts_1a(self) -> None:
        self.hook(
            RECORDER_PRE,
            _payload(
                "run_command",
                {"CommandLine": f'bq query --nouse_legacy_sql "{PROFILE_SQL}"'},
            ),
        )

        tile = self.tiles()["1a"]

        self.assertEqual(tile["state"], "in_progress")
        self.assertEqual(tile["awaiting"], ["staging.ws1_eda_heatmap"])
        [lane] = tile["activity"]["lanes"]
        self.assertIn("staging.hospital_flu", lane["label"])

    def test_mcp_execute_sql_with_a_long_query_starts_1a(self) -> None:
        self.hook(
            RECORDER_PRE,
            _payload(
                "call_mcp_tool",
                {
                    "ServerName": "dak-bigquery",
                    "ToolName": "execute_sql",
                    "Arguments": {"projectId": "demo-proj", "sql": PROFILE_SQL},
                },
            ),
        )

        self.assertEqual(self.tiles()["1a"]["state"], "in_progress")

    def test_queries_of_other_tables_leave_1a_locked(self) -> None:
        self.hook(
            RECORDER_PRE,
            _payload(
                "run_command",
                {
                    "CommandLine": 'bq query "SELECT COUNT(*) FROM staging.hospital_flu_clean"'
                },
            ),
        )

        self.assertEqual(self.tiles()["1a"]["state"], "locked")


class TriageAndReviewActivityTest(WorkspaceCase):
    """1B shows the three triage lanes, then the stats-reviewer."""

    def test_triage_lanes_then_stats_reviewer(self) -> None:
        for type_name in TRIAGE:
            self.hook(RECORDER_PRE, _subagent(type_name))
        self.assertNotIn("review", self.tiles()["1b"]["activity"])

        self.hook(RECORDER_PRE, _subagent("stats-reviewer"))
        self.hook(RECORDER_POST, _subagent("stats-reviewer"))
        activity = self.tiles()["1b"]["activity"]

        self.assertEqual([lane["label"] for lane in activity["lanes"]], TRIAGE)
        self.assertEqual(activity["review"]["label"], "stats-reviewer")
        self.assertEqual(activity["review"]["since"], self.events()[3]["ts"])

    def test_landed_1b_keeps_the_review(self) -> None:
        self.hook(RECORDER_PRE, _subagent("stats-reviewer"))
        self.catalog.put_table("staging.ws1_attribution", rows=ATTRIBUTION_ROWS)

        tile = self.tiles()["1b"]

        self.assertEqual(tile["state"], "landed")
        self.assertEqual(tile["activity"]["review"]["label"], "stats-reviewer")


class CleanPipelineActivityTest(WorkspaceCase):
    """1C shows the diff awaiting approval, then a timer from the batch submit."""

    def test_writing_pipeline_clean_shows_the_diff_awaiting_approval(self) -> None:
        self.hook(
            RECORDER_POST,
            _payload(
                "write_file",
                {"Path": PIPELINE_PATH, "Content": "import pyspark\n" * 200},
            ),
        )

        tile = self.tiles()["1c"]

        self.assertEqual(tile["state"], "in_progress")
        self.assertEqual(
            tile["activity"]["approval"]["label"], "pipelines/pipeline_clean.py"
        )
        self.assertNotIn("timer", tile["activity"])

    def test_batch_submit_starts_a_timer_that_a_failure_stops(self) -> None:
        self.hook(
            RECORDER_POST,
            _payload(
                "edit_file", {"Path": PIPELINE_PATH, "Target": "a", "Replacement": "b"}
            ),
        )
        submit = _payload("run_command", {"CommandLine": SUBMIT})
        self.hook(RECORDER_PRE, submit)

        timer = self.tiles()["1c"]["activity"]["timer"]
        self.assertEqual(timer["label"], "Dataproc Serverless batch")
        self.assertEqual(timer["since"], self.events()[1]["ts"])
        self.assertNotIn("until", timer)

        self.hook(
            RECORDER_POST,
            _payload("run_command", {"CommandLine": SUBMIT}, error="exit status 1"),
        )
        timer = self.tiles()["1c"]["activity"]["timer"]
        self.assertEqual((timer["until"], timer["ok"]), (self.events()[2]["ts"], False))

        self.hook(RECORDER_PRE, submit)
        timer = self.tiles()["1c"]["activity"]["timer"]
        self.assertEqual(timer["since"], self.events()[3]["ts"])
        self.assertNotIn("until", timer)

    def test_successful_post_leaves_the_timer_running(self) -> None:
        # Antigravity backgrounds a long command and reports it done early,
        # so only the Tile landing (or a failure) ends the batch timer.
        self.hook(RECORDER_PRE, _payload("run_command", {"CommandLine": SUBMIT}))
        self.hook(RECORDER_POST, _payload("run_command", {"CommandLine": SUBMIT}))

        self.assertNotIn("until", self.tiles()["1c"]["activity"]["timer"])

    def test_blocked_submit_stops_the_timer(self) -> None:
        submit = SUBMIT + " --service-account=sa@demo-proj.iam.gserviceaccount.com"
        self.hook(RECORDER_PRE, _payload("run_command", {"CommandLine": SUBMIT}))
        self.hook(GUARDRAIL, _payload("run_command", {"CommandLine": submit}))

        timer = self.tiles()["1c"]["activity"]["timer"]

        self.assertFalse(timer["ok"])
        self.assertEqual(timer["until"], self.events()[-1]["ts"])


class LandingTest(WorkspaceCase):
    def test_checkpoint_swap_lands_each_tile_with_no_events(self) -> None:
        board = self.board()
        before = self.tiles(board)
        for tile_id, (table, rows) in SOURCES.items():
            self.assertEqual(before[tile_id]["state"], "locked")
            self.catalog.put_table(table, num_rows=len(rows), rows=rows)

        after = self.tiles(board)

        for tile_id, (_, rows) in SOURCES.items():
            with self.subTest(tile=tile_id):
                tile = after[tile_id]
                self.assertEqual(tile["state"], "landed")
                self.assertNotIn("activity", tile)
                self.assertEqual(tile["chart"]["rows"], rows)
                self.assertEqual(tile["proves"], PROVES[tile_id])
        self.assertEqual(
            {t: after[t]["chart"]["type"] for t in SOURCES},
            {"1a": "heatmap", "1b": "waterfall", "1c": "before_after"},
        )
        self.assertFalse(event_log_path(self.workspace).exists())

    def test_unexpected_rows_fall_back_to_plain_proves_text(self) -> None:
        for table, _ in SOURCES.values():
            self.catalog.put_table(table, rows=[{"unexpected": 1}])

        tiles = self.tiles()

        for tile_id in SOURCES:
            with self.subTest(tile=tile_id):
                self.assertEqual(tiles[tile_id]["state"], "landed")
                self.assertNotIn("{", tiles[tile_id]["proves"])

    def test_1c_lands_from_the_clean_table_alone(self) -> None:
        self.catalog.put_table("staging.hospital_flu", rows=[{"week_end": "x"}])
        self.catalog.put_table("staging.hospital_flu_clean", rows=DEDUP_ROWS)

        tile = self.tiles()["1c"]

        self.assertEqual(tile["chart"]["rows"], DEDUP_ROWS)

    def test_one_failing_chart_query_does_not_hold_back_the_others(self) -> None:
        class OneTileFails(FakeCatalog):
            def run_query(self, sql: str) -> list[dict]:
                if "ws1_attribution" in sql:
                    raise RuntimeError("Unrecognized name: contributed_points")
                return super().run_query(sql)

        self.catalog = OneTileFails()
        for table, rows in SOURCES.values():
            self.catalog.put_table(table, rows=rows)

        tiles = self.tiles()

        self.assertEqual(tiles["1a"]["state"], "landed")
        self.assertEqual(tiles["1c"]["state"], "landed")
        self.assertEqual(tiles["1b"]["state"], "locked")


class ManifestContractTest(unittest.TestCase):
    def tile(self, tile_id: str) -> dict:
        tiles = json.loads(MANIFEST_PATH.read_text("utf-8"))["tiles"]
        return next(t for t in tiles if t["id"] == tile_id)

    def test_ws1_tiles_land_on_non_empty_tables(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        rules = {t.id: (t.readiness, t.tables) for t in manifest.tiles}

        self.assertEqual(rules["1a"], ("non_empty", ("staging.ws1_eda_heatmap",)))
        self.assertEqual(rules["1b"], ("non_empty", ("staging.ws1_attribution",)))
        self.assertEqual(rules["1c"], ("non_empty", ("staging.hospital_flu_clean",)))

    def test_chart_reads_must_stay_in_the_working_datasets(self) -> None:
        tile = self.tile("1c")
        for reads in (["raw.hospital_flu_feeds"], ["checkpoint.x"], "staging.x", ["x"]):
            with self.subTest(reads=reads), self.assertRaises(ManifestError):
                parse_manifest(
                    {"tiles": [{**tile, "chart": {**tile["chart"], "reads": reads}}]}
                )

    def test_chart_query_may_not_read_an_undeclared_table(self) -> None:
        tile = self.tile("1c")
        chart = {key: value for key, value in tile["chart"].items() if key != "reads"}

        with self.assertRaises(ManifestError):
            parse_manifest({"tiles": [{**tile, "chart": chart}]})

    def test_new_matcher_kinds_need_a_label(self) -> None:
        tile = self.tile("1c")
        for kind in ("approval", "review"):
            with self.subTest(kind=kind), self.assertRaises(ManifestError):
                parse_manifest(
                    {"tiles": [{**tile, "matchers": [{"kind": kind, "tool": ".*"}]}]}
                )


class RecorderSummaryTest(WorkspaceCase):
    def test_summaries_name_the_tables_a_long_query_touches(self) -> None:
        long_sql = (
            PROFILE_SQL
            + " UNION ALL "
            + PROFILE_SQL.replace(
                "`staging.hospital_flu`", "features.seasonal_features"
            )
        )
        self.hook(
            RECORDER_PRE,
            _payload("run_command", {"CommandLine": f'bq query "{long_sql}"'}),
        )

        [event] = self.events()

        self.assertLessEqual(len(event["summary"]), 200)
        self.assertTrue(
            event["summary"].endswith(
                "[tables: staging.hospital_flu, features.seasonal_features]"
            ),
            event["summary"],
        )
        self.assertNotIn(PROFILE_SQL, event["summary"])

    def test_long_paths_keep_their_file_name(self) -> None:
        self.hook(RECORDER_PRE, _payload("view_file", {"AbsolutePath": PIPELINE_PATH}))

        [event] = self.events()

        self.assertIn("pipelines/pipeline_clean.py", event["summary"])
        self.assertLessEqual(len(event["summary"]), 200)


if __name__ == "__main__":
    unittest.main()
