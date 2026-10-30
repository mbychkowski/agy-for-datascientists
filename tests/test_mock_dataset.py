import csv
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from collections import defaultdict
from datetime import date
from pathlib import Path

from lib.mock_dataset_generator import (
    BACKFILL_BATCH_ID,
    BACKFILL_END_DATE,
    BACKFILL_INGESTED_AT,
    BACKFILL_RUN_ID,
    BACKFILL_START_DATE,
    BASELINE_WEEK_END,
    BASELINE_WEEK_START,
    CUTOFF_DATE,
    REVEAL_END_DATE,
    REVEAL_START_DATE,
    SPIKE_WEEK_START,
    generate_dataset,
)

WORKTREE_ROOT = Path(__file__).resolve().parent.parent
GENERATE_BIN = WORKTREE_ROOT / "bin" / "generate-mock-dataset"
LOAD_BIN = WORKTREE_ROOT / "bin" / "load-raw-ops"
MOCK_DATASET_DIR = WORKTREE_ROOT / "fixtures" / "mock_dataset"
MOCK_WITHHELD_DIR = WORKTREE_ROOT / "fixtures" / "mock_withheld"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class TestMockDatasetDeterminismAndFixtures(unittest.TestCase):
    def test_committed_fixtures_exist_and_match_seed_42(self):
        """Committed fixtures in fixtures/ must match a fresh seed=42 mini run byte-for-byte."""
        expected_files = [
            MOCK_DATASET_DIR / "raw" / "hospital_reference.csv",
            MOCK_DATASET_DIR / "raw" / "hospital_flu_feeds" / "feeds.csv",
            MOCK_DATASET_DIR / "ops" / "pipeline_run_log.csv",
            MOCK_WITHHELD_DIR / "answer_key.json",
            MOCK_WITHHELD_DIR / "reveal" / "hospital_flu_feeds_reveal" / "reveal.csv",
            MOCK_WITHHELD_DIR / "README.md",
        ]
        for fpath in expected_files:
            self.assertTrue(fpath.exists(), f"Expected committed fixture at {fpath}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_out = Path(tmpdir) / "dataset"
            tmp_withheld = Path(tmpdir) / "withheld"
            proc = subprocess.run(
                [
                    str(GENERATE_BIN),
                    "--seed",
                    "42",
                    "--scale",
                    "mini",
                    "--output-dir",
                    str(tmp_out),
                    "--withheld-dir",
                    str(tmp_withheld),
                ],
                cwd=WORKTREE_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("Generated mini dataset (seed=42)", proc.stdout)

            pairs = [
                (
                    MOCK_DATASET_DIR / "raw" / "hospital_reference.csv",
                    tmp_out / "raw" / "hospital_reference.csv",
                ),
                (
                    MOCK_DATASET_DIR / "raw" / "hospital_flu_feeds" / "feeds.csv",
                    tmp_out / "raw" / "hospital_flu_feeds" / "feeds.csv",
                ),
                (
                    MOCK_DATASET_DIR / "ops" / "pipeline_run_log.csv",
                    tmp_out / "ops" / "pipeline_run_log.csv",
                ),
                (
                    MOCK_WITHHELD_DIR / "answer_key.json",
                    tmp_withheld / "answer_key.json",
                ),
                (
                    MOCK_WITHHELD_DIR
                    / "reveal"
                    / "hospital_flu_feeds_reveal"
                    / "reveal.csv",
                    tmp_withheld
                    / "reveal"
                    / "hospital_flu_feeds_reveal"
                    / "reveal.csv",
                ),
            ]
            for committed, generated in pairs:
                self.assertEqual(
                    _sha256(committed),
                    _sha256(generated),
                    f"Committed fixture {committed.name} drifted from seed=42 generator output",
                )

    def test_adr_0001_fixture_exemption_is_documented(self):
        """fixtures/mock_withheld/README.md must explain why ADR 0001 does not apply to test fixtures."""
        readme_path = MOCK_WITHHELD_DIR / "README.md"
        self.assertTrue(readme_path.exists())
        text = readme_path.read_text(encoding="utf-8")
        self.assertIn("ADR 0001", text)
        self.assertIn("Answer Key", text)
        self.assertIn("Reveal", text)
        self.assertIn("test fixture", text.lower())

    def test_full_scale_matches_contract_hospital_counts_and_ids(self):
        """--scale full must produce 90 hospitals and match contract Answer Key IDs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_out = Path(tmpdir) / "dataset"
            tmp_withheld = Path(tmpdir) / "withheld"
            summary = generate_dataset(
                seed=42, scale="full", output_dir=tmp_out, withheld_dir=tmp_withheld
            )
            self.assertEqual(summary["hospitals"], 90)
            self.assertEqual(summary["duplicate_rows"], 40)  # 8 hospitals * 5 days
            self.assertEqual(summary["feed_rows"], 90 * 1127 + 40)
            self.assertEqual(summary["reveal_rows"], 90 * 42)

            ak = summary["answer_key"]
            by_cause = {item["cause"]: item for item in ak["attribution"]}
            self.assertEqual(
                by_cause["pipeline_defect"]["affected_hospitals"],
                [
                    "HOSP_NE_003",
                    "HOSP_NE_007",
                    "HOSP_NE_011",
                    "HOSP_NE_014",
                    "HOSP_NE_016",
                    "HOSP_NE_019",
                    "HOSP_NE_022",
                    "HOSP_NE_025",
                ],
            )
            self.assertEqual(
                by_cause["sampling_artifact"]["affected_hospitals"],
                [
                    "HOSP_NE_002",
                    "HOSP_NE_005",
                    "HOSP_NE_009",
                    "HOSP_NE_013",
                    "HOSP_NE_018",
                    "HOSP_NE_021",
                ],
            )
            self.assertEqual(
                by_cause["outbreak"]["affected_hospitals"],
                ["HOSP_NE_001", "HOSP_NE_004", "HOSP_NE_006"],
            )


class TestMockDatasetStatisticalInvariants(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.hospitals = _read_csv(MOCK_DATASET_DIR / "raw" / "hospital_reference.csv")
        cls.feeds = _read_csv(
            MOCK_DATASET_DIR / "raw" / "hospital_flu_feeds" / "feeds.csv"
        )
        cls.run_log = _read_csv(MOCK_DATASET_DIR / "ops" / "pipeline_run_log.csv")
        cls.reveal = _read_csv(
            MOCK_WITHHELD_DIR / "reveal" / "hospital_flu_feeds_reveal" / "reveal.csv"
        )
        cls.answer_key = json.loads(
            (MOCK_WITHHELD_DIR / "answer_key.json").read_text(encoding="utf-8")
        )
        cls.hosp_by_id = {h["hospital_id"]: h for h in cls.hospitals}

    def test_regions_and_history_span_for_backtest_and_reveal(self):
        """Must have hospitals across >= 2 regions (including Northeast) and full 2025-26 season."""
        regions = {h["region"] for h in self.hospitals}
        self.assertIn("Northeast", regions)
        self.assertGreaterEqual(len(regions), 4)

        dates = sorted({date.fromisoformat(r["feed_date"]) for r in self.feeds})
        self.assertEqual(dates[0], date(2024, 9, 29))
        self.assertEqual(dates[-1], CUTOFF_DATE)

        reveal_dates = sorted({date.fromisoformat(r["feed_date"]) for r in self.reveal})
        self.assertEqual(reveal_dates[0], REVEAL_START_DATE)
        self.assertEqual(reveal_dates[-1], REVEAL_END_DATE)
        self.assertEqual(len(reveal_dates), 42)

    def test_duplicate_feeds_and_pipeline_run_log_correlation(self):
        """Duplicated feeds share (hospital_id, feed_date) and counts, with matching backfill log."""
        by_key: defaultdict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
        for row in self.feeds:
            by_key[(row["hospital_id"], row["feed_date"])].append(row)

        duplicates = {k: v for k, v in by_key.items() if len(v) > 1}
        self.assertEqual(len(duplicates), 20)  # 4 NE pipeline_defect hospitals * 5 days

        pipeline_defect_hospitals = set(
            next(
                a["affected_hospitals"]
                for a in self.answer_key["attribution"]
                if a["cause"] == "pipeline_defect"
            )
        )

        for (hid, fdate_str), rows in duplicates.items():
            self.assertEqual(len(rows), 2)
            self.assertIn(hid, pipeline_defect_hospitals)
            fdate = date.fromisoformat(fdate_str)
            self.assertTrue(BACKFILL_START_DATE <= fdate <= BACKFILL_END_DATE)

            # Sort by ingested_at ASC
            ordered = sorted(rows, key=lambda r: r["ingested_at"])
            orig, dup = ordered[0], ordered[1]
            self.assertEqual(orig["total_flu_tests"], dup["total_flu_tests"])
            self.assertEqual(orig["positive_flu_tests"], dup["positive_flu_tests"])
            self.assertNotEqual(orig["batch_id"], dup["batch_id"])
            self.assertEqual(dup["batch_id"], BACKFILL_BATCH_ID)
            self.assertEqual(dup["ingested_at"], BACKFILL_INGESTED_AT)

        # Verify matching backfill entry in ops.pipeline_run_log
        backfill_runs = [r for r in self.run_log if r["run_type"] == "backfill"]
        self.assertEqual(len(backfill_runs), 1)
        bf = backfill_runs[0]
        self.assertEqual(bf["run_id"], BACKFILL_RUN_ID)
        self.assertEqual(bf["date_range_start"], BACKFILL_START_DATE.isoformat())
        self.assertEqual(bf["date_range_end"], BACKFILL_END_DATE.isoformat())
        self.assertEqual(bf["status"], "SUCCESS")
        self.assertEqual(int(bf["rows_written"]), 20)

    def test_headline_spike_and_four_planted_causes_attribution(self):
        """Northeast Spike must be +35.0% raw and decompose into 15 + 8 + 7 + 5 points."""
        ne_ids = {
            h["hospital_id"] for h in self.hospitals if h["region"] == "Northeast"
        }
        ak_causes = {a["cause"]: a for a in self.answer_key["attribution"]}
        sampling_ids = set(ak_causes["sampling_artifact"]["affected_hospitals"])
        outbreak_ids = set(ak_causes["outbreak"]["affected_hospitals"])

        w42_pos_raw = 0
        w43_pos_raw = 0
        w43_pos_clean = 0

        # Track clean per-group counts in W42 and W43
        deduped: dict[tuple[str, str], dict[str, str]] = {}
        for row in self.feeds:
            key = (row["hospital_id"], row["feed_date"])
            if key not in deduped or (row["ingested_at"], row["batch_id"]) > (
                deduped[key]["ingested_at"],
                deduped[key]["batch_id"],
            ):
                deduped[key] = row

        for row in self.feeds:
            if row["hospital_id"] not in ne_ids:
                continue
            d = date.fromisoformat(row["feed_date"])
            pos = int(row["positive_flu_tests"])
            if BASELINE_WEEK_START <= d <= BASELINE_WEEK_END:
                w42_pos_raw += pos
            elif SPIKE_WEEK_START <= d <= CUTOFF_DATE:
                w43_pos_raw += pos

        w42_group_pos = defaultdict(int)
        w42_group_tot = defaultdict(int)
        w43_group_pos = defaultdict(int)
        w43_group_tot = defaultdict(int)

        for (hid, fdate_str), row in deduped.items():
            if hid not in ne_ids:
                continue
            d = date.fromisoformat(fdate_str)
            pos = int(row["positive_flu_tests"])
            tot = int(row["total_flu_tests"])
            group = (
                "sampling"
                if hid in sampling_ids
                else ("outbreak" if hid in outbreak_ids else "other_ne")
            )
            if BASELINE_WEEK_START <= d <= BASELINE_WEEK_END:
                w42_group_pos[group] += pos
                w42_group_tot[group] += tot
            elif SPIKE_WEEK_START <= d <= CUTOFF_DATE:
                w43_pos_clean += pos
                w43_group_pos[group] += pos
                w43_group_tot[group] += tot

        headline_spike_pct = ((w43_pos_raw - w42_pos_raw) / w42_pos_raw) * 100.0
        self.assertAlmostEqual(headline_spike_pct, 35.0, places=2)

        # 1. Pipeline Defect share
        pipeline_pts = ((w43_pos_raw - w43_pos_clean) / w42_pos_raw) * 100.0
        self.assertAlmostEqual(
            pipeline_pts, ak_causes["pipeline_defect"]["target_points"], places=2
        )

        # 2. Sampling Artifact share (excess over 5% Seasonal Ramp)
        sampling_excess = w43_group_pos["sampling"] - round(
            w42_group_pos["sampling"] * 1.05
        )
        sampling_pts = (sampling_excess / w42_pos_raw) * 100.0
        self.assertAlmostEqual(
            sampling_pts, ak_causes["sampling_artifact"]["target_points"], places=2
        )

        # Verify Sampling Artifact hospitals increased volume ~48% with flat Positivity
        vol_growth = (
            w43_group_tot["sampling"] - w42_group_tot["sampling"]
        ) / w42_group_tot["sampling"]
        self.assertGreater(vol_growth, 0.40)
        pos_w42_samp = w42_group_pos["sampling"] / w42_group_tot["sampling"]
        pos_w43_samp = w43_group_pos["sampling"] / w43_group_tot["sampling"]
        self.assertAlmostEqual(pos_w42_samp, pos_w43_samp, delta=0.005)

        # 3. Outbreak share (excess over 5% Seasonal Ramp)
        outbreak_excess = w43_group_pos["outbreak"] - round(
            w42_group_pos["outbreak"] * 1.05
        )
        outbreak_pts = (outbreak_excess / w42_pos_raw) * 100.0
        self.assertAlmostEqual(
            outbreak_pts, ak_causes["outbreak"]["target_points"], places=2
        )

        # Verify Outbreak Positivity jumped from ~6% to ~16.3% with stable volume
        pos_w42_out = w42_group_pos["outbreak"] / w42_group_tot["outbreak"]
        pos_w43_out = w43_group_pos["outbreak"] / w43_group_tot["outbreak"]
        self.assertAlmostEqual(pos_w42_out, 0.06, delta=0.01)
        self.assertGreater(pos_w43_out, 0.15)
        self.assertEqual(w42_group_tot["outbreak"], w43_group_tot["outbreak"])

        # 4. Seasonal Ramp share
        seasonal_pts = headline_spike_pct - pipeline_pts - sampling_pts - outbreak_pts
        self.assertAlmostEqual(
            seasonal_pts, ak_causes["seasonal_ramp"]["target_points"], places=2
        )

    def test_simpsons_paradox_and_zero_test_day_invariants(self):
        """Verify Simpson's paradox across Urban vs Non-Urban strata and zero-test ANSI guard."""
        # Check zero-test rows exist for Rural hospitals
        zero_rows = [
            r
            for r in self.feeds
            if int(r["total_flu_tests"]) == 0 and int(r["positive_flu_tests"]) == 0
        ]
        self.assertGreater(
            len(zero_rows),
            0,
            "Dataset must include zero-test days for Spark 4 ANSI division-by-zero tests",
        )

        # Deduplicate feeds
        deduped: dict[tuple[str, str], dict[str, str]] = {}
        for row in self.feeds:
            key = (row["hospital_id"], row["feed_date"])
            if key not in deduped or (row["ingested_at"], row["batch_id"]) > (
                deduped[key]["ingested_at"],
                deduped[key]["batch_id"],
            ):
                deduped[key] = row

        outbreak_ids = {"HOSP_NE_001", "HOSP_NE_004", "HOSP_NE_006"}
        ne_non_outbreak = {
            h["hospital_id"]: h["urban_rural"]
            for h in self.hospitals
            if h["region"] == "Northeast" and h["hospital_id"] not in outbreak_ids
        }

        strata = {
            "Urban": {"w42_pos": 0, "w42_tot": 0, "w43_pos": 0, "w43_tot": 0},
            "NonUrban": {"w42_pos": 0, "w42_tot": 0, "w43_pos": 0, "w43_tot": 0},
        }
        for (hid, fdate_str), row in deduped.items():
            if hid not in ne_non_outbreak:
                continue
            d = date.fromisoformat(fdate_str)
            bucket = "Urban" if ne_non_outbreak[hid] == "Urban" else "NonUrban"
            pos = int(row["positive_flu_tests"])
            tot = int(row["total_flu_tests"])
            if BASELINE_WEEK_START <= d <= BASELINE_WEEK_END:
                strata[bucket]["w42_pos"] += pos
                strata[bucket]["w42_tot"] += tot
            elif SPIKE_WEEK_START <= d <= CUTOFF_DATE:
                strata[bucket]["w43_pos"] += pos
                strata[bucket]["w43_tot"] += tot

        urban_w42_rate = strata["Urban"]["w42_pos"] / strata["Urban"]["w42_tot"]
        urban_w43_rate = strata["Urban"]["w43_pos"] / strata["Urban"]["w43_tot"]
        nonurban_w42_rate = (
            strata["NonUrban"]["w42_pos"] / strata["NonUrban"]["w42_tot"]
        )
        nonurban_w43_rate = (
            strata["NonUrban"]["w43_pos"] / strata["NonUrban"]["w43_tot"]
        )

        agg_w42_rate = (strata["Urban"]["w42_pos"] + strata["NonUrban"]["w42_pos"]) / (
            strata["Urban"]["w42_tot"] + strata["NonUrban"]["w42_tot"]
        )
        agg_w43_rate = (strata["Urban"]["w43_pos"] + strata["NonUrban"]["w43_pos"]) / (
            strata["Urban"]["w43_tot"] + strata["NonUrban"]["w43_tot"]
        )

        # Simpson's Paradox: Positivity rises in BOTH strata individually, yet DROPS in aggregate!
        self.assertGreater(urban_w43_rate, urban_w42_rate)
        self.assertGreater(nonurban_w43_rate, nonurban_w42_rate)
        self.assertLess(agg_w43_rate, agg_w42_rate)

    def test_four_cohort_separation_and_reveal_overshoot(self):
        """Outbreak hospitals must be distinct on seasonal features, and uncleaned forecast must overshoot Reveal."""
        ne_ids = {
            h["hospital_id"] for h in self.hospitals if h["region"] == "Northeast"
        }
        w42_raw = sum(
            int(r["positive_flu_tests"])
            for r in self.feeds
            if r["hospital_id"] in ne_ids
            and BASELINE_WEEK_START
            <= date.fromisoformat(r["feed_date"])
            <= BASELINE_WEEK_END
        )
        w43_raw = sum(
            int(r["positive_flu_tests"])
            for r in self.feeds
            if r["hospital_id"] in ne_ids
            and SPIKE_WEEK_START <= date.fromisoformat(r["feed_date"]) <= CUTOFF_DATE
        )

        # Uncleaned weekly slope (+35% jump in W43) projected across the 6 Reveal weeks
        uncleaned_weekly_delta = w43_raw - w42_raw
        uncleaned_6wk_projection = sum(
            w43_raw + uncleaned_weekly_delta * wk for wk in range(1, 7)
        )

        reveal_ne_total = sum(
            int(r["positive_flu_tests"])
            for r in self.reveal
            if r["hospital_id"] in ne_ids
        )
        self.assertGreater(
            uncleaned_6wk_projection,
            reveal_ne_total * 1.35,
            "Uncleaned forecast trajectory must visibly overshoot the 6-week Reveal",
        )


class TestLoadRawOpsCLI(unittest.TestCase):
    def test_load_raw_ops_invokes_bq_load_and_labels_all_three_tables(self):
        """bin/load-raw-ops must load raw and ops tables with explicit project/region and label demo:true."""
        self.assertTrue(LOAD_BIN.exists(), "bin/load-raw-ops must exist")
        self.assertTrue(
            os.access(LOAD_BIN, os.X_OK), "bin/load-raw-ops must be executable"
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            env_file = tmp_path / "demo.env"
            env_file.write_text(
                'PROJECT_ID="test-proj-008"\n'
                'REGION="us-central1"\n'
                "export PROJECT_ID\n"
                "export REGION\n",
                encoding="utf-8",
            )

            log_file = tmp_path / "bq_calls.log"
            bin_dir = tmp_path / "bin"
            bin_dir.mkdir()
            fake_bq = bin_dir / "bq"
            fake_bq.write_text(
                f'#!/usr/bin/env bash\necho "$*" >> "{log_file}"\nexit 0\n',
                encoding="utf-8",
            )
            fake_bq.chmod(0o755)

            env = os.environ.copy()
            env["PATH"] = f"{bin_dir}:{env['PATH']}"

            proc = subprocess.run(
                [
                    str(LOAD_BIN),
                    "--env",
                    str(env_file),
                    "--dataset-dir",
                    str(MOCK_DATASET_DIR),
                ],
                cwd=WORKTREE_ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                proc.returncode, 0, f"Output:\n{proc.stdout}\n{proc.stderr}"
            )
            self.assertIn("[PASS]", proc.stdout)

            calls = log_file.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                len(calls), 6, "Expected 3 bq load calls and 3 bq update label calls"
            )

            expected_tables = [
                "test-proj-008:raw.hospital_reference",
                "test-proj-008:raw.hospital_flu_feeds",
                "test-proj-008:ops.pipeline_run_log",
            ]
            for idx, table_ref in enumerate(expected_tables):
                load_call = calls[idx * 2]
                label_call = calls[idx * 2 + 1]
                self.assertIn("--project_id=test-proj-008", load_call)
                self.assertIn("--location=us-central1", load_call)
                self.assertIn("load --replace --source_format=CSV", load_call)
                self.assertIn(table_ref, load_call)

                self.assertIn("--project_id=test-proj-008", label_call)
                self.assertIn("--location=us-central1", label_call)
                self.assertIn("update --set_label demo:true", label_call)
                self.assertIn(table_ref, label_call)

    def test_load_raw_ops_fails_on_placeholder_env(self):
        """bin/load-raw-ops must fail when PROJECT_ID contains a placeholder."""
        proc = subprocess.run(
            [str(LOAD_BIN), "--env", str(WORKTREE_ROOT / "demo.env.example")],
            cwd=WORKTREE_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("[FAIL]", proc.stderr)


if __name__ == "__main__":
    unittest.main()
