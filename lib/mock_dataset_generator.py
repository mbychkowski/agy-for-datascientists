#!/usr/bin/env python3
"""Deterministic synthetic dataset generator for the Command Center demo.

Conforms to docs/data-generator-contract.md and supports two scales:
  - mini: 20 hospitals across 4 regions, covering 2024-09-29 through the Cutoff
          (2026-10-31) plus a 6-week Reveal (2026-11-01 through 2026-12-12).
  - full: 90 hospitals across 4 regions, covering 2023-10-01 through the Cutoff
          (2026-10-31) plus a 6-week Reveal (2026-11-01 through 2026-12-12).

All terminology adheres to GLOSSARY.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "1.0"

# Key epidemiological dates from docs/data-generator-contract.md
FULL_START_DATE = date(2023, 10, 1)  # MMWR 2023 Week 40
MINI_START_DATE = date(2024, 9, 29)  # MMWR 2024 Week 40
BASELINE_WEEK_START = date(2026, 10, 18)  # MMWR 2026 Week 42 (Sunday)
BASELINE_WEEK_END = date(2026, 10, 24)  # MMWR 2026 Week 42 (Saturday)
SPIKE_WEEK_START = date(2026, 10, 25)  # MMWR 2026 Week 43 (Sunday)
CUTOFF_DATE = date(2026, 10, 31)  # MMWR 2026 Week 43 (Saturday - the Cutoff)
BACKFILL_START_DATE = date(2026, 10, 26)  # Monday of Spike week
BACKFILL_END_DATE = date(2026, 10, 30)  # Friday of Spike week
REVEAL_START_DATE = date(2026, 11, 1)  # MMWR 2026 Week 44 (Sunday)
REVEAL_END_DATE = date(2026, 12, 12)  # MMWR 2026 Week 49 (Saturday)

BACKFILL_RUN_ID = "RUN-20261031-BF01"
BACKFILL_BATCH_ID = "BATCH-20261031-BACKFILL-01"
BACKFILL_STARTED_AT = "2026-10-31 06:15:00 UTC"
BACKFILL_INGESTED_AT = "2026-10-31 06:16:00 UTC"
BACKFILL_FINISHED_AT = "2026-10-31 06:18:42 UTC"

# Dates in off-season where specific Rural hospitals record zero total_flu_tests
# so Spark 4 ANSI division-by-zero handling (Positivity IS NULL) is exercised.
ZERO_TEST_DATES = {date(2025, 7, 15), date(2026, 7, 15)}

FEED_COLUMNS = [
    "hospital_id",
    "feed_date",
    "total_flu_tests",
    "positive_flu_tests",
    "batch_id",
    "ingested_at",
]


def _make_feed_row(
    hospital_id: str,
    feed_date: str,
    total_flu_tests: int,
    positive_flu_tests: int,
    batch_id: str,
    ingested_at: str,
) -> dict[str, Any]:
    """Construct a row dictionary for raw.hospital_flu_feeds or reveal.csv."""
    return {
        "hospital_id": hospital_id,
        "feed_date": feed_date,
        "total_flu_tests": total_flu_tests,
        "positive_flu_tests": positive_flu_tests,
        "batch_id": batch_id,
        "ingested_at": ingested_at,
    }


@dataclass(frozen=True)
class HospitalSpec:
    hospital_id: str
    hospital_name: str
    region: str
    state: str
    urban_rural: str
    bed_count: int
    archetype: str  # 'urban_early' | 'suburban_broad' | 'rural_sharp' | 'outbreak'
    role: str  # 'outbreak' | 'sampling_artifact' | 'pipeline_defect' | 'baseline'


def _build_hospital_specs(scale: str) -> list[HospitalSpec]:
    """Return deterministic hospital specifications for 'mini' (20) or 'full' (90)."""
    if scale == "mini":
        return [
            # Northeast (12 hospitals)
            # 3 Outbreak hospitals (Archetype 4: 'outbreak')
            HospitalSpec(
                "HOSP_NE_001",
                "Pine Valley Medical Center",
                "Northeast",
                "NY",
                "Suburban",
                320,
                "outbreak",
                "outbreak",
            ),
            HospitalSpec(
                "HOSP_NE_002",
                "Metro Boston University Hospital",
                "Northeast",
                "MA",
                "Urban",
                950,
                "urban_early",
                "sampling_artifact",
            ),
            HospitalSpec(
                "HOSP_NE_003",
                "Berkshire Community Clinic",
                "Northeast",
                "MA",
                "Rural",
                90,
                "rural_sharp",
                "pipeline_defect",
            ),
            HospitalSpec(
                "HOSP_NE_004",
                "Hudson River Regional Hospital",
                "Northeast",
                "NY",
                "Suburban",
                280,
                "outbreak",
                "outbreak",
            ),
            HospitalSpec(
                "HOSP_NE_005",
                "Manhattan Central Medical Center",
                "Northeast",
                "NY",
                "Urban",
                1100,
                "urban_early",
                "sampling_artifact",
            ),
            HospitalSpec(
                "HOSP_NE_006",
                "Catskill Valley General",
                "Northeast",
                "NY",
                "Suburban",
                310,
                "outbreak",
                "outbreak",
            ),
            HospitalSpec(
                "HOSP_NE_007",
                "Adirondack Rural Health",
                "Northeast",
                "NY",
                "Rural",
                75,
                "rural_sharp",
                "pipeline_defect",
            ),
            HospitalSpec(
                "HOSP_NE_008",
                "White Mountain Community Hospital",
                "Northeast",
                "NH",
                "Rural",
                85,
                "rural_sharp",
                "baseline",
            ),
            HospitalSpec(
                "HOSP_NE_009",
                "Philadelphia Harbor Health",
                "Northeast",
                "PA",
                "Urban",
                880,
                "urban_early",
                "sampling_artifact",
            ),
            HospitalSpec(
                "HOSP_NE_010",
                "Hartford Charter Hospital",
                "Northeast",
                "CT",
                "Suburban",
                440,
                "suburban_broad",
                "baseline",
            ),
            HospitalSpec(
                "HOSP_NE_011",
                "Allegheny Valley Hospital",
                "Northeast",
                "PA",
                "Suburban",
                410,
                "suburban_broad",
                "pipeline_defect",
            ),
            HospitalSpec(
                "HOSP_NE_014",
                "Champlain Regional Medical",
                "Northeast",
                "VT",
                "Rural",
                110,
                "rural_sharp",
                "pipeline_defect",
            ),
            # Midwest (3 hospitals)
            HospitalSpec(
                "HOSP_MW_001",
                "Great Lakes University Medical",
                "Midwest",
                "IL",
                "Urban",
                920,
                "urban_early",
                "baseline",
            ),
            HospitalSpec(
                "HOSP_MW_002",
                "Prairie View Regional Hospital",
                "Midwest",
                "IA",
                "Suburban",
                380,
                "suburban_broad",
                "baseline",
            ),
            HospitalSpec(
                "HOSP_MW_003",
                "Northwoods Rural Clinic",
                "Midwest",
                "WI",
                "Rural",
                65,
                "rural_sharp",
                "baseline",
            ),
            # South (3 hospitals)
            HospitalSpec(
                "HOSP_SO_001",
                "Peachtree Metro Medical Center",
                "South",
                "GA",
                "Urban",
                890,
                "urban_early",
                "baseline",
            ),
            HospitalSpec(
                "HOSP_SO_002",
                "Blue Ridge Community Hospital",
                "South",
                "NC",
                "Suburban",
                360,
                "suburban_broad",
                "baseline",
            ),
            HospitalSpec(
                "HOSP_SO_003",
                "Bayou Parish Rural Health",
                "South",
                "LA",
                "Rural",
                80,
                "rural_sharp",
                "baseline",
            ),
            # West (2 hospitals)
            HospitalSpec(
                "HOSP_WE_001",
                "Cascade Bay Medical Center",
                "West",
                "WA",
                "Urban",
                840,
                "urban_early",
                "baseline",
            ),
            HospitalSpec(
                "HOSP_WE_002",
                "High Desert Community Clinic",
                "West",
                "NV",
                "Rural",
                70,
                "rural_sharp",
                "baseline",
            ),
        ]

    if scale != "full":
        raise ValueError(f"Unsupported scale '{scale}'. Expected 'mini' or 'full'.")

    # Full contract scale: 90 hospitals (25 NE, 25 MW, 25 SO, 15 WE)
    outbreak_ids = {"HOSP_NE_001", "HOSP_NE_004", "HOSP_NE_006"}
    sampling_ids = {
        "HOSP_NE_002",
        "HOSP_NE_005",
        "HOSP_NE_009",
        "HOSP_NE_013",
        "HOSP_NE_018",
        "HOSP_NE_021",
    }
    pipeline_ids = {
        "HOSP_NE_003",
        "HOSP_NE_007",
        "HOSP_NE_011",
        "HOSP_NE_014",
        "HOSP_NE_016",
        "HOSP_NE_019",
        "HOSP_NE_022",
        "HOSP_NE_025",
    }

    ne_states = ["NY", "MA", "PA", "CT", "NJ", "NH", "VT", "ME"]
    mw_states = ["IL", "OH", "MI", "MN", "WI", "IN", "MO", "IA"]
    so_states = ["GA", "NC", "VA", "FL", "TX", "TN", "MD", "LA"]
    we_states = ["WA", "CA", "CO", "OR", "AZ", "UT", "NV"]

    specs: list[HospitalSpec] = []

    # 25 Northeast hospitals
    for idx in range(1, 26):
        hid = f"HOSP_NE_{idx:03d}"
        state = ne_states[(idx - 1) % len(ne_states)]
        if hid in outbreak_ids:
            specs.append(
                HospitalSpec(
                    hid,
                    f"Northeast Regional Facility {idx:02d}",
                    "Northeast",
                    "NY",
                    "Suburban",
                    280 + (idx * 7) % 80,
                    "outbreak",
                    "outbreak",
                )
            )
        elif hid in sampling_ids:
            specs.append(
                HospitalSpec(
                    hid,
                    f"Northeast Metro Center {idx:02d}",
                    "Northeast",
                    state,
                    "Urban",
                    850 + (idx * 19) % 300,
                    "urban_early",
                    "sampling_artifact",
                )
            )
        elif hid in pipeline_ids:
            is_rural = idx % 2 == 1
            specs.append(
                HospitalSpec(
                    hid,
                    f"Northeast Valley Hospital {idx:02d}",
                    "Northeast",
                    state,
                    "Rural" if is_rural else "Suburban",
                    80 + (idx * 5) % 40 if is_rural else 350 + (idx * 11) % 120,
                    "rural_sharp" if is_rural else "suburban_broad",
                    "pipeline_defect",
                )
            )
        else:
            is_rural = idx % 2 == 0
            specs.append(
                HospitalSpec(
                    hid,
                    f"Northeast Community Hospital {idx:02d}",
                    "Northeast",
                    state,
                    "Rural" if is_rural else "Suburban",
                    75 + (idx * 7) % 45 if is_rural else 360 + (idx * 13) % 140,
                    "rural_sharp" if is_rural else "suburban_broad",
                    "baseline",
                )
            )

    # Helper for remaining regions
    region_configs = [
        ("MW", "Midwest", 25, mw_states),
        ("SO", "South", 25, so_states),
        ("WE", "West", 15, we_states),
    ]
    for code, region_name, count, states in region_configs:
        for idx in range(1, count + 1):
            hid = f"HOSP_{code}_{idx:03d}"
            state = states[(idx - 1) % len(states)]
            mod = idx % 3
            if mod == 1:
                urban_rural = "Urban"
                archetype = "urban_early"
                beds = 820 + (idx * 23) % 340
            elif mod == 2:
                urban_rural = "Suburban"
                archetype = "suburban_broad"
                beds = 320 + (idx * 17) % 180
            else:
                urban_rural = "Rural"
                archetype = "rural_sharp"
                beds = 60 + (idx * 9) % 60
            specs.append(
                HospitalSpec(
                    hid,
                    f"{region_name} Medical Center {idx:02d}",
                    region_name,
                    state,
                    urban_rural,
                    beds,
                    archetype,
                    "baseline",
                )
            )

    return specs


def _season_week_offset(d: date) -> float:
    """Return fractional weeks (0..52) elapsed since the start of the flu season (around Oct 1)."""
    # Anchor each season near Oct 1
    if d < date(2024, 9, 29):
        season_start = date(2023, 10, 1)
    elif d < date(2025, 9, 28):
        season_start = date(2024, 9, 29)
    elif d < date(2026, 10, 4):
        season_start = date(2025, 9, 28)
    else:
        season_start = date(2026, 10, 4)
    return (d - season_start).days / 7.0


def _historical_daily_counts(
    spec: HospitalSpec, d: date, rng: random.Random
) -> tuple[int, int]:
    """Compute (total_flu_tests, positive_flu_tests) for historical dates prior to Baseline week."""
    # Exercise Spark 4 ANSI division-by-zero guard on off-season dates for Rural hospitals
    if d in ZERO_TEST_DATES and spec.urban_rural == "Rural":
        return 0, 0

    w = _season_week_offset(d)

    # Archetype parameters designed so K-means (k=4) on seasonal features
    # (peak_arrival_week, peak_volume, curve_width, trend) separates cleanly:
    #   1. urban_early: peaks at week offset ~13.0, high peak volume, medium width (sigma=3.8)
    #   2. suburban_broad: peaks at week offset ~18.5, medium volume, wide curve (sigma=6.8)
    #   3. rural_sharp: peaks at week offset ~22.5, low volume, narrow curve (sigma=2.1)
    #   4. outbreak: peaks at week offset ~9.0, medium-high volume, narrow-medium width (sigma=3.0)
    if spec.archetype == "urban_early":
        peak_week = 13.0
        sigma = 3.8
        base_tests = 190
        peak_extra_tests = 90
        off_positivity = 0.038
        peak_positivity = 0.145
    elif spec.archetype == "suburban_broad":
        peak_week = 18.5
        sigma = 6.8
        base_tests = 85
        peak_extra_tests = 45
        off_positivity = 0.055
        peak_positivity = 0.165
    elif spec.archetype == "rural_sharp":
        peak_week = 22.5
        sigma = 2.1
        base_tests = 22
        peak_extra_tests = 18
        off_positivity = 0.085
        peak_positivity = 0.220
    else:  # 'outbreak'
        peak_week = 9.0
        sigma = 3.0
        base_tests = 48
        peak_extra_tests = 32
        off_positivity = 0.050
        peak_positivity = 0.195

    # Slight season-over-season growth factor for realistic multi-season history
    if d < date(2024, 9, 29):
        season_scale = 0.94
    elif d < date(2025, 9, 28):
        season_scale = 1.00
    elif d < date(2026, 10, 4):
        season_scale = 1.05
    else:
        season_scale = 1.08

    gaussian = math.exp(-0.5 * ((w - peak_week) / sigma) ** 2)
    jitter = 1.0 + rng.uniform(-0.04, 0.04)

    total_tests = max(
        5, round((base_tests + peak_extra_tests * gaussian) * season_scale * jitter)
    )
    positivity = off_positivity + (peak_positivity - off_positivity) * gaussian
    pos_tests = max(0, min(total_tests, round(total_tests * positivity)))
    return total_tests, pos_tests


def _distribute_weekly_total(weekly_total: int, weights: list[float]) -> list[int]:
    """Distribute an exact integer weekly total across 7 days according to weights."""
    weight_sum = sum(weights)
    raw = [weekly_total * (w / weight_sum) for w in weights]
    floored = [math.floor(x) for x in raw]
    remainder = weekly_total - sum(floored)
    # Sort indices by largest fractional part
    frac_indices = sorted(
        range(len(raw)), key=lambda i: (raw[i] - floored[i], -i), reverse=True
    )
    for idx in frac_indices[:remainder]:
        floored[idx] += 1
    return floored


def _distribute_across_hospitals(total: int, count: int) -> list[int]:
    """Split an exact integer total evenly across `count` hospitals."""
    base = total // count
    rem = total % count
    return [base + (1 if i < rem else 0) for i in range(count)]


def _build_controlled_window_counts(
    specs: list[HospitalSpec], scale: str, seed: int = 42
) -> dict[tuple[str, date], tuple[int, int]]:
    """Build exact daily (total_flu_tests, positive_flu_tests) for early 2026-2027
    season ramp (W40-W41), Baseline Week (W42), Spike Week (W43), and the 6-week
    Reveal (W44-W49).

    Guarantees:
      1. Exact +35.0% Northeast Spike in W43 vs W42 raw positive counts:
         - Pipeline Defect: +15.0 percentage points (from 5 backfilled days 2026-10-26..30)
         - Sampling Artifact: +8.0 percentage points (~48% test volume expansion, flat Positivity)
         - Outbreak: +7.0 percentage points (Positivity jumps ~6.0% -> ~16.3% at stable volume)
         - Seasonal Ramp: +5.0 percentage points (~5% WoW across all hospitals)
      2. Simpson's Paradox in Northeast non-Outbreak hospitals:
         - Every individual non-Outbreak hospital's Positivity increases slightly from W42 to W43,
           yet combined non-Outbreak Northeast Positivity decreases because high-volume Urban
           hospitals (low Positivity ~4.3%) expand testing volume by ~48%.
      3. Smooth early-season ramp (W40 -> W41 -> W42) with zero step-function discontinuity
         and balanced weekday/weekend distribution in W43 Pipeline Defect hospitals.
      4. Reveal trajectory (W44-W49):
         - Follows the cleaned trajectory so forecasts trained on uncleaned W43 data (+35% jump)
           visibly overshoot the Reveal.
    """
    mult = 1 if scale == "mini" else 2
    ne_specs = [s for s in specs if s.region == "Northeast"]
    other_specs = [s for s in specs if s.region != "Northeast"]

    sampling_specs = [s for s in ne_specs if s.role == "sampling_artifact"]
    outbreak_specs = [s for s in ne_specs if s.role == "outbreak"]
    pipeline_specs = [s for s in ne_specs if s.role == "pipeline_defect"]
    baseline_ne_specs = [s for s in ne_specs if s.role == "baseline"]

    # Exact weekly Northeast positive test totals in W42 (sums to 1000 * mult)
    w42_pos_sampling = 180 * mult
    w42_pos_outbreak = 42 * mult
    w42_pos_pipeline = 200 * mult
    w42_pos_baseline_ne = 578 * mult

    # Exact weekly Northeast total_flu_tests in W42
    w42_tot_sampling = 4200 * mult  # Positivity = 4.286%
    w42_tot_outbreak = 700 * mult  # Positivity = 6.000%
    w42_tot_pipeline = 1680 * mult  # Positivity = 11.905%
    w42_tot_baseline_ne = 4720 * mult  # Positivity = 12.246%

    # Exact weekly Northeast positive test totals in W43 (clean sums to 1200 * mult;
    # plus 150 * mult from 5-day backfill duplicate rows = 1350 * mult = +35.0%)
    # Seasonal Ramp (+50 * mult): +9 sampling, +2 outbreak, +10 pipeline, +29 baseline_ne
    # Sampling Artifact (+80 * mult): on sampling_specs
    # Outbreak (+70 * mult): on outbreak_specs
    w43_pos_sampling = (180 + 9 + 80) * mult  # 269 * mult
    w43_pos_outbreak = (42 + 2 + 70) * mult  # 114 * mult
    w43_pos_pipeline = (
        200 + 10
    ) * mult  # 210 * mult (Mon-Fri = 150 * mult = 5/7 of 210)
    w43_pos_baseline_ne = (578 + 29) * mult  # 607 * mult

    # Exact weekly Northeast total_flu_tests in W43:
    # Sampling Artifact hospitals expand volume by +48.0% (4200 -> 6216 * mult)
    # so Positivity goes from 4.286% -> 4.328% (+0.042% rise at each hospital!),
    # while non-Urban non-outbreak hospitals expand volume by ~4.0% so their Positivity
    # ALSO rises (from 12.156% -> 12.275%), yet combined non-outbreak Positivity DROPS
    # from 9.038% -> 8.437% (Simpson's Paradox!).
    w43_tot_sampling = 6216 * mult  # Positivity = 269/6216 = 4.328% (> 4.286%)
    w43_tot_outbreak = 700 * mult  # Positivity = 114/700 = 16.286% (jump from 6.0%!)
    w43_tot_pipeline = 1720 * mult  # Positivity = 210/1720 = 12.209% (> 11.905%)
    w43_tot_baseline_ne = 4936 * mult  # Positivity = 607/4936 = 12.297% (> 12.246%)

    base_daily_weights = [0.95, 1.05, 1.02, 1.00, 1.03, 0.98, 0.97]
    overrides: dict[tuple[str, date], tuple[int, int]] = {}

    def _assign_group_week(
        group: list[HospitalSpec],
        week_start: date,
        tot_week: int,
        pos_week: int,
        mon_fri_pos_target: int | None = None,
    ) -> None:
        tot_per_hosp = _distribute_across_hospitals(tot_week, len(group))
        pos_per_hosp = _distribute_across_hospitals(pos_week, len(group))
        mon_fri_per_hosp = (
            _distribute_across_hospitals(mon_fri_pos_target, len(group))
            if mon_fri_pos_target is not None
            else None
        )

        for idx, spec in enumerate(group):
            h_tot = tot_per_hosp[idx]
            h_pos = pos_per_hosp[idx]
            hosp_hash = sum((i + 1) * ord(ch) for i, ch in enumerate(spec.hospital_id))
            wk_rng = random.Random(
                (seed * 1_000_003)
                ^ (week_start.toordinal() * 9_973)
                ^ (hosp_hash * 65_537)
                ^ (idx * 313)
            )
            day_weights = [
                w * (1.0 + wk_rng.uniform(-0.05, 0.05)) for w in base_daily_weights
            ]
            day_tots = _distribute_weekly_total(h_tot, day_weights)
            if mon_fri_per_hosp is not None:
                mf_pos = mon_fri_per_hosp[idx]
                weekend_pos = h_pos - mf_pos
                sun_pos = weekend_pos // 2
                sat_pos = weekend_pos - sun_pos
                mf_weights = [1.0 + wk_rng.uniform(-0.05, 0.05) for _ in range(5)]
                mf_days = _distribute_weekly_total(mf_pos, mf_weights)
                day_poss = [sun_pos, *mf_days, sat_pos]
            else:
                day_poss = _distribute_weekly_total(h_pos, day_weights)

            for d_offset in range(7):
                cur_date = week_start + timedelta(days=d_offset)
                overrides[(spec.hospital_id, cur_date)] = (
                    day_tots[d_offset],
                    day_poss[d_offset],
                )

    # Assign smooth early-season ramp weeks W40 (2026-10-04..10) and W41 (2026-10-11..17)
    # so the 2026-2027 season ramps smoothly at ~5%/wk into W42 without a step jump.
    for pre_idx, pre_factor in enumerate((1.0 / (1.05**2), 1.0 / 1.05)):
        pre_week_start = BASELINE_WEEK_START - timedelta(days=(2 - pre_idx) * 7)
        pre_vol_factor = 1.0 / (1.04 ** (2 - pre_idx))
        _assign_group_week(
            sampling_specs,
            pre_week_start,
            round(w42_tot_sampling * pre_vol_factor),
            round(w42_pos_sampling * pre_factor),
        )
        _assign_group_week(
            outbreak_specs,
            pre_week_start,
            round(w42_tot_outbreak * pre_vol_factor),
            round(w42_pos_outbreak * pre_factor),
        )
        _assign_group_week(
            pipeline_specs,
            pre_week_start,
            round(w42_tot_pipeline * pre_vol_factor),
            round(w42_pos_pipeline * pre_factor),
        )
        _assign_group_week(
            baseline_ne_specs,
            pre_week_start,
            round(w42_tot_baseline_ne * pre_vol_factor),
            round(w42_pos_baseline_ne * pre_factor),
        )

    # Assign W42 (2026-10-18..2026-10-24)
    _assign_group_week(
        sampling_specs, BASELINE_WEEK_START, w42_tot_sampling, w42_pos_sampling
    )
    _assign_group_week(
        outbreak_specs, BASELINE_WEEK_START, w42_tot_outbreak, w42_pos_outbreak
    )
    _assign_group_week(
        pipeline_specs, BASELINE_WEEK_START, w42_tot_pipeline, w42_pos_pipeline
    )
    _assign_group_week(
        baseline_ne_specs,
        BASELINE_WEEK_START,
        w42_tot_baseline_ne,
        w42_pos_baseline_ne,
    )

    # Assign W43 (2026-10-25..2026-10-31)
    # Note: For pipeline_specs, Mon-Fri (2026-10-26..2026-10-30) positive tests sum to
    # exactly 150 * mult (5/7 of 210 * mult) so the 5-day duplicate backfill adds
    # +150 * mult (+15.0 pts) with balanced weekday/weekend rates.
    _assign_group_week(
        sampling_specs, SPIKE_WEEK_START, w43_tot_sampling, w43_pos_sampling
    )
    _assign_group_week(
        outbreak_specs, SPIKE_WEEK_START, w43_tot_outbreak, w43_pos_outbreak
    )
    _assign_group_week(
        pipeline_specs,
        SPIKE_WEEK_START,
        w43_tot_pipeline,
        w43_pos_pipeline,
        mon_fri_pos_target=150 * mult,
    )
    _assign_group_week(
        baseline_ne_specs,
        SPIKE_WEEK_START,
        w43_tot_baseline_ne,
        w43_pos_baseline_ne,
    )

    # Assign non-Northeast W40, W41, W42, and W43 with clean +5.0% Seasonal Ramp
    for spec in other_specs:
        if spec.urban_rural == "Urban":
            w42_t, w42_p = 1260, 60
        elif spec.urban_rural == "Suburban":
            w42_t, w42_p = 630, 40
        else:
            w42_t, w42_p = 175, 20
        for pre_idx, pre_factor in enumerate((1.0 / (1.05**2), 1.0 / 1.05)):
            pre_week_start = BASELINE_WEEK_START - timedelta(days=(2 - pre_idx) * 7)
            pre_vol_factor = 1.0 / (1.04 ** (2 - pre_idx))
            _assign_group_week(
                [spec],
                pre_week_start,
                round(w42_t * pre_vol_factor),
                round(w42_p * pre_factor),
            )
        w43_t = round(w42_t * 1.04)
        w43_p = round(w42_p * 1.05)
        _assign_group_week([spec], BASELINE_WEEK_START, w42_t, w42_p)
        _assign_group_week([spec], SPIKE_WEEK_START, w43_t, w43_p)

    # Assign the 6-week Reveal (W44..W49: 2026-11-01..2026-12-12)
    # In the Reveal:
    # - No duplicate backfills occur.
    # - Sampling Artifact temporary screening expansion reverts to normal Seasonal Ramp (+5%/wk from W42 base).
    # - Outbreak hospitals sustain their localized outbreak trajectory (+4%/wk from W43).
    # - Pipeline Defect & Baseline hospitals continue normal +5%/wk Seasonal Ramp from clean W43.
    # Consequently, clean Northeast W44..W49 grows smoothly around ~1,180 -> ~1,440 (* mult),
    # whereas an uncleaned forecast extrapolating the +35% jump (1,000 -> 1,350) projects
    # ~1,550 -> ~2,200 (* mult), visibly overshooting the Reveal!
    for week_idx in range(6):
        rev_week_start = REVEAL_START_DATE + timedelta(days=week_idx * 7)
        ramp_factor = 1.05 ** (week_idx + 1)
        outbreak_factor = 1.04 ** (week_idx + 1)

        # Sampling hospitals return to normal Seasonal Ramp from their W42 + 5% base (189 * mult)
        rev_pos_sampling = round(189 * mult * ramp_factor)
        rev_tot_sampling = round(4368 * mult * (1.03 ** (week_idx + 1)))

        # Outbreak hospitals continue elevated curve from W43 (114 * mult)
        rev_pos_outbreak = round(w43_pos_outbreak * outbreak_factor)
        rev_tot_outbreak = round(w43_tot_outbreak * (1.02 ** (week_idx + 1)))

        # Pipeline hospitals continue normal Seasonal Ramp from clean W43 (210 * mult)
        rev_pos_pipeline = round(w43_pos_pipeline * ramp_factor)
        rev_tot_pipeline = round(w43_tot_pipeline * (1.03 ** (week_idx + 1)))

        # Baseline NE hospitals continue normal Seasonal Ramp from W43 (607 * mult)
        rev_pos_base_ne = round(w43_pos_baseline_ne * ramp_factor)
        rev_tot_base_ne = round(w43_tot_baseline_ne * (1.03 ** (week_idx + 1)))

        _assign_group_week(
            sampling_specs, rev_week_start, rev_tot_sampling, rev_pos_sampling
        )
        _assign_group_week(
            outbreak_specs, rev_week_start, rev_tot_outbreak, rev_pos_outbreak
        )
        _assign_group_week(
            pipeline_specs, rev_week_start, rev_tot_pipeline, rev_pos_pipeline
        )
        _assign_group_week(
            baseline_ne_specs, rev_week_start, rev_tot_base_ne, rev_pos_base_ne
        )

        for spec in other_specs:
            if spec.urban_rural == "Urban":
                w43_t, w43_p = round(1260 * 1.04), round(60 * 1.05)
            elif spec.urban_rural == "Suburban":
                w43_t, w43_p = round(630 * 1.04), round(40 * 1.05)
            else:
                w43_t, w43_p = round(175 * 1.04), round(20 * 1.05)
            w_t = round(w43_t * (1.03 ** (week_idx + 1)))
            w_p = round(w43_p * ramp_factor)
            _assign_group_week([spec], rev_week_start, w_t, w_p)

    return overrides


def generate_dataset(
    seed: int = 42,
    scale: str = "mini",
    output_dir: Path | None = None,
    withheld_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate the synthetic dataset and withheld Answer Key + Reveal files.

    Returns a dictionary of summary metadata for verification and tests.
    """
    specs = _build_hospital_specs(scale)
    start_date = MINI_START_DATE if scale == "mini" else FULL_START_DATE
    total_visible_days = (CUTOFF_DATE - start_date).days + 1
    total_reveal_days = (REVEAL_END_DATE - REVEAL_START_DATE).days + 1

    overrides = _build_controlled_window_counts(specs, scale, seed=seed)

    # 1. Build hospital_reference rows
    hospital_rows: list[dict[str, Any]] = [
        {
            "hospital_id": s.hospital_id,
            "hospital_name": s.hospital_name,
            "region": s.region,
            "state": s.state,
            "urban_rural": s.urban_rural,
            "bed_count": s.bed_count,
        }
        for s in specs
    ]

    # 2. Build hospital_flu_feeds rows (visible up to Cutoff) and duplicate backfill rows
    feed_rows: list[dict[str, Any]] = []
    duplicate_rows: list[dict[str, Any]] = []

    for d_idx in range(total_visible_days):
        cur_date = start_date + timedelta(days=d_idx)
        date_str = cur_date.isoformat()
        compact_date = cur_date.strftime("%Y%m%d")
        scheduled_batch_id = f"BATCH-{compact_date}-01"
        scheduled_ingested_at = f"{date_str} 04:10:00 UTC"

        for s_idx, spec in enumerate(specs):
            # Per-(hospital, date, seed) deterministic RNG so order never drifts
            row_rng = random.Random(
                (seed * 1_000_003) ^ (d_idx * 9_973) ^ (s_idx * 313)
            )
            if (spec.hospital_id, cur_date) in overrides:
                tot_tests, pos_tests = overrides[(spec.hospital_id, cur_date)]
            else:
                tot_tests, pos_tests = _historical_daily_counts(spec, cur_date, row_rng)

            feed_rows.append(
                _make_feed_row(
                    spec.hospital_id,
                    date_str,
                    tot_tests,
                    pos_tests,
                    scheduled_batch_id,
                    scheduled_ingested_at,
                )
            )

            # Plant duplicate backfill rows for Pipeline Defect hospitals on 2026-10-26..30
            if (
                spec.role == "pipeline_defect"
                and BACKFILL_START_DATE <= cur_date <= BACKFILL_END_DATE
            ):
                duplicate_rows.append(
                    _make_feed_row(
                        spec.hospital_id,
                        date_str,
                        tot_tests,
                        pos_tests,
                        BACKFILL_BATCH_ID,
                        BACKFILL_INGESTED_AT,
                    )
                )

    feed_rows.extend(duplicate_rows)

    # 3. Build ops.pipeline_run_log rows
    run_log_rows: list[dict[str, Any]] = []
    num_hospitals = len(specs)
    for d_idx in range(total_visible_days):
        cur_date = start_date + timedelta(days=d_idx)
        date_str = cur_date.isoformat()
        compact_date = cur_date.strftime("%Y%m%d")
        run_log_rows.append(
            {
                "run_id": f"RUN-{compact_date}-01",
                "pipeline_name": "hospital_flu_daily_ingest",
                "run_type": "scheduled",
                "date_range_start": date_str,
                "date_range_end": date_str,
                "started_at": f"{date_str} 04:05:00 UTC",
                "finished_at": f"{date_str} 04:12:30 UTC",
                "status": "SUCCESS",
                "rows_written": num_hospitals,
            }
        )

    # Add the errant backfill run on the morning of the Cutoff (2026-10-31)
    run_log_rows.append(
        {
            "run_id": BACKFILL_RUN_ID,
            "pipeline_name": "hospital_flu_backfill",
            "run_type": "backfill",
            "date_range_start": BACKFILL_START_DATE.isoformat(),
            "date_range_end": BACKFILL_END_DATE.isoformat(),
            "started_at": BACKFILL_STARTED_AT,
            "finished_at": BACKFILL_FINISHED_AT,
            "status": "SUCCESS",
            "rows_written": len(duplicate_rows),
        }
    )

    # 4. Build Reveal rows (2026-11-01 through 2026-12-12, 42 days, zero duplicates)
    reveal_rows: list[dict[str, Any]] = []
    for d_idx in range(total_reveal_days):
        cur_date = REVEAL_START_DATE + timedelta(days=d_idx)
        date_str = cur_date.isoformat()
        compact_date = cur_date.strftime("%Y%m%d")
        batch_id = f"BATCH-{compact_date}-01"
        ingested_at = f"{date_str} 04:10:00 UTC"

        for spec in specs:
            tot_tests, pos_tests = overrides[(spec.hospital_id, cur_date)]
            reveal_rows.append(
                _make_feed_row(
                    spec.hospital_id,
                    date_str,
                    tot_tests,
                    pos_tests,
                    batch_id,
                    ingested_at,
                )
            )

    # 5. Build Answer Key JSON
    answer_key = {
        "contract_version": CONTRACT_VERSION,
        "seed": seed,
        "scale": scale,
        "evaluation_window": {
            "target_region": "Northeast",
            "baseline_week_start": BASELINE_WEEK_START.isoformat(),
            "baseline_week_end": BASELINE_WEEK_END.isoformat(),
            "spike_week_start": SPIKE_WEEK_START.isoformat(),
            "spike_week_end": CUTOFF_DATE.isoformat(),
            "headline_spike_pct": 35.0,
        },
        "attribution": [
            {
                "cause": "pipeline_defect",
                "target_points": 15.0,
                "affected_hospitals": [
                    s.hospital_id for s in specs if s.role == "pipeline_defect"
                ],
                "date_range": {
                    "start": BACKFILL_START_DATE.isoformat(),
                    "end": BACKFILL_END_DATE.isoformat(),
                },
                "manifestation": "Re-sent backfill duplicate feeds with identical counts and later ingested_at",
            },
            {
                "cause": "sampling_artifact",
                "target_points": 8.0,
                "affected_hospitals": [
                    s.hospital_id for s in specs if s.role == "sampling_artifact"
                ],
                "date_range": {
                    "start": SPIKE_WEEK_START.isoformat(),
                    "end": CUTOFF_DATE.isoformat(),
                },
                "manifestation": "Testing volume increased ~48% with Positivity remaining flat",
            },
            {
                "cause": "outbreak",
                "target_points": 7.0,
                "affected_hospitals": [
                    s.hospital_id for s in specs if s.role == "outbreak"
                ],
                "date_range": {
                    "start": SPIKE_WEEK_START.isoformat(),
                    "end": CUTOFF_DATE.isoformat(),
                },
                "manifestation": "Positivity jumped from 6% to 16.3% with stable testing volume",
            },
            {
                "cause": "seasonal_ramp",
                "target_points": 5.0,
                "affected_hospitals": ["*"],
                "date_range": {
                    "start": SPIKE_WEEK_START.isoformat(),
                    "end": CUTOFF_DATE.isoformat(),
                },
                "manifestation": "Normal early-season rise across all regions",
            },
        ],
    }

    # Write files if directories are provided
    if output_dir is not None:
        raw_dir = output_dir / "raw"
        feeds_dir = raw_dir / "hospital_flu_feeds"
        ops_dir = output_dir / "ops"
        feeds_dir.mkdir(parents=True, exist_ok=True)
        ops_dir.mkdir(parents=True, exist_ok=True)

        _write_csv(
            raw_dir / "hospital_reference.csv",
            [
                "hospital_id",
                "hospital_name",
                "region",
                "state",
                "urban_rural",
                "bed_count",
            ],
            hospital_rows,
        )
        _write_csv(
            feeds_dir / "feeds.csv",
            FEED_COLUMNS,
            feed_rows,
        )
        _write_csv(
            ops_dir / "pipeline_run_log.csv",
            [
                "run_id",
                "pipeline_name",
                "run_type",
                "date_range_start",
                "date_range_end",
                "started_at",
                "finished_at",
                "status",
                "rows_written",
            ],
            run_log_rows,
        )

    if withheld_dir is not None:
        reveal_dir = withheld_dir / "reveal" / "hospital_flu_feeds_reveal"
        reveal_dir.mkdir(parents=True, exist_ok=True)

        answer_key_path = withheld_dir / "answer_key.json"
        answer_key_path.write_text(json.dumps(answer_key, indent=2) + "\n")

        _write_csv(
            reveal_dir / "reveal.csv",
            FEED_COLUMNS,
            reveal_rows,
        )

    return {
        "seed": seed,
        "scale": scale,
        "hospitals": len(hospital_rows),
        "feed_rows": len(feed_rows),
        "duplicate_rows": len(duplicate_rows),
        "run_log_rows": len(run_log_rows),
        "reveal_rows": len(reveal_rows),
        "answer_key": answer_key,
    }


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate deterministic synthetic Hospital Feeds, pipeline run log, Answer Key, and Reveal data."
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Integer random seed for deterministic output (default: 42)",
    )
    parser.add_argument(
        "--scale",
        choices=["mini", "full"],
        default="mini",
        help="Dataset scale: 'mini' (20 hospitals, 2+ seasons) or 'full' (90 hospitals, 3+ seasons)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Target directory for raw/ and ops/ tables",
    )
    parser.add_argument(
        "--withheld-dir",
        type=Path,
        required=True,
        help="Target directory for answer_key.json and reveal/ data",
    )

    args = parser.parse_args(argv)
    summary = generate_dataset(
        seed=args.seed,
        scale=args.scale,
        output_dir=args.output_dir,
        withheld_dir=args.withheld_dir,
    )
    print(
        f"Generated {summary['scale']} dataset (seed={summary['seed']}): "
        f"{summary['hospitals']} hospitals, {summary['feed_rows']} feed rows "
        f"({summary['duplicate_rows']} duplicate backfill rows), "
        f"{summary['run_log_rows']} run log rows, {summary['reveal_rows']} Reveal rows."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
