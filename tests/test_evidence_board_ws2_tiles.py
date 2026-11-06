"""Evidence Board Workstream 2 modeling Tiles: 2A Cohorts, 2B WAPE leaderboard (#95).

Seams from spec #88: real hook payloads are piped through
`bin/event-recorder-pre` / `-post` into a temp workspace's event log, and
Tile states are asserted through `GET /api/tiles` with a `FakeCatalog` whose
rows stand in for each Tile's chart query result.
"""

from __future__ import annotations

import json
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

KMEANS_SQL = (
    "CREATE OR REPLACE MODEL `demo-proj.ml.hospital_cohort_model` OPTIONS("
    " model_type='KMEANS', num_clusters=4, standardize_features=TRUE,"
    " kmeans_init_method='KMEANS++') AS SELECT peak_arrival_week, peak_volume,"
    " curve_width, seasonal_trend FROM `demo-proj.features.hospital_seasonal_features`;"
    " CREATE OR REPLACE TABLE `demo-proj.features.hospital_cohorts` AS SELECT"
    " hospital_id, CONCAT('COHORT_', CAST(CENTROID_ID AS STRING)) AS cohort_id"
    " FROM ML.PREDICT(MODEL `demo-proj.ml.hospital_cohort_model`,"
    " TABLE `demo-proj.features.hospital_seasonal_features`)"
)
FEATURES_SQL = (
    "CREATE OR REPLACE TABLE `demo-proj.features.hospital_seasonal_features` AS"
    " SELECT hospital_id, MAX(positive_flu_tests) AS peak_volume, COUNT(*) AS curve_width"
    " FROM `demo-proj.staging.hospital_flu_clean` GROUP BY hospital_id"
)
ARIMA_SQL = (
    "CREATE OR REPLACE MODEL `demo-proj.ml.forecast_clean_by_cohort` OPTIONS("
    " model_type='ARIMA_PLUS', time_series_timestamp_col='feed_date',"
    " time_series_data_col='positive_flu_tests', time_series_id_col='hospital_id',"
    " auto_arima=TRUE, data_frequency='DAILY') AS SELECT feed_date, hospital_id,"
    " positive_flu_tests FROM `demo-proj.staging.hospital_flu_clean`"
)
TIMESFM_SQL = (
    "INSERT INTO `demo-proj.ml.experiment_trials` SELECT * FROM AI.FORECAST("
    " (SELECT feed_date, hospital_id, positive_flu_tests"
    " FROM `demo-proj.staging.hospital_flu_clean`), data_col => 'positive_flu_tests',"
    " timestamp_col => 'feed_date', id_cols => ['hospital_id'], horizon => 56)"
)
KMEANS_FILE = "sql/ws2_kmeans_cohorts.sql"


def _bq(sql: str) -> str:
    return _payload(
        "run_command",
        {
            "CommandLine": f'bq query --project_id="demo-proj" --nouse_legacy_sql "{sql}"'
        },
    )


def _mcp(sql: str) -> str:
    return _payload(
        "call_mcp_tool",
        {
            "ServerName": "dak-bigquery",
            "ToolName": "execute_sql",
            "Arguments": {"projectId": "demo-proj", "sql": sql},
        },
    )


def _cohort_rows() -> list[dict]:
    """Chart-query rows for 2A: five hospitals in three Cohorts, cross-joined totals."""
    totals = {
        "breakout_cohort": "COHORT_3",
        "breakout_size": 2,
        "breakout_hospitals": "HOSP_A, HOSP_B",
        "hospitals": 5,
        "cohorts": 3,
    }
    hospitals = (
        ("HOSP_C", "COHORT_1", 2, 18.0, 0.9),
        ("HOSP_D", "COHORT_1", 2, 19.0, 1.0),
        ("HOSP_E", "COHORT_2", 1, 21.0, 1.1),
        ("HOSP_A", "COHORT_3", 2, 23.0, 2.71),
        ("HOSP_B", "COHORT_3", 2, 24.0, 2.71),
    )
    return [
        {
            "hospital_id": hospital,
            "cohort_id": cohort,
            "cohort_size": size,
            "peak_arrival_week": week,
            "seasonal_trend": trend,
            **totals,
        }
        for hospital, cohort, size, week, trend in hospitals
    ]


def _leaderboard_rows() -> list[dict]:
    """Chart-query rows for 2B: one Cohort x two families x two versions."""
    totals = {
        "clean_wape": 12.5,
        "uncleaned_wape": 21.25,
        "clean_wins": 2,
        "comparisons": 2,
        "best_family": "TimesFM",
    }
    return [
        {
            "cohort_id": "COHORT_1",
            "model_family": family,
            "training_data_version": version,
            "backtest_wape": wape,
            **totals,
        }
        for family, version, wape in (
            ("ARIMA_PLUS", "clean", 14.0),
            ("ARIMA_PLUS", "uncleaned", 22.5),
            ("TimesFM", "clean", 11.0),
            ("TimesFM", "uncleaned", 20.0),
        )
    ]


SOURCES = {
    "2a": ("features.hospital_cohorts", _cohort_rows()),
    "2b": ("ml.forecast_leaderboard", _leaderboard_rows()),
}
PROVES = {
    "2a": "K-means sorts 5 hospitals into 3 Cohorts by seasonal shape; the steepest-rising Cohort, COHORT_3, holds just 2 hospitals (HOSP_A, HOSP_B), isolating the Outbreak in its own Cohort.",
    "2b": "Forecasts trained on clean data beat uncleaned data in 2 of 2 Cohort and model pairs, with mean WAPE 12.5% vs 21.2%; TimesFM leads on clean data.",
}


class CohortTrainingActivityTest(WorkspaceCase):
    """2A shows a timer while BQML K-means trains."""

    def assert_training(self) -> None:
        tile = self.tiles()["2a"]
        self.assertEqual(tile["state"], "in_progress")
        self.assertEqual(tile["awaiting"], ["features.hospital_cohorts"])
        self.assertEqual(tile["activity"]["timer"]["label"], "BQML K-means training")

    def test_bq_query_creating_a_kmeans_model_starts_2a(self) -> None:
        self.hook(RECORDER_PRE, _bq(KMEANS_SQL))

        self.assert_training()

    def test_mcp_execute_sql_creating_a_kmeans_model_starts_2a(self) -> None:
        self.hook(RECORDER_PRE, _mcp(KMEANS_SQL))

        self.assert_training()

    def test_running_the_saved_kmeans_sql_file_starts_2a(self) -> None:
        command = (
            f"bq query --project_id=demo-proj --use_legacy_sql=false < {KMEANS_FILE}"
        )
        self.hook(RECORDER_PRE, _payload("run_command", {"CommandLine": command}))

        self.assert_training()

    def test_piping_the_rendered_kmeans_sql_file_into_bq_starts_2a(self) -> None:
        command = (
            f'sed "s/\\${{PROJECT_ID}}/demo-proj/g" {KMEANS_FILE}'
            " | bq query --project_id=demo-proj --use_legacy_sql=false"
        )
        self.hook(RECORDER_PRE, _payload("run_command", {"CommandLine": command}))

        self.assert_training()

    def test_writing_reading_or_featurizing_leaves_2a_locked(self) -> None:
        self.hook(
            RECORDER_POST,
            _payload("write_file", {"Path": KMEANS_FILE, "Content": KMEANS_SQL}),
        )
        self.hook(RECORDER_PRE, _payload("view_file", {"AbsolutePath": KMEANS_FILE}))
        self.hook(
            RECORDER_PRE, _payload("run_command", {"CommandLine": f"cat {KMEANS_FILE}"})
        )
        self.hook(RECORDER_PRE, _bq(FEATURES_SQL))

        self.assertEqual(self.tiles()["2a"]["state"], "locked")


class ForecastTrialsActivityTest(WorkspaceCase):
    """2B shows a ticker of ARIMA_PLUS and TimesFM trials as they start."""

    def test_arima_then_timesfm_tick_in_order(self) -> None:
        self.hook(RECORDER_PRE, _bq(ARIMA_SQL))
        self.hook(RECORDER_PRE, _mcp(TIMESFM_SQL))
        self.hook(RECORDER_POST, _mcp(TIMESFM_SQL))

        tile = self.tiles()["2b"]

        self.assertEqual(tile["state"], "in_progress")
        self.assertEqual(tile["awaiting"], ["ml.forecast_leaderboard"])
        ticker = tile["activity"]["ticker"]
        self.assertEqual([t["label"] for t in ticker], ["ARIMA_PLUS", "TimesFM"])
        self.assertEqual(ticker[0]["ts"], self.events()[0]["ts"])
        self.assertIn("ml.forecast_clean_by_cohort", ticker[0]["summary"])

    def test_the_ticker_keeps_only_the_latest_trials(self) -> None:
        for _ in range(12):
            self.hook(RECORDER_PRE, _bq(ARIMA_SQL))
        self.hook(RECORDER_PRE, _bq(TIMESFM_SQL))

        ticker = self.tiles()["2b"]["activity"]["ticker"]

        self.assertEqual(len(ticker), 8)
        self.assertEqual(ticker[-1]["label"], "TimesFM")

    def test_running_the_saved_forecast_sql_file_ticks_2b(self) -> None:
        self.hook(
            RECORDER_PRE,
            _payload(
                "run_command", {"CommandLine": "cat sql/ws2_forecasts_and_trials.sql"}
            ),
        )
        self.assertEqual(self.tiles()["2b"]["state"], "locked")

        command = "bq query --use_legacy_sql=false < sql/ws2_forecasts_and_trials.sql"
        self.hook(RECORDER_PRE, _payload("run_command", {"CommandLine": command}))

        [entry] = self.tiles()["2b"]["activity"]["ticker"]
        self.assertEqual(entry["label"], "ARIMA_PLUS + TimesFM")

    def test_piping_the_rendered_forecast_sql_file_into_bq_ticks_2b(self) -> None:
        command = (
            "envsubst < sql/ws2_forecasts_and_trials.sql"
            " | bq query --project_id=demo-proj --use_legacy_sql=false"
        )
        self.hook(RECORDER_PRE, _payload("run_command", {"CommandLine": command}))

        [entry] = self.tiles()["2b"]["activity"]["ticker"]
        self.assertEqual(entry["label"], "ARIMA_PLUS + TimesFM")

    def test_kmeans_training_does_not_tick_2b(self) -> None:
        self.hook(RECORDER_PRE, _bq(KMEANS_SQL))

        self.assertEqual(self.tiles()["2b"]["state"], "locked")


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
            {"2a": "cohorts", "2b": "leaderboard"},
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

    def test_landing_ends_the_training_activity(self) -> None:
        self.hook(RECORDER_PRE, _bq(KMEANS_SQL))
        self.catalog.put_table("features.hospital_cohorts", rows=_cohort_rows())

        self.assertEqual(self.tiles()["2a"]["state"], "landed")


class ManifestContractTest(unittest.TestCase):
    def tile(self, tile_id: str) -> dict:
        tiles = json.loads(MANIFEST_PATH.read_text("utf-8"))["tiles"]
        return next(t for t in tiles if t["id"] == tile_id)

    def test_ws2_modeling_tiles_land_on_non_empty_tables(self) -> None:
        manifest = load_manifest(MANIFEST_PATH)
        rules = {t.id: (t.readiness, t.tables) for t in manifest.tiles}

        self.assertEqual(rules["2a"], ("non_empty", ("features.hospital_cohorts",)))
        self.assertEqual(rules["2b"], ("non_empty", ("ml.forecast_leaderboard",)))

    def test_ticker_matchers_need_a_label(self) -> None:
        tile = self.tile("2b")
        with self.assertRaises(ManifestError):
            parse_manifest(
                {"tiles": [{**tile, "matchers": [{"kind": "ticker", "tool": ".*"}]}]}
            )


class RecorderSummaryTest(WorkspaceCase):
    def test_summaries_name_the_bqml_model_types_and_functions(self) -> None:
        self.hook(RECORDER_PRE, _bq(KMEANS_SQL))

        [event] = self.events()

        self.assertLessEqual(len(event["summary"]), 200)
        self.assertIn("[bqml: KMEANS, ML.PREDICT]", event["summary"])
        self.assertTrue(
            event["summary"].endswith(
                "[tables: ml.hospital_cohort_model, features.hospital_seasonal_features,"
                " features.hospital_cohorts]"
            ),
            event["summary"],
        )
        self.assertNotIn(KMEANS_SQL, event["summary"])

    def test_table_names_are_not_bqml_functions(self) -> None:
        self.hook(RECORDER_PRE, _bq(TIMESFM_SQL))

        [event] = self.events()

        self.assertIn("[bqml: AI.FORECAST]", event["summary"])

    def test_file_writes_carry_no_bqml_marker(self) -> None:
        self.hook(
            RECORDER_POST,
            _payload("write_file", {"Path": KMEANS_FILE, "Content": KMEANS_SQL}),
        )

        [event] = self.events()

        self.assertNotIn("bqml", event["summary"])


if __name__ == "__main__":
    unittest.main()
