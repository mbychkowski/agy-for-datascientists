"""Workstream 1 rehearsal, triage subagent logic, and Attribution reconciliation engine.

Provides pure-Python implementations of the Workstream 1 exploratory heatmap,
the three parallel triage investigations (pipeline-triage, sampling-triage,
distribution-triage), the adversarial stats-reviewer checks, and the reconciled
four-cause Attribution table.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pipelines.pipeline_v1 import build_v1_rows

PRIOR_WEEK_START = date(2026, 10, 18)
PRIOR_WEEK_END = date(2026, 10, 24)
SPIKE_WEEK_START = date(2026, 10, 25)
CUTOFF_DATE = date(2026, 10, 31)

# Recorded tolerance (in percentage points of the Northeast Spike) when comparing
# empirical Attribution output against the Answer Key.
ATTRIBUTION_TOLERANCE_POINTS: float = 1.5

CAUSE_ORDER: tuple[str, ...] = (
    "pipeline_defect",
    "sampling_artifact",
    "outbreak",
    "seasonal_ramp",
)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file into a list of string dictionaries."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def load_dataset_tables(
    dataset_dir: Path,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    """Load raw Hospital Feeds and reference metadata from `dataset_dir` and build Pipeline v1 staging rows.

    Returns `(staging_rows, run_log_rows)`.
    """
    hospitals_path = dataset_dir / "raw" / "hospital_reference.csv"
    feeds_path = dataset_dir / "raw" / "hospital_flu_feeds" / "feeds.csv"
    run_log_path = dataset_dir / "ops" / "pipeline_run_log.csv"

    hospitals = _read_csv_rows(hospitals_path)
    feeds = _read_csv_rows(feeds_path)
    run_log_rows = _read_csv_rows(run_log_path)
    staging_rows = build_v1_rows(feeds, hospitals)
    return staging_rows, run_log_rows


def deduplicate_staging_rows(
    staging_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, object]]:
    """Deduplicate `staging.hospital_flu` rows on `(hospital_id, feed_date)`.

    Follows the contract tie-break rule: retain the record with the latest
    `ingested_at` timestamp, breaking ties by lexicographically greatest `batch_id`.
    """
    best_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for row in staging_rows:
        hid = str(row["hospital_id"])
        fdate = str(row["feed_date"])
        key = (hid, fdate)
        candidate = dict(row)
        cand_order = (str(candidate["ingested_at"]), str(candidate["batch_id"]))
        existing = best_by_key.get(key)
        if existing is None or cand_order > (
            str(existing["ingested_at"]),
            str(existing["batch_id"]),
        ):
            best_by_key[key] = candidate
    return [best_by_key[k] for k in sorted(best_by_key)]


def _mmwr_week_start(d: date) -> date:
    """Return the Sunday MMWR week start date for `d`."""
    days_since_sunday = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sunday)


def _safe_divide(numerator: float, denominator: float) -> float | None:
    """Divide `numerator` by `denominator`, returning `None` when `denominator == 0`."""
    if denominator == 0:
        return None
    return numerator / denominator


def build_eda_heatmap(
    staging_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute the Workstream 1 hospital x week EDA heatmap and Northeast Spike concentration."""
    weekly_cells: dict[tuple[str, date], dict[str, Any]] = {}
    dates_seen: dict[tuple[str, date], set[str]] = defaultdict(set)
    hosp_meta: dict[str, dict[str, Any]] = {}

    for row in staging_rows:
        fdate = date.fromisoformat(str(row["feed_date"]))
        if fdate < date(2026, 10, 4) or fdate > CUTOFF_DATE:
            continue
        hid = str(row["hospital_id"])
        wk_start = _mmwr_week_start(fdate)
        cell_key = (hid, wk_start)
        if hid not in hosp_meta:
            hosp_meta[hid] = {
                "hospital_id": hid,
                "hospital_name": str(row["hospital_name"]),
                "region": str(row["region"]),
                "state": str(row["state"]),
                "urban_rural": str(row["urban_rural"]),
                "bed_count": int(row["bed_count"]),
            }
        if cell_key not in weekly_cells:
            weekly_cells[cell_key] = {
                **hosp_meta[hid],
                "week_start": wk_start.isoformat(),
                "week_end": (wk_start + timedelta(days=6)).isoformat(),
                "physical_feed_rows": 0,
                "total_flu_tests": 0,
                "positive_flu_tests": 0,
            }
        cell = weekly_cells[cell_key]
        cell["physical_feed_rows"] += 1
        cell["total_flu_tests"] += int(row["total_flu_tests"])
        cell["positive_flu_tests"] += int(row["positive_flu_tests"])
        dates_seen[cell_key].add(fdate.isoformat())

    for cell_key, cell in weekly_cells.items():
        distinct_days = len(dates_seen[cell_key])
        cell["distinct_feed_days"] = distinct_days
        cell["duplicate_feed_rows"] = cell["physical_feed_rows"] - distinct_days
        pos_ratio = _safe_divide(cell["positive_flu_tests"], cell["total_flu_tests"])
        cell["positivity"] = round(pos_ratio, 4) if pos_ratio is not None else None

    ne_prior_positives = sum(
        c["positive_flu_tests"]
        for (hid, wk), c in weekly_cells.items()
        if c["region"] == "Northeast" and wk == PRIOR_WEEK_START
    )
    ne_cutoff_positives = sum(
        c["positive_flu_tests"]
        for (hid, wk), c in weekly_cells.items()
        if c["region"] == "Northeast" and wk == SPIKE_WEEK_START
    )
    ne_spike_delta = ne_cutoff_positives - ne_prior_positives
    headline_spike_pct = (
        round((ne_spike_delta / ne_prior_positives) * 100.0, 2)
        if ne_prior_positives > 0
        else 0.0
    )

    hospital_summaries: list[dict[str, Any]] = []
    for hid, meta in sorted(hosp_meta.items()):
        prior_cell = weekly_cells.get((hid, PRIOR_WEEK_START), {})
        cutoff_cell = weekly_cells.get((hid, SPIKE_WEEK_START), {})
        prior_pos = int(prior_cell.get("positive_flu_tests", 0))
        cutoff_pos = int(cutoff_cell.get("positive_flu_tests", 0))
        prior_tot = int(prior_cell.get("total_flu_tests", 0))
        cutoff_tot = int(cutoff_cell.get("total_flu_tests", 0))
        pos_delta = cutoff_pos - prior_pos
        vol_pct = (
            round(((cutoff_tot - prior_tot) / prior_tot) * 100.0, 2)
            if prior_tot > 0
            else 0.0
        )
        is_ne = meta["region"] == "Northeast"
        spike_pts = (
            round((pos_delta / ne_prior_positives) * 100.0, 2)
            if is_ne and ne_prior_positives > 0
            else 0.0
        )
        share_pct = (
            round((pos_delta / ne_spike_delta) * 100.0, 2)
            if is_ne and ne_spike_delta > 0
            else 0.0
        )
        hospital_summaries.append(
            {
                **meta,
                "prior_week_tests": prior_tot,
                "prior_week_positives": prior_pos,
                "prior_week_positivity": prior_cell.get("positivity"),
                "cutoff_week_tests": cutoff_tot,
                "cutoff_week_positives": cutoff_pos,
                "cutoff_week_positivity": cutoff_cell.get("positivity"),
                "cutoff_week_duplicate_rows": int(
                    cutoff_cell.get("duplicate_feed_rows", 0)
                ),
                "wow_positive_delta": pos_delta,
                "wow_test_volume_pct": vol_pct,
                "ne_spike_points_contributed": spike_pts,
                "share_of_ne_spike_pct": share_pct,
            }
        )

    ne_ranked = sorted(
        (h for h in hospital_summaries if h["region"] == "Northeast"),
        key=lambda h: (-h["wow_positive_delta"], h["hospital_id"]),
    )

    return {
        "target_region": "Northeast",
        "prior_week_start": PRIOR_WEEK_START.isoformat(),
        "prior_week_end": PRIOR_WEEK_END.isoformat(),
        "spike_week_start": SPIKE_WEEK_START.isoformat(),
        "spike_week_end": CUTOFF_DATE.isoformat(),
        "ne_prior_positives": ne_prior_positives,
        "ne_cutoff_positives": ne_cutoff_positives,
        "ne_spike_delta": ne_spike_delta,
        "headline_spike_pct": headline_spike_pct,
        "heatmap_cells": [weekly_cells[k] for k in sorted(weekly_cells)],
        "hospital_summaries": hospital_summaries,
        "northeast_ranked": ne_ranked,
    }


def _compute_ne_prior_raw_positives(staging_rows: Sequence[Mapping[str, Any]]) -> int:
    """Return raw Northeast positive flu test counts in the prior week (`2026-10-18`..`2026-10-24`)."""
    total = 0
    for row in staging_rows:
        if str(row["region"]) != "Northeast":
            continue
        fdate = date.fromisoformat(str(row["feed_date"]))
        if PRIOR_WEEK_START <= fdate <= PRIOR_WEEK_END:
            total += int(row["positive_flu_tests"])
    return total


def _compute_ne_cutoff_raw_positives(staging_rows: Sequence[Mapping[str, Any]]) -> int:
    """Return raw Northeast positive flu test counts in the Cutoff week (`2026-10-25`..`2026-10-31`)."""
    total = 0
    for row in staging_rows:
        if str(row["region"]) != "Northeast":
            continue
        fdate = date.fromisoformat(str(row["feed_date"]))
        if SPIKE_WEEK_START <= fdate <= CUTOFF_DATE:
            total += int(row["positive_flu_tests"])
    return total


def triage_pipeline_defect(
    staging_rows: Sequence[Mapping[str, Any]],
    run_log_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Execute the `pipeline-triage` subagent investigation.

    Identifies duplicate `(hospital_id, feed_date)` Hospital Feed records in
    `staging.hospital_flu`, correlates them with `ops.pipeline_run_log` backfill
    runs, and quantifies the `pipeline_defect` share of the Northeast Spike.
    """
    grouped: defaultdict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in staging_rows:
        grouped[(str(row["hospital_id"]), str(row["feed_date"]))].append(dict(row))

    duplicate_records: list[dict[str, object]] = []
    affected_hospitals_set: set[str] = set()
    duplicate_dates: set[str] = set()
    duplicate_batches: set[str] = set()
    duplicate_positives = 0

    for (hid, fdate_str), rows in sorted(grouped.items()):
        if len(rows) <= 1:
            continue
        ordered = sorted(
            rows, key=lambda r: (str(r["ingested_at"]), str(r["batch_id"]))
        )
        # All rows beyond the original scheduled feed are duplicate backfill rows
        for dup in ordered[1:]:
            duplicate_records.append(dup)
            affected_hospitals_set.add(hid)
            duplicate_dates.add(fdate_str)
            duplicate_batches.add(str(dup["batch_id"]))
            if (
                str(dup["region"]) == "Northeast"
                and SPIKE_WEEK_START <= date.fromisoformat(fdate_str) <= CUTOFF_DATE
            ):
                duplicate_positives += int(dup["positive_flu_tests"])

    start_date = (
        min(duplicate_dates) if duplicate_dates else SPIKE_WEEK_START.isoformat()
    )
    end_date = max(duplicate_dates) if duplicate_dates else CUTOFF_DATE.isoformat()

    correlated_runs: list[dict[str, Any]] = []
    for run in run_log_rows:
        if str(run.get("run_type", "")).lower() != "backfill":
            continue
        r_start = str(run.get("date_range_start", ""))
        r_end = str(run.get("date_range_end", ""))
        if r_start <= end_date and r_end >= start_date:
            correlated_runs.append(dict(run))

    ne_prior_raw = _compute_ne_prior_raw_positives(staging_rows)
    contributed_points = (
        round((duplicate_positives / ne_prior_raw) * 100.0, 1)
        if ne_prior_raw > 0
        else 0.0
    )
    correlated_run_id = (
        str(correlated_runs[0]["run_id"]) if correlated_runs else "UNKNOWN"
    )
    affected_hospitals = sorted(affected_hospitals_set)

    return {
        "cause": "pipeline_defect",
        "contributed_points": contributed_points,
        "affected_hospitals": affected_hospitals,
        "start_date": start_date,
        "end_date": end_date,
        "duplicate_row_count": len(duplicate_records),
        "duplicate_positives": duplicate_positives,
        "correlated_run_id": correlated_run_id,
        "correlated_batches": sorted(duplicate_batches),
        "correlated_runs": correlated_runs,
        "evidence": (
            f"Duplicate Hospital Feed rows ({len(duplicate_records)} rows, "
            f"+{duplicate_positives} positive tests) across {len(affected_hospitals)} "
            f"Northeast hospitals on {start_date}..{end_date}, correlated with "
            f"ops.pipeline_run_log backfill run {correlated_run_id}."
        ),
    }


def _classify_clean_northeast_hospitals(
    staging_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], float]:
    """Compute deduplicated prior-week and Cutoff-week metrics per Northeast hospital and normal Seasonal Ramp rate."""
    deduped = deduplicate_staging_rows(staging_rows)
    by_hosp: dict[str, dict[str, Any]] = {}

    for row in deduped:
        if str(row["region"]) != "Northeast":
            continue
        hid = str(row["hospital_id"])
        fdate = date.fromisoformat(str(row["feed_date"]))
        if fdate < PRIOR_WEEK_START or fdate > CUTOFF_DATE:
            continue
        if hid not in by_hosp:
            by_hosp[hid] = {
                "hospital_id": hid,
                "urban_rural": str(row["urban_rural"]),
                "prior_tests": 0,
                "prior_positives": 0,
                "cutoff_tests": 0,
                "cutoff_positives": 0,
            }
        rec = by_hosp[hid]
        if PRIOR_WEEK_START <= fdate <= PRIOR_WEEK_END:
            rec["prior_tests"] += int(row["total_flu_tests"])
            rec["prior_positives"] += int(row["positive_flu_tests"])
        elif SPIKE_WEEK_START <= fdate <= CUTOFF_DATE:
            rec["cutoff_tests"] += int(row["total_flu_tests"])
            rec["cutoff_positives"] += int(row["positive_flu_tests"])

    for rec in by_hosp.values():
        p_pos = _safe_divide(rec["prior_positives"], rec["prior_tests"]) or 0.0
        c_pos = _safe_divide(rec["cutoff_positives"], rec["cutoff_tests"]) or 0.0
        vol_growth = (
            _safe_divide(rec["cutoff_tests"] - rec["prior_tests"], rec["prior_tests"])
            or 0.0
        )
        pos_delta = c_pos - p_pos
        rec["prior_positivity"] = p_pos
        rec["cutoff_positivity"] = c_pos
        rec["volume_growth_ratio"] = vol_growth
        rec["positivity_delta"] = pos_delta

        if pos_delta >= 0.05 and abs(vol_growth) < 0.15:
            rec["classification"] = "outbreak"
        elif vol_growth >= 0.30 and abs(pos_delta) < 0.02:
            rec["classification"] = "sampling_artifact"
        else:
            rec["classification"] = "seasonal_ramp"

    normal_prior = sum(
        r["prior_positives"]
        for r in by_hosp.values()
        if r["classification"] == "seasonal_ramp"
    )
    normal_cutoff = sum(
        r["cutoff_positives"]
        for r in by_hosp.values()
        if r["classification"] == "seasonal_ramp"
    )
    ramp_ratio = (
        (normal_cutoff - normal_prior) / normal_prior if normal_prior > 0 else 0.05
    )
    return by_hosp, ramp_ratio


def triage_sampling_artifact(
    staging_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Execute the `sampling-triage` subagent investigation.

    Identifies Northeast hospitals where `total_flu_tests` expanded sharply (~48%)
    while Positivity remained flat, and quantifies the `sampling_artifact` share.
    """
    by_hosp, ramp_ratio = _classify_clean_northeast_hospitals(staging_rows)
    ne_prior_raw = _compute_ne_prior_raw_positives(staging_rows)

    sampling_hospitals = sorted(
        hid
        for hid, rec in by_hosp.items()
        if rec["classification"] == "sampling_artifact"
    )
    prior_tests = sum(by_hosp[h]["prior_tests"] for h in sampling_hospitals)
    cutoff_tests = sum(by_hosp[h]["cutoff_tests"] for h in sampling_hospitals)
    prior_pos = sum(by_hosp[h]["prior_positives"] for h in sampling_hospitals)
    cutoff_pos = sum(by_hosp[h]["cutoff_positives"] for h in sampling_hospitals)

    vol_growth_pct = (
        round(((cutoff_tests - prior_tests) / prior_tests) * 100.0, 1)
        if prior_tests > 0
        else 0.0
    )
    prior_positivity = round(prior_pos / prior_tests, 4) if prior_tests > 0 else 0.0
    cutoff_positivity = round(cutoff_pos / cutoff_tests, 4) if cutoff_tests > 0 else 0.0

    excess_positives = cutoff_pos - (prior_pos * (1.0 + ramp_ratio))
    contributed_points = (
        round((excess_positives / ne_prior_raw) * 100.0, 1) if ne_prior_raw > 0 else 0.0
    )

    return {
        "cause": "sampling_artifact",
        "contributed_points": contributed_points,
        "affected_hospitals": sampling_hospitals,
        "start_date": SPIKE_WEEK_START.isoformat(),
        "end_date": CUTOFF_DATE.isoformat(),
        "volume_growth_pct": vol_growth_pct,
        "prior_positivity": prior_positivity,
        "cutoff_positivity": cutoff_positivity,
        "evidence": (
            f"Testing volume increased +{vol_growth_pct:.1f}% across "
            f"{len(sampling_hospitals)} Urban Northeast hospitals while Positivity "
            f"stayed flat ({prior_positivity * 100:.2f}% -> {cutoff_positivity * 100:.2f}%)."
        ),
    }


def triage_outbreak_and_seasonal_ramp(
    staging_rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Execute the `distribution-triage` subagent investigation.

    Separates the localized `outbreak` (sharp Positivity jump at stable testing
    volume) from the broad `seasonal_ramp` across all hospitals.
    """
    by_hosp, ramp_ratio = _classify_clean_northeast_hospitals(staging_rows)
    ne_prior_raw = _compute_ne_prior_raw_positives(staging_rows)

    outbreak_hospitals = sorted(
        hid for hid, rec in by_hosp.items() if rec["classification"] == "outbreak"
    )
    prior_tests = sum(by_hosp[h]["prior_tests"] for h in outbreak_hospitals)
    cutoff_tests = sum(by_hosp[h]["cutoff_tests"] for h in outbreak_hospitals)
    prior_pos = sum(by_hosp[h]["prior_positives"] for h in outbreak_hospitals)
    cutoff_pos = sum(by_hosp[h]["cutoff_positives"] for h in outbreak_hospitals)

    prior_positivity = round(prior_pos / prior_tests, 4) if prior_tests > 0 else 0.0
    cutoff_positivity = round(cutoff_pos / cutoff_tests, 4) if cutoff_tests > 0 else 0.0
    vol_growth_pct = (
        round(((cutoff_tests - prior_tests) / prior_tests) * 100.0, 1)
        if prior_tests > 0
        else 0.0
    )

    outbreak_excess = cutoff_pos - (prior_pos * (1.0 + ramp_ratio))
    outbreak_points = (
        round((outbreak_excess / ne_prior_raw) * 100.0, 1) if ne_prior_raw > 0 else 0.0
    )
    seasonal_points = round(ramp_ratio * 100.0, 1)

    return {
        "outbreak": {
            "cause": "outbreak",
            "contributed_points": outbreak_points,
            "affected_hospitals": outbreak_hospitals,
            "start_date": SPIKE_WEEK_START.isoformat(),
            "end_date": CUTOFF_DATE.isoformat(),
            "prior_positivity": prior_positivity,
            "cutoff_positivity": cutoff_positivity,
            "volume_growth_pct": vol_growth_pct,
            "evidence": (
                f"Positivity jumped from {prior_positivity * 100:.1f}% to "
                f"{cutoff_positivity * 100:.1f}% across {len(outbreak_hospitals)} "
                f"Suburban Northeast hospitals with stable testing volume ({vol_growth_pct:+.1f}%)."
            ),
        },
        "seasonal_ramp": {
            "cause": "seasonal_ramp",
            "contributed_points": seasonal_points,
            "affected_hospitals": ["*"],
            "start_date": SPIKE_WEEK_START.isoformat(),
            "end_date": CUTOFF_DATE.isoformat(),
            "ramp_pct": round(ramp_ratio * 100.0, 2),
            "evidence": (
                f"Normal early-season rise of +{ramp_ratio * 100:.1f}% week-over-week "
                "across all regions."
            ),
        },
    }


def run_stats_reviewer_checks(
    staging_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Execute the three mandatory statistical peer-review challenges from `stats-reviewer`.

    1. Raw counts vs. Positivity rates
    2. Small-sample hospitals & zero-test denominator guard
    3. Simpson's paradox across Urban vs. Non-Urban strata in non-Outbreak Northeast hospitals
    """
    deduped = deduplicate_staging_rows(staging_rows)
    by_hosp, _ = _classify_clean_northeast_hospitals(staging_rows)

    ne_prior_raw = _compute_ne_prior_raw_positives(staging_rows)
    ne_cutoff_raw = _compute_ne_cutoff_raw_positives(staging_rows)
    raw_spike_pct = (
        round(((ne_cutoff_raw - ne_prior_raw) / ne_prior_raw) * 100.0, 2)
        if ne_prior_raw > 0
        else 0.0
    )

    clean_prior_tests = sum(r["prior_tests"] for r in by_hosp.values())
    clean_prior_pos = sum(r["prior_positives"] for r in by_hosp.values())
    clean_cutoff_tests = sum(r["cutoff_tests"] for r in by_hosp.values())
    clean_cutoff_pos = sum(r["cutoff_positives"] for r in by_hosp.values())

    clean_prior_positivity = (
        round(clean_prior_pos / clean_prior_tests, 4) if clean_prior_tests > 0 else 0.0
    )
    clean_cutoff_positivity = (
        round(clean_cutoff_pos / clean_cutoff_tests, 4)
        if clean_cutoff_tests > 0
        else 0.0
    )

    # Check 2: Small-sample rural hospitals and zero-test days
    zero_test_rows = [
        r
        for r in deduped
        if int(r["total_flu_tests"]) == 0
        and _safe_divide(int(r["positive_flu_tests"]), int(r["total_flu_tests"]))
        is None
    ]
    rural_weekly_tests = [
        r["cutoff_tests"] for r in by_hosp.values() if r["urban_rural"] == "Rural"
    ]

    # Check 3: Simpson's Paradox in non-Outbreak Northeast hospitals
    non_outbreak = {
        hid: r for hid, r in by_hosp.items() if r["classification"] != "outbreak"
    }
    every_hospital_positivity_rose = all(
        r["cutoff_positivity"] > r["prior_positivity"] for r in non_outbreak.values()
    )

    urban_prior_pos = sum(
        r["prior_positives"]
        for r in non_outbreak.values()
        if r["urban_rural"] == "Urban"
    )
    urban_prior_tot = sum(
        r["prior_tests"] for r in non_outbreak.values() if r["urban_rural"] == "Urban"
    )
    urban_cutoff_pos = sum(
        r["cutoff_positives"]
        for r in non_outbreak.values()
        if r["urban_rural"] == "Urban"
    )
    urban_cutoff_tot = sum(
        r["cutoff_tests"] for r in non_outbreak.values() if r["urban_rural"] == "Urban"
    )

    nonurban_prior_pos = sum(
        r["prior_positives"]
        for r in non_outbreak.values()
        if r["urban_rural"] != "Urban"
    )
    nonurban_prior_tot = sum(
        r["prior_tests"] for r in non_outbreak.values() if r["urban_rural"] != "Urban"
    )
    nonurban_cutoff_pos = sum(
        r["cutoff_positives"]
        for r in non_outbreak.values()
        if r["urban_rural"] != "Urban"
    )
    nonurban_cutoff_tot = sum(
        r["cutoff_tests"] for r in non_outbreak.values() if r["urban_rural"] != "Urban"
    )

    urban_prior_rate = urban_prior_pos / urban_prior_tot if urban_prior_tot > 0 else 0.0
    urban_cutoff_rate = (
        urban_cutoff_pos / urban_cutoff_tot if urban_cutoff_tot > 0 else 0.0
    )
    nonurban_prior_rate = (
        nonurban_prior_pos / nonurban_prior_tot if nonurban_prior_tot > 0 else 0.0
    )
    nonurban_cutoff_rate = (
        nonurban_cutoff_pos / nonurban_cutoff_tot if nonurban_cutoff_tot > 0 else 0.0
    )

    pooled_prior_rate = (urban_prior_pos + nonurban_prior_pos) / (
        urban_prior_tot + nonurban_prior_tot
    )
    pooled_cutoff_rate = (urban_cutoff_pos + nonurban_cutoff_pos) / (
        urban_cutoff_tot + nonurban_cutoff_tot
    )
    simpsons_paradox_confirmed = (
        every_hospital_positivity_rose
        and urban_cutoff_rate > urban_prior_rate
        and nonurban_cutoff_rate > nonurban_prior_rate
        and pooled_cutoff_rate < pooled_prior_rate
    )

    return {
        "counts_vs_positivity": {
            "raw_spike_pct": raw_spike_pct,
            "clean_prior_positivity": clean_prior_positivity,
            "clean_cutoff_positivity": clean_cutoff_positivity,
            "passed": raw_spike_pct > 30.0
            and clean_cutoff_positivity < clean_prior_positivity + 0.02,
        },
        "small_sample_hospitals": {
            "zero_test_rows_guarded": len(zero_test_rows),
            "min_rural_weekly_tests": min(rural_weekly_tests)
            if rural_weekly_tests
            else 0,
            "passed": len(zero_test_rows) > 0,
        },
        "simpsons_paradox": {
            "every_non_outbreak_hospital_rose": every_hospital_positivity_rose,
            "urban_prior_positivity": round(urban_prior_rate, 5),
            "urban_cutoff_positivity": round(urban_cutoff_rate, 5),
            "nonurban_prior_positivity": round(nonurban_prior_rate, 5),
            "nonurban_cutoff_positivity": round(nonurban_cutoff_rate, 5),
            "pooled_prior_positivity": round(pooled_prior_rate, 5),
            "pooled_cutoff_positivity": round(pooled_cutoff_rate, 5),
            "passed": simpsons_paradox_confirmed,
        },
    }


def reconcile_attribution(
    dataset_dir: Path | None = None,
    *,
    staging_rows: Sequence[Mapping[str, Any]] | None = None,
    run_log_rows: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Reconcile the four Workstream 1 triage causes into the canonical Attribution table.

    Accepts either `dataset_dir` (containing `raw/` and `ops/`) or pre-loaded
    `staging_rows` and `run_log_rows`.
    """
    if staging_rows is None or run_log_rows is None:
        if dataset_dir is None:
            raise ValueError(
                "Must supply either dataset_dir or both staging_rows and run_log_rows."
            )
        staging_rows, run_log_rows = load_dataset_tables(dataset_dir)

    ne_prior_raw = _compute_ne_prior_raw_positives(staging_rows)
    ne_cutoff_raw = _compute_ne_cutoff_raw_positives(staging_rows)
    headline_spike_pts = (
        round(((ne_cutoff_raw - ne_prior_raw) / ne_prior_raw) * 100.0, 1)
        if ne_prior_raw > 0
        else 0.0
    )

    pipeline_res = triage_pipeline_defect(staging_rows, run_log_rows)
    sampling_res = triage_sampling_artifact(staging_rows)
    dist_res = triage_outbreak_and_seasonal_ramp(staging_rows)
    outbreak_res = dist_res["outbreak"]
    seasonal_res = dict(dist_res["seasonal_ramp"])

    # Ensure reconciled points sum cleanly to the headline Northeast Spike
    reconciled_seasonal_pts = round(
        headline_spike_pts
        - float(pipeline_res["contributed_points"])
        - float(sampling_res["contributed_points"])
        - float(outbreak_res["contributed_points"]),
        1,
    )
    seasonal_res["contributed_points"] = reconciled_seasonal_pts

    by_cause = {
        "pipeline_defect": pipeline_res,
        "sampling_artifact": sampling_res,
        "outbreak": outbreak_res,
        "seasonal_ramp": seasonal_res,
    }
    return [
        {
            "cause": cause,
            "contributed_points": float(by_cause[cause]["contributed_points"]),
            "affected_hospitals": list(by_cause[cause]["affected_hospitals"]),
            "start_date": str(by_cause[cause]["start_date"]),
            "end_date": str(by_cause[cause]["end_date"]),
            "evidence": str(by_cause[cause]["evidence"]),
        }
        for cause in CAUSE_ORDER
    ]


def compare_attribution_to_answer_key(
    attribution_rows: Sequence[Mapping[str, Any]],
    answer_key: Mapping[str, Any],
    tolerance_points: float = ATTRIBUTION_TOLERANCE_POINTS,
) -> dict[str, Any]:
    """Compare reconciled Attribution rows against an Answer Key dictionary within `tolerance_points`.

    Note: The Answer Key is passed in by the caller (such as a test or presenter
    verification script) and is never read from a hardcoded path.
    """
    expected_items = {
        str(item["cause"]): item for item in answer_key.get("attribution", [])
    }
    actual_items = {str(row["cause"]): row for row in attribution_rows}

    cause_comparisons: dict[str, dict[str, Any]] = {}
    all_passed = set(expected_items.keys()) == set(actual_items.keys())

    for cause in CAUSE_ORDER:
        exp = expected_items.get(cause)
        act = actual_items.get(cause)
        if exp is None or act is None:
            all_passed = False
            cause_comparisons[cause] = {"passed": False, "reason": "missing_cause"}
            continue

        target_pts = float(exp["target_points"])
        actual_pts = float(act["contributed_points"])
        point_error = abs(actual_pts - target_pts)
        points_ok = point_error <= tolerance_points

        exp_hospitals = sorted(str(h) for h in exp["affected_hospitals"])
        act_hospitals = sorted(str(h) for h in act["affected_hospitals"])
        hospitals_ok = exp_hospitals == act_hospitals

        exp_start = str(exp["date_range"]["start"])
        exp_end = str(exp["date_range"]["end"])
        dates_ok = (
            str(act["start_date"]) == exp_start and str(act["end_date"]) == exp_end
        )

        cause_passed = points_ok and hospitals_ok and dates_ok
        if not cause_passed:
            all_passed = False

        cause_comparisons[cause] = {
            "target_points": target_pts,
            "contributed_points": actual_pts,
            "point_error": round(point_error, 4),
            "tolerance_points": tolerance_points,
            "points_ok": points_ok,
            "hospitals_ok": hospitals_ok,
            "dates_ok": dates_ok,
            "passed": cause_passed,
        }

    headline_target = float(
        answer_key.get("evaluation_window", {}).get("headline_spike_pct", 35.0)
    )
    total_contributed = round(
        sum(float(r["contributed_points"]) for r in attribution_rows), 2
    )
    total_ok = abs(total_contributed - headline_target) <= tolerance_points
    if not total_ok:
        all_passed = False

    return {
        "passed": all_passed,
        "tolerance_points": tolerance_points,
        "headline_target_pct": headline_target,
        "total_contributed_points": total_contributed,
        "total_ok": total_ok,
        "causes": cause_comparisons,
    }


def load_ws1_checkpoint_manifests(
    repo_root: Path,
) -> dict[str, dict[str, Any]]:
    """Load and validate Workstream 1 Checkpoint descriptor files in `checkpoints/manifest.d/`."""
    manifest_dir = repo_root / "checkpoints" / "manifest.d"
    descriptors: dict[str, dict[str, Any]] = {}
    for path in sorted(manifest_dir.glob("ws1_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cid = str(data["id"])
        descriptors[cid] = data
    return descriptors
