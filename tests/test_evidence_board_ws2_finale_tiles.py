"""Evidence Board Workstream 2 finale Tiles: 2C Reveal, 2D skill refresh (#96).

Seams from spec #88: real hook payloads are piped through
`bin/event-recorder-pre` / `-post` into a temp workspace's event log, and
Tile states are asserted through `GET /api/tiles` with a `FakeCatalog` whose
rows stand in for each Tile's chart query result.
"""

from __future__ import annotations

import json
import re
import unittest

from tests.evidence_board_helpers import (
    MANIFEST_PATH,
    RECORDER_POST,
    RECORDER_PRE,
    ManifestError,
    WorkspaceCase,
    event_log_path,
    load_manifest,
    parse_manifest,
)
from tests.evidence_board_helpers import payload as _payload
from tests.helpers import EVIDENCE_BOARD_DIR

REVEAL_TABLE = "staging.reveal_forecast_comparison"
TRIALS_TABLE = "ml.experiment_trials"
LEADERBOARD_TABLE = "ml.forecast_leaderboard"
SKILL_PATH = ".agents/plugins/ds-command-center/skills/cohort-forecast-refresh/SKILL.md"


def _reveal_rows() -> list[dict]:
    """Chart-query rows for 2C: six Reveal weeks, cross-joined totals."""
    totals = {
        "reveal_weeks": 6,
        "clean_wape": 4.2,
        "uncleaned_wape": 31.75,
        "uncleaned_overshoot_pct": 31.75,
    }
    weeks = (
        ("2026-11-01", "2026-11-07", 600, 610, 790),
        ("2026-11-08", "2026-11-14", 640, 655, 840),
        ("2026-11-15", "2026-11-21", 690, 700, 905),
        ("2026-11-22", "2026-11-28", 720, 745, 950),
        ("2026-11-29", "2026-12-05", 760, 780, 1005),
        ("2026-12-06", "2026-12-12", 790, 820, 1045),
    )
    return [
        {
            "horizon_week": i,
            "week_start": start,
            "week_end": end,
            "reveal_observed_positives": observed,
            "clean_forecast_positives": clean,
            "uncleaned_forecast_positives": uncleaned,
            **totals,
        }
        for i, (start, end, observed, clean, uncleaned) in enumerate(weeks, start=1)
    ]


def _refresh_rows() -> list[dict]:
    """Chart-query rows for 2D: two Cohorts x two families for 2026-W44."""
    totals = {
        "period": "2026-W44",
        "new_trials": 4,
        "cohorts": 2,
        "best_family": "TimesFM",
    }
    return [
        {"cohort_id": cohort, "model_family": family, "backtest_wape": wape, **totals}
        for cohort, family, wape in (
            ("COHORT_1", "ARIMA_PLUS", 0.081),
            ("COHORT_1", "TimesFM", 0.0684),
            ("COHORT_2", "ARIMA_PLUS", 0.112),
            ("COHORT_2", "TimesFM", 0.097),
        )
    ]


REVEAL_PROVES = (
    "Over the 6 Reveal weeks after the Cutoff, the clean-data forecast tracks reality"
    " at 4.2% WAPE, while the uncleaned forecast overshoots it by 31.8%."
)
REFRESH_PROVES = (
    "The cohort-forecast-refresh skill reran the forecasting workflow for 2026-W44:"
    " 4 new trials across 2 Cohorts, with TimesFM leading on backtest WAPE."
)


def _run(command: str) -> str:
    return _payload("run_command", {"CommandLine": command})


def _mcp(sql: str) -> str:
    return _payload(
        "call_mcp_tool",
        {
            "ServerName": "dak-bigquery",
            "ToolName": "execute_sql",
            "Arguments": {"projectId": "demo-proj", "sql": sql},
        },
    )


def _write_skill() -> str:
    return _payload(
        "write_to_file",
        {"TargetFile": f"/workspace/project/{SKILL_PATH}", "CodeContent": "# skill"},
    )


def _dispatch(type_name: str, role: str) -> str:
    return _payload(
        "invoke_subagent",
        {"TypeName": type_name, "Role": role, "Prompt": "Refresh 2026-W44."},
    )


class RevealLandingTest(WorkspaceCase):
    """2C stays locked until the Reveal comparison table exists, then lands."""

    def test_locked_until_the_reveal_table_exists(self) -> None:
        board = self.board()
        tile = self.tiles(board)["2c"]
        self.assertEqual(tile["state"], "locked")
        self.assertEqual(tile["awaiting"], [REVEAL_TABLE])

        self.catalog.put_table(REVEAL_TABLE, num_rows=0)
        self.assertEqual(self.tiles(board)["2c"]["state"], "locked")

        rows = _reveal_rows()
        self.catalog.put_table(REVEAL_TABLE, num_rows=len(rows), rows=rows)
        tile = self.tiles(board)["2c"]

        self.assertEqual(tile["state"], "landed")
        self.assertEqual(tile["chart"], {"type": "reveal", "rows": rows})
        self.assertEqual(tile["proves"], REVEAL_PROVES)
        self.assertFalse(event_log_path(self.workspace).exists())

    def test_unexpected_rows_fall_back_to_plain_proves_text(self) -> None:
        self.catalog.put_table(REVEAL_TABLE, rows=[{"unexpected": 1}])

        tile = self.tiles()["2c"]

        self.assertEqual(tile["state"], "landed")
        self.assertNotIn("{", tile["proves"])


class RevealActivityTest(WorkspaceCase):
    """2C shows a timer while the Reveal loads and is compared."""

    def assert_loading(self) -> None:
        tile = self.tiles()["2c"]
        self.assertEqual(tile["state"], "in_progress")
        self.assertEqual(tile["awaiting"], [REVEAL_TABLE])
        self.assertEqual(tile["activity"]["timer"]["label"], "Loading the Reveal")

    def test_running_load_reveal_starts_2c(self) -> None:
        self.hook(RECORDER_PRE, _run("./load-reveal --reveal-location /tmp/presenter"))

        self.assert_loading()

    def test_running_the_reveal_comparison_sql_starts_2c(self) -> None:
        self.hook(
            RECORDER_PRE,
            _run("bq query --use_legacy_sql=false < sql/ws2_reveal_comparison.sql"),
        )

        self.assert_loading()

    def test_mcp_sql_writing_the_comparison_table_starts_2c(self) -> None:
        self.hook(
            RECORDER_PRE,
            _mcp(
                "CREATE OR REPLACE TABLE `demo-proj.staging.reveal_forecast_comparison`"
                " AS SELECT 1 AS horizon_week"
            ),
        )

        self.assert_loading()

    def test_landing_ends_the_loading_activity(self) -> None:
        self.hook(RECORDER_PRE, _run("./load-reveal /tmp/presenter"))
        self.catalog.put_table(REVEAL_TABLE, rows=_reveal_rows())

        self.assertEqual(self.tiles()["2c"]["state"], "landed")

    def test_forecasting_leaves_2c_locked(self) -> None:
        self.hook(
            RECORDER_PRE,
            _run("bq query --use_legacy_sql=false < sql/ws2_forecasts_and_trials.sql"),
        )

        self.assertEqual(self.tiles()["2c"]["state"], "locked")


class RefreshLandingTest(WorkspaceCase):
    """2D lands only once trials for the refresh period exist."""

    def put_ws2_tables(self, trial_rows: list[dict]) -> None:
        # The fake runs 2D's query against ml.experiment_trials, so its rows
        # are the period-filtered result: none until the refresh logs trials.
        self.catalog.put_table(TRIALS_TABLE, num_rows=24, modified="1", rows=trial_rows)
        self.catalog.put_table(LEADERBOARD_TABLE, num_rows=24, rows=[{"x": 1}])

    def test_existing_tables_without_refresh_period_rows_do_not_land_2d(self) -> None:
        self.put_ws2_tables([])

        tile = self.tiles()["2d"]

        self.assertEqual(tile["state"], "locked")
        self.assertEqual(tile["awaiting"], [TRIALS_TABLE, LEADERBOARD_TABLE])
        self.assertNotIn("chart", tile)

    def test_lands_once_refresh_period_rows_exist(self) -> None:
        board = self.board()
        self.put_ws2_tables([])
        self.assertEqual(self.tiles(board)["2d"]["state"], "locked")

        rows = _refresh_rows()
        self.catalog.put_table(TRIALS_TABLE, num_rows=28, modified="2", rows=rows)
        tile = self.tiles(board)["2d"]

        self.assertEqual(tile["state"], "landed")
        self.assertEqual(tile["chart"], {"type": "refresh", "rows": rows})
        self.assertEqual(tile["proves"], REFRESH_PROVES)

    def test_needs_both_tables(self) -> None:
        self.catalog.put_table(TRIALS_TABLE, rows=_refresh_rows())

        tile = self.tiles()["2d"]

        self.assertEqual(tile["state"], "locked")
        self.assertEqual(tile["awaiting"], [LEADERBOARD_TABLE])


class RefreshActivityTest(WorkspaceCase):
    """2D shows the skill written, the fresh subagent and the refresh run."""

    def test_skill_write_then_dispatch_then_run_show_on_2d(self) -> None:
        self.hook(RECORDER_POST, _write_skill())
        self.hook(RECORDER_PRE, _dispatch("self", "Cohort Forecast Refresh Runner"))
        self.hook(RECORDER_PRE, _run("./run-cohort-forecast-refresh --period 2026-W44"))

        tile = self.tiles()["2d"]

        self.assertEqual(tile["state"], "in_progress")
        activity = tile["activity"]
        self.assertEqual(
            [lane["label"] for lane in activity["lanes"]],
            ["SKILL.md written", "Fresh subagent dispatched"],
        )
        self.assertEqual(activity["timer"]["label"], "Refreshing 2026-W44")

    def test_reading_the_skill_or_dispatching_triage_leaves_2d_locked(self) -> None:
        self.hook(RECORDER_PRE, _payload("view_file", {"AbsolutePath": SKILL_PATH}))
        self.hook(RECORDER_PRE, _run(f"cat {SKILL_PATH}"))
        self.hook(RECORDER_PRE, _dispatch("distribution-triage", "Distribution Triage"))
        self.hook(
            RECORDER_POST,
            _payload("write_file", {"Path": "pipelines/pipeline_clean.py"}),
        )

        self.assertEqual(self.tiles()["2d"]["state"], "locked")

    def test_landing_wins_over_activity(self) -> None:
        self.hook(RECORDER_PRE, _run("./run-cohort-forecast-refresh --period 2026-W44"))
        self.catalog.put_table(TRIALS_TABLE, rows=_refresh_rows())
        self.catalog.put_table(LEADERBOARD_TABLE, rows=[{"x": 1}])

        tile = self.tiles()["2d"]

        self.assertEqual(tile["state"], "landed")
        self.assertIn("timer", tile["activity"])


class ManifestContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = json.loads(MANIFEST_PATH.read_text("utf-8"))
        self.manifest = load_manifest(MANIFEST_PATH)

    def tile(self, tile_id: str) -> dict:
        return next(t for t in self.raw["tiles"] if t["id"] == tile_id)

    def test_finale_tiles_readiness(self) -> None:
        rules = {t.id: (t.readiness, t.tables) for t in self.manifest.tiles}

        self.assertEqual(rules["2c"], ("non_empty", (REVEAL_TABLE,)))
        self.assertEqual(rules["2d"], ("chart_rows", (TRIALS_TABLE, LEADERBOARD_TABLE)))

    def test_2d_query_selects_only_the_refresh_period(self) -> None:
        tile = next(t for t in self.manifest.tiles if t.id == "2d")
        [literal] = re.findall(r"r'([^']*)'", tile.chart_query)
        period = re.compile(literal)

        # How lib/cohort_forecast_refresh.py names the refresh trials.
        for text in (
            "trial_2026_w44_timesfm_cohort_1_clean",
            "clean_v2_2026_w44",
            '{"period":"2026-w44"}',
        ):
            self.assertRegex(text, period)
        # Workstream 2 trials and the baseline period stay out.
        for text in (
            "trial_2026_w43_arima_plus_cohort_1_clean",
            "clean_v2_2026_w43",
            "clean",
            '{"period_label":"2025-26-peak-8w"}',
        ):
            self.assertNotRegex(text, period)
        self.assertIn("LOWER(", tile.chart_query)

    def test_unknown_readiness_rules_are_rejected(self) -> None:
        tile = self.tile("2d")
        for rule in ("deferred", "table_exists"):
            with self.subTest(rule=rule), self.assertRaises(ManifestError):
                parse_manifest({"tiles": [{**tile, "readiness": {"rule": rule}}]})


class WithheldDataBoundaryTest(unittest.TestCase):
    """ADR 0001 and the Command Center rules: the board never points at the
    withheld bucket, the Answer Key or the `checkpoint` dataset."""

    FORBIDDEN = re.compile(
        r"(?i)gs://|answer[_ -]?key|reveal\.csv|mock_withheld|withheld[_-](dir|bucket)"
        r"|hospital_flu_feeds_reveal|\bcheckpoint`?\s*\.\s*`?\w"
    )

    def board_files(self) -> list:
        files = [
            EVIDENCE_BOARD_DIR / "tiles.json",
            EVIDENCE_BOARD_DIR / "sidecar.json",
            EVIDENCE_BOARD_DIR / "frontend" / "index.html",
            *sorted((EVIDENCE_BOARD_DIR / "board").glob("*.py")),
            *sorted((EVIDENCE_BOARD_DIR / "frontend" / "src").rglob("*.ts*")),
        ]
        self.assertGreater(len(files), 10)
        return files

    def test_board_sources_never_reference_withheld_data_or_checkpoint(self) -> None:
        for path in self.board_files():
            with self.subTest(path=path.name):
                self.assertIsNone(
                    self.FORBIDDEN.search(path.read_text("utf-8")), str(path)
                )

    def test_no_tile_mentions_checkpoint(self) -> None:
        text = MANIFEST_PATH.read_text("utf-8")

        self.assertNotRegex(text, r"(?i)checkpoint")

    def test_the_pattern_catches_what_it_guards(self) -> None:
        for text in (
            "gs://presenter-withheld/reveal/",
            "answer_key.json",
            "Answer Key",
            "reveal.csv",
            "SELECT * FROM `checkpoint.hospital_flu_clean`",
            "FROM checkpoint . ml_trials",
            "raw.hospital_flu_feeds_reveal",
        ):
            self.assertRegex(text, self.FORBIDDEN)


if __name__ == "__main__":
    unittest.main()
