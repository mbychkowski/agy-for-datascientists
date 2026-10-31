"""Workstream 2 seasonal feature engineering and K-means Cohort assignment engine.

Computes the four per-hospital seasonal features (`peak_arrival_week`,
`peak_volume`, `curve_width`, `seasonal_trend`) from `staging.hospital_flu_clean`
and assigns hospitals to four seasonal Cohorts via standardized K-means
(`KMEANS++`). Verifies that the three Northeast Outbreak hospitals
(`HOSP_NE_001`, `HOSP_NE_004`, `HOSP_NE_006`) separate cleanly into their own
distinct Cohort and stand out as clear seasonal trend outliers.
"""

from __future__ import annotations

import csv
import math
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from pipelines.pipeline_clean import deduplicate_and_compute_positivity_rows

SEASONAL_FEATURE_COLUMNS: tuple[str, ...] = (
    "peak_arrival_week",
    "peak_volume",
    "curve_width",
    "seasonal_trend",
)

OUTBREAK_HOSPITAL_IDS: tuple[str, ...] = (
    "HOSP_NE_001",
    "HOSP_NE_004",
    "HOSP_NE_006",
)

BASELINE_WEEK_START = date(2026, 10, 18)
BASELINE_WEEK_END = date(2026, 10, 24)
SPIKE_WEEK_START = date(2026, 10, 25)
CUTOFF_DATE = date(2026, 10, 31)
CURRENT_SEASON_START = date(2026, 10, 4)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read a UTF-8 CSV file into a list of string dictionaries."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _mmwr_week_start(d: date) -> date:
    """Return the Sunday MMWR week start date for `d`."""
    days_since_sunday = (d.weekday() + 1) % 7
    return d - timedelta(days=days_since_sunday)


def _historical_season_start(d: date) -> date | None:
    """Return the season start date for historical seasons prior to `2026-10-04`."""
    if d >= CURRENT_SEASON_START:
        return None
    if d < date(2024, 9, 29):
        return date(2023, 10, 1)
    if d < date(2025, 9, 28):
        return date(2024, 9, 29)
    return date(2025, 9, 28)


def load_clean_staging_rows(dataset_dir: Path | str) -> list[dict[str, object]]:
    """Load raw Hospital Feeds and reference metadata from `dataset_dir` and build `staging.hospital_flu_clean` rows."""
    root = Path(dataset_dir)
    hospitals = _read_csv_rows(root / "raw" / "hospital_reference.csv")
    feeds = _read_csv_rows(root / "raw" / "hospital_flu_feeds" / "feeds.csv")
    return deduplicate_and_compute_positivity_rows(feeds, hospitals)


def compute_hospital_seasonal_features(
    clean_rows: Sequence[Mapping[str, Any]] | Path | str | None = None,
    *,
    dataset_dir: Path | str | None = None,
) -> list[dict[str, Any]]:
    """Compute the four per-hospital seasonal features from `staging.hospital_flu_clean` rows.

    Features computed per hospital:
      - `peak_arrival_week`: average seasonal week offset from MMWR Week 40 when the
        hospital reaches its seasonal peak positive flu test count across historical seasons.
      - `peak_volume`: average weekly positive flu tests at the seasonal peak across
        historical seasons.
      - `curve_width`: average number of weeks per season where weekly positive flu tests
        are >= 50% of that season's peak (full width at half maximum).
      - `seasonal_trend`: early-season Positivity ratio comparing the Spike week ending on
        the Cutoff (`2026-10-25..2026-10-31`) to the baseline week (`2026-10-18..2026-10-24`).
    """
    if isinstance(clean_rows, (Path, str)):
        resolved_rows: Sequence[Mapping[str, Any]] = load_clean_staging_rows(clean_rows)
    elif clean_rows is None:
        if dataset_dir is None:
            raise ValueError("Either clean_rows or dataset_dir must be provided.")
        resolved_rows = load_clean_staging_rows(dataset_dir)
    else:
        resolved_rows = clean_rows

    hosp_meta: dict[str, dict[str, Any]] = {}
    historical_weekly_positives: dict[tuple[str, date, int], int] = defaultdict(int)
    baseline_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    cutoff_totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for row in resolved_rows:
        hid = str(row["hospital_id"])
        fdate = date.fromisoformat(str(row["feed_date"]))
        if fdate > CUTOFF_DATE:
            continue

        if hid not in hosp_meta:
            hosp_meta[hid] = {
                "hospital_id": hid,
                "hospital_name": str(row["hospital_name"]),
                "region": str(row["region"]),
                "state": str(row.get("state", "")),
                "urban_rural": str(row["urban_rural"]),
                "bed_count": int(row["bed_count"]),
            }

        pos = int(row["positive_flu_tests"])
        tot = int(row["total_flu_tests"])

        season_start = _historical_season_start(fdate)
        if season_start is not None:
            week_start = _mmwr_week_start(fdate)
            week_offset = (week_start - season_start).days // 7
            historical_weekly_positives[(hid, season_start, week_offset)] += pos

        if BASELINE_WEEK_START <= fdate <= BASELINE_WEEK_END:
            baseline_totals[hid][0] += pos
            baseline_totals[hid][1] += tot
        elif SPIKE_WEEK_START <= fdate <= CUTOFF_DATE:
            cutoff_totals[hid][0] += pos
            cutoff_totals[hid][1] += tot

    by_hosp_season: dict[tuple[str, date], dict[int, int]] = defaultdict(dict)
    for (
        hid,
        season_start,
        week_offset,
    ), pos_sum in historical_weekly_positives.items():
        by_hosp_season[(hid, season_start)][week_offset] = pos_sum

    seasons_by_hosp: dict[str, list[date]] = defaultdict(list)
    for hid, season_start in sorted(by_hosp_season.keys()):
        seasons_by_hosp[hid].append(season_start)

    feature_rows: list[dict[str, Any]] = []
    for hid in sorted(hosp_meta.keys()):
        meta = hosp_meta[hid]
        peak_weeks: list[int] = []
        peak_volumes: list[int] = []
        curve_widths: list[int] = []

        for season_start in seasons_by_hosp.get(hid, []):
            week_map = by_hosp_season[(hid, season_start)]
            if not week_map:
                continue
            max_pos = max(week_map.values())
            best_week = min(wk for wk, val in week_map.items() if val == max_pos)
            half_max_weeks = sum(1 for val in week_map.values() if val >= 0.5 * max_pos)
            peak_weeks.append(best_week)
            peak_volumes.append(max_pos)
            curve_widths.append(half_max_weeks)

        peak_arrival_week = (
            round(sum(peak_weeks) / len(peak_weeks), 4) if peak_weeks else 0.0
        )
        peak_volume = (
            round(sum(peak_volumes) / len(peak_volumes), 4) if peak_volumes else 0.0
        )
        curve_width = (
            round(sum(curve_widths) / len(curve_widths), 4) if curve_widths else 0.0
        )

        base_pos, base_tot = baseline_totals[hid]
        cut_pos, cut_tot = cutoff_totals[hid]
        base_positivity = (base_pos / base_tot) if base_tot > 0 else 0.0
        cut_positivity = (cut_pos / cut_tot) if cut_tot > 0 else 0.0
        seasonal_trend = (
            round(cut_positivity / base_positivity, 4) if base_positivity > 0.0 else 1.0
        )

        feature_rows.append(
            {
                **meta,
                "peak_arrival_week": peak_arrival_week,
                "peak_volume": peak_volume,
                "curve_width": curve_width,
                "seasonal_trend": seasonal_trend,
            }
        )

    return feature_rows


def _euclidean_distance(a: Sequence[float], b: Sequence[float]) -> float:
    """Compute Euclidean distance between two equal-length coordinate vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b, strict=True)))


def _kmeans_plus_plus_init(
    points: Sequence[tuple[float, ...]],
    k: int,
    rng: random.Random,
) -> list[tuple[float, ...]]:
    """Select `k` initial centroids using deterministic K-means++ D^2 weighting."""
    n = len(points)
    first_idx = rng.randrange(n)
    centroids: list[tuple[float, ...]] = [points[first_idx]]

    while len(centroids) < k:
        sq_distances = [
            min(_euclidean_distance(pt, c) ** 2 for c in centroids) for pt in points
        ]
        total_sq = sum(sq_distances)
        if total_sq <= 0.0:
            for pt in points:
                if pt not in centroids:
                    centroids.append(pt)
                    if len(centroids) == k:
                        break
            while len(centroids) < k:
                centroids.append(points[len(centroids) % n])
            break

        threshold = rng.uniform(0.0, total_sq)
        cumulative = 0.0
        chosen = points[-1]
        for pt, sq_d in zip(points, sq_distances, strict=True):
            cumulative += sq_d
            if cumulative >= threshold:
                chosen = pt
                break
        centroids.append(chosen)

    return centroids


def _run_single_kmeans(
    points: Sequence[tuple[float, ...]],
    k: int,
    rng: random.Random,
    max_iterations: int = 100,
) -> tuple[list[tuple[float, ...]], list[int], float]:
    """Run one deterministic K-means++ trial and return `(centroids, assignments, inertia)`."""
    centroids = _kmeans_plus_plus_init(points, k, rng)
    assignments = [0] * len(points)
    dim = len(points[0])

    for _ in range(max_iterations):
        new_assignments: list[int] = []
        for pt in points:
            best_c = min(
                range(k),
                key=lambda c_idx: (_euclidean_distance(pt, centroids[c_idx]), c_idx),
            )
            new_assignments.append(best_c)

        new_centroids: list[tuple[float, ...]] = []
        for c_idx in range(k):
            members = [
                pt
                for pt, assigned in zip(points, new_assignments, strict=True)
                if assigned == c_idx
            ]
            if members:
                mean_vec = tuple(
                    sum(m[d] for m in members) / len(members) for d in range(dim)
                )
                new_centroids.append(mean_vec)
            else:
                # Re-seed an empty centroid to the point farthest from its current centroid
                farthest_idx = max(
                    range(len(points)),
                    key=lambda idx: _euclidean_distance(
                        points[idx], centroids[new_assignments[idx]]
                    ),
                )
                new_centroids.append(points[farthest_idx])

        if new_assignments == assignments and all(
            _euclidean_distance(a, b) < 1e-9
            for a, b in zip(centroids, new_centroids, strict=True)
        ):
            centroids = new_centroids
            break

        assignments = new_assignments
        centroids = new_centroids

    inertia = sum(
        _euclidean_distance(pt, centroids[c_idx]) ** 2
        for pt, c_idx in zip(points, assignments, strict=True)
    )
    return centroids, assignments, inertia


def assign_kmeans_cohorts(
    feature_rows: Sequence[Mapping[str, Any]],
    k: int = 4,
    seed: int = 42,
    max_iterations: int = 100,
) -> list[dict[str, Any]]:
    """Assign every hospital to one of `k` seasonal Cohorts using standardized K-means++.

    Standardizes the four seasonal features (`peak_arrival_week`, `peak_volume`,
    `curve_width`, `seasonal_trend`) to zero mean and unit variance, mirroring
    BigQuery ML `OPTIONS(model_type='KMEANS', num_clusters=4, standardize_features=TRUE,
    kmeans_init_method='KMEANS++')`.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    ordered_rows = sorted(feature_rows, key=lambda r: str(r["hospital_id"]))
    if len(ordered_rows) < k:
        raise ValueError(
            f"Cannot assign {len(ordered_rows)} hospitals into k={k} Cohorts."
        )

    raw_vectors: list[tuple[float, ...]] = [
        tuple(float(row[col]) for col in SEASONAL_FEATURE_COLUMNS)
        for row in ordered_rows
    ]
    n = len(raw_vectors)
    dim = len(SEASONAL_FEATURE_COLUMNS)

    means = [sum(vec[d] for vec in raw_vectors) / n for d in range(dim)]
    stds = [
        math.sqrt(sum((vec[d] - means[d]) ** 2 for vec in raw_vectors) / n) or 1.0
        for d in range(dim)
    ]

    standardized_points: list[tuple[float, ...]] = [
        tuple((vec[d] - means[d]) / stds[d] for d in range(dim)) for vec in raw_vectors
    ]

    best_centroids: list[tuple[float, ...]] | None = None
    best_assignments: list[int] | None = None
    best_inertia = float("inf")

    for restart in range(8):
        trial_rng = random.Random((seed * 1_000_003) ^ (restart * 9_973))
        centroids, assignments, inertia = _run_single_kmeans(
            standardized_points,
            k=k,
            rng=trial_rng,
            max_iterations=max_iterations,
        )
        if inertia + 1e-9 < best_inertia:
            best_inertia = inertia
            best_centroids = centroids
            best_assignments = assignments

    assert best_centroids is not None and best_assignments is not None

    # Unstandardize centroids to order Cohort IDs deterministically:
    # Non-outbreak Cohorts first ordered by peak_arrival_week ascending (COHORT_1..COHORT_{k-1}),
    # and the Outbreak Cohort (highest seasonal_trend >= 1.5) assigned COHORT_{k}.
    unstandardized_centroids: list[tuple[float, ...]] = [
        tuple(c[d] * stds[d] + means[d] for d in range(dim)) for c in best_centroids
    ]
    max_trend_idx = max(range(k), key=lambda idx: unstandardized_centroids[idx][3])
    sorted_old_indices = sorted(
        range(k),
        key=lambda idx: (
            1
            if (idx == max_trend_idx and unstandardized_centroids[idx][3] >= 1.5)
            else 0,
            round(unstandardized_centroids[idx][0], 6),
            round(-unstandardized_centroids[idx][1], 6),
        ),
    )
    old_to_new_centroid_id = {
        old_idx: new_rank
        for new_rank, old_idx in enumerate(sorted_old_indices, start=1)
    }
    ordered_std_centroids = {
        new_rank: best_centroids[old_idx]
        for old_idx, new_rank in old_to_new_centroid_id.items()
    }
    outbreak_centroid_id = old_to_new_centroid_id[max_trend_idx]

    origin = tuple(0.0 for _ in range(dim))
    cohort_rows: list[dict[str, Any]] = []

    for row, std_pt, old_c_idx in zip(
        ordered_rows, standardized_points, best_assignments, strict=True
    ):
        cid_num = old_to_new_centroid_id[old_c_idx]
        cohort_id = f"COHORT_{cid_num}"
        own_centroid = ordered_std_centroids[cid_num]
        centroid_dist = round(_euclidean_distance(std_pt, own_centroid), 4)
        other_dists = [
            _euclidean_distance(std_pt, other_c)
            for other_id, other_c in ordered_std_centroids.items()
            if other_id != cid_num
        ]
        nearest_other_dist = round(min(other_dists), 4) if other_dists else 0.0
        global_outlier_dist = round(_euclidean_distance(std_pt, origin), 4)
        trend_val = float(row["seasonal_trend"])
        is_outbreak_outlier = bool(cid_num == outbreak_centroid_id and trend_val >= 1.5)

        cohort_rows.append(
            {
                "hospital_id": str(row["hospital_id"]),
                "hospital_name": str(row["hospital_name"]),
                "region": str(row["region"]),
                "state": str(row.get("state", "")),
                "urban_rural": str(row["urban_rural"]),
                "bed_count": int(row["bed_count"]),
                "centroid_id": cid_num,
                "cohort_id": cohort_id,
                "centroid_distance": centroid_dist,
                "nearest_other_centroid_distance": nearest_other_dist,
                "global_outlier_distance": global_outlier_dist,
                "is_outbreak_outlier": is_outbreak_outlier,
                "peak_arrival_week": float(row["peak_arrival_week"]),
                "peak_volume": float(row["peak_volume"]),
                "curve_width": float(row["curve_width"]),
                "seasonal_trend": trend_val,
            }
        )

    cohort_rows.sort(key=lambda r: (str(r["cohort_id"]), str(r["hospital_id"])))
    return cohort_rows


def summarize_cohort_separation(
    cohort_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Summarize Cohort separation and verify that the Outbreak hospitals form a distinct Cohort."""
    by_cohort: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in cohort_rows:
        by_cohort[str(row["cohort_id"])].append(dict(row))

    cohort_profiles: list[dict[str, Any]] = []
    for cid in sorted(by_cohort.keys()):
        members = sorted(by_cohort[cid], key=lambda r: str(r["hospital_id"]))
        count = len(members)
        cohort_profiles.append(
            {
                "cohort_id": cid,
                "hospital_count": count,
                "hospital_ids": [str(m["hospital_id"]) for m in members],
                "mean_peak_arrival_week": round(
                    sum(float(m["peak_arrival_week"]) for m in members) / count, 4
                ),
                "mean_peak_volume": round(
                    sum(float(m["peak_volume"]) for m in members) / count, 4
                ),
                "mean_curve_width": round(
                    sum(float(m["curve_width"]) for m in members) / count, 4
                ),
                "mean_seasonal_trend": round(
                    sum(float(m["seasonal_trend"]) for m in members) / count, 4
                ),
                "mean_centroid_distance": round(
                    sum(float(m["centroid_distance"]) for m in members) / count, 4
                ),
                "min_other_cohort_centroid_distance": round(
                    min(
                        float(m.get("nearest_other_centroid_distance", 0.0))
                        for m in members
                    ),
                    4,
                ),
            }
        )

    outbreak_profile = max(
        cohort_profiles, key=lambda p: float(p["mean_seasonal_trend"])
    )
    outbreak_cohort_id = str(outbreak_profile["cohort_id"])
    outbreak_hospital_ids = list(outbreak_profile["hospital_ids"])

    non_outbreak_trends = [
        float(r["seasonal_trend"])
        for r in cohort_rows
        if str(r["cohort_id"]) != outbreak_cohort_id
    ]
    ranked_outliers = sorted(
        cohort_rows,
        key=lambda r: (
            -float(r.get("global_outlier_distance", 0.0)),
            -float(r["seasonal_trend"]),
            str(r["hospital_id"]),
        ),
    )
    top_outlier_hospital_ids = sorted(
        str(r["hospital_id"]) for r in ranked_outliers[: len(OUTBREAK_HOSPITAL_IDS)]
    )

    return {
        "total_hospitals": len(cohort_rows),
        "num_cohorts": len(cohort_profiles),
        "cohort_counts": {p["cohort_id"]: p["hospital_count"] for p in cohort_profiles},
        "cohort_profiles": cohort_profiles,
        "outbreak_cohort_id": outbreak_cohort_id,
        "outbreak_hospital_ids": outbreak_hospital_ids,
        "expected_outbreak_hospital_ids": list(OUTBREAK_HOSPITAL_IDS),
        "outbreak_isolated_in_own_cohort": (
            outbreak_hospital_ids == list(OUTBREAK_HOSPITAL_IDS)
        ),
        "outbreak_mean_seasonal_trend": float(outbreak_profile["mean_seasonal_trend"]),
        "non_outbreak_max_seasonal_trend": (
            round(max(non_outbreak_trends), 4) if non_outbreak_trends else 0.0
        ),
        "top_outlier_hospital_ids": top_outlier_hospital_ids,
    }
