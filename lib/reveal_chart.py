"""Post-Cutoff Reveal comparison, overshoot evaluation, and chart rendering.

Compares the six post-Cutoff Reveal weeks (2026-11-01..2026-12-12) against
Northeast weekly positive flu test forecasts trained on deduplicated clean data
(`staging.hospital_flu_clean`) versus uncleaned data (`staging.hospital_flu`).

In accordance with ADR 0001, neither the Answer Key location nor the Reveal
location is ever hardcoded or persisted by this module; callers must supply
withheld locations at runtime. All terminology adheres to GLOSSARY.md.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from lib.ws1_triage import (
    CUTOFF_DATE,
    SPIKE_WEEK_START,
    _classify_clean_northeast_hospitals,
    _mmwr_week_start,
    load_dataset_tables,
)

W40_WEEK_START = date(2026, 10, 4)
W40_WEEK_END = date(2026, 10, 10)
REVEAL_START_DATE = date(2026, 11, 1)
REVEAL_END_DATE = date(2026, 12, 12)
REVEAL_HORIZON_WEEKS = 6

# Minimum mean percentage overshoot and WAPE gap required to confirm that the
# uncleaned forecast visibly overshoots the Reveal.
MIN_UNCLEANED_MEAN_OVERSHOOT_PCT: float = 15.0
MIN_UNCLEANED_WAPE_GAP_POINTS: float = 10.0


def resolve_reveal_csv_path(reveal_location: str | Path) -> Path:
    """Resolve a runtime-supplied Reveal path or directory to its CSV file.

    Accepts a direct `.csv` file path, a directory containing `reveal.csv`,
    `<dir>/hospital_flu_feeds_reveal/reveal.csv`, or
    `<withheld_dir>/reveal/hospital_flu_feeds_reveal/reveal.csv`.
    """
    raw_str = str(reveal_location).strip()
    if not raw_str:
        raise ValueError(
            "Reveal location must be provided at runtime (ADR 0001); received empty path."
        )

    base = Path(raw_str)
    candidates = (
        base,
        base / "reveal.csv",
        base / "hospital_flu_feeds_reveal" / "reveal.csv",
        base / "reveal" / "hospital_flu_feeds_reveal" / "reveal.csv",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"Reveal CSV not found under runtime location: {reveal_location}"
    )


def resolve_answer_key_path(answer_key_location: str | Path) -> Path:
    """Resolve a runtime-supplied Answer Key file or withheld directory to `answer_key.json`."""
    raw_str = str(answer_key_location).strip()
    if not raw_str:
        raise ValueError(
            "Answer Key location must be provided at runtime (ADR 0001); received empty path."
        )

    base = Path(raw_str)
    candidates = (
        base,
        base / "answer_key.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"Answer Key JSON not found under runtime location: {answer_key_location}"
    )


def load_reveal_feeds(reveal_path: str | Path) -> list[dict[str, Any]]:
    """Load the 6 post-Cutoff Reveal weeks (`2026-11-01`..`2026-12-12`) from a runtime-supplied path."""
    csv_path = resolve_reveal_csv_path(reveal_path)
    rows: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            fdate = date.fromisoformat(str(raw_row["feed_date"]))
            if REVEAL_START_DATE <= fdate <= REVEAL_END_DATE:
                rows.append(
                    {
                        "hospital_id": str(raw_row["hospital_id"]),
                        "feed_date": fdate.isoformat(),
                        "total_flu_tests": int(raw_row["total_flu_tests"]),
                        "positive_flu_tests": int(raw_row["positive_flu_tests"]),
                        "batch_id": str(raw_row["batch_id"]),
                        "ingested_at": str(raw_row["ingested_at"]),
                    }
                )
    if not rows:
        raise ValueError(
            f"No post-Cutoff Reveal rows (2026-11-01..2026-12-12) found in {csv_path}"
        )
    return rows


def build_reveal_comparison_series(
    dataset_dir: str | Path,
    reveal_path: str | Path,
) -> list[dict[str, Any]]:
    """Build the 6-week Northeast comparison series across Reveal observed counts, clean forecast, and uncleaned forecast.

    Both `dataset_dir` and `reveal_path` must be supplied by the caller at runtime.
    """
    staging_rows, _ = load_dataset_tables(Path(dataset_dir))
    reveal_rows = load_reveal_feeds(reveal_path)

    # 1. Uncleaned pre-Cutoff Northeast trajectory from defective staging.hospital_flu
    w40_uncleaned = 0
    w43_uncleaned = 0
    for row in staging_rows:
        if str(row["region"]) != "Northeast":
            continue
        fdate = date.fromisoformat(str(row["feed_date"]))
        pos = int(row["positive_flu_tests"])
        if W40_WEEK_START <= fdate <= W40_WEEK_END:
            w40_uncleaned += pos
        elif SPIKE_WEEK_START <= fdate <= CUTOFF_DATE:
            w43_uncleaned += pos

    uncleaned_weekly_slope = (w43_uncleaned - w40_uncleaned) / 3.0

    # 2. Clean Cohort-aware Northeast bases from deduplicated staging.hospital_flu_clean
    by_hosp, ramp_ratio = _classify_clean_northeast_hospitals(staging_rows)
    ne_hospital_ids = set(by_hosp.keys())

    sampling_clean_base = sum(
        rec["prior_positives"]
        for rec in by_hosp.values()
        if rec["classification"] == "sampling_artifact"
    ) * (1.0 + ramp_ratio)
    outbreak_clean_base = float(
        sum(
            rec["cutoff_positives"]
            for rec in by_hosp.values()
            if rec["classification"] == "outbreak"
        )
    )
    seasonal_clean_base = float(
        sum(
            rec["cutoff_positives"]
            for rec in by_hosp.values()
            if rec["classification"] == "seasonal_ramp"
        )
    )

    # 3. Aggregate observed Northeast positive flu tests per post-Cutoff Reveal week
    reveal_by_week: dict[date, int] = {}
    for row in reveal_rows:
        if str(row["hospital_id"]) not in ne_hospital_ids:
            continue
        fdate = date.fromisoformat(str(row["feed_date"]))
        wk_start = _mmwr_week_start(fdate)
        reveal_by_week[wk_start] = reveal_by_week.get(wk_start, 0) + int(
            row["positive_flu_tests"]
        )

    comparison_rows: list[dict[str, Any]] = []
    for idx, wk_start in enumerate(sorted(reveal_by_week), start=1):
        wk_end = wk_start + timedelta(days=6)
        observed = reveal_by_week[wk_start]
        clean_fc = round(
            (sampling_clean_base + seasonal_clean_base) * ((1.0 + ramp_ratio) ** idx)
            + outbreak_clean_base * ((1.0 + 0.8 * ramp_ratio) ** idx),
            1,
        )
        uncleaned_fc = round(w43_uncleaned + uncleaned_weekly_slope * idx, 1)

        clean_err_pct = (
            round(((clean_fc - observed) / observed) * 100.0, 2)
            if observed > 0
            else 0.0
        )
        uncleaned_overshoot_pct = (
            round(((uncleaned_fc - observed) / observed) * 100.0, 2)
            if observed > 0
            else 0.0
        )

        comparison_rows.append(
            {
                "horizon_week": idx,
                "week_start": wk_start.isoformat(),
                "week_end": wk_end.isoformat(),
                "reveal_observed_positives": observed,
                "clean_forecast_positives": clean_fc,
                "uncleaned_forecast_positives": uncleaned_fc,
                "clean_error_pct": clean_err_pct,
                "uncleaned_overshoot_pct": uncleaned_overshoot_pct,
            }
        )

    return comparison_rows


def evaluate_reveal_overshoot(
    comparison_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Evaluate WAPE and overshoot metrics across the 6 post-Cutoff Reveal weeks."""
    if not comparison_rows:
        return {
            "weeks_evaluated": 0,
            "total_reveal_observed_positives": 0,
            "clean_wape": 0.0,
            "uncleaned_wape": 0.0,
            "clean_mean_error_pct": 0.0,
            "uncleaned_mean_overshoot_pct": 0.0,
            "every_week_overshoots": False,
            "uncleaned_visibly_overshoots": False,
        }

    total_observed = sum(
        int(row["reveal_observed_positives"]) for row in comparison_rows
    )
    clean_abs_error = sum(
        abs(
            float(row["clean_forecast_positives"])
            - float(row["reveal_observed_positives"])
        )
        for row in comparison_rows
    )
    uncleaned_abs_error = sum(
        abs(
            float(row["uncleaned_forecast_positives"])
            - float(row["reveal_observed_positives"])
        )
        for row in comparison_rows
    )

    clean_wape = (
        round((clean_abs_error / total_observed) * 100.0, 2)
        if total_observed > 0
        else 0.0
    )
    uncleaned_wape = (
        round((uncleaned_abs_error / total_observed) * 100.0, 2)
        if total_observed > 0
        else 0.0
    )

    clean_pct_errors = [
        abs(
            float(row["clean_forecast_positives"])
            - float(row["reveal_observed_positives"])
        )
        / float(row["reveal_observed_positives"])
        * 100.0
        for row in comparison_rows
        if float(row["reveal_observed_positives"]) > 0
    ]
    uncleaned_overshoots = [
        (
            float(row["uncleaned_forecast_positives"])
            - float(row["reveal_observed_positives"])
        )
        / float(row["reveal_observed_positives"])
        * 100.0
        for row in comparison_rows
        if float(row["reveal_observed_positives"]) > 0
    ]

    clean_mean_error_pct = (
        round(sum(clean_pct_errors) / len(clean_pct_errors), 2)
        if clean_pct_errors
        else 0.0
    )
    uncleaned_mean_overshoot_pct = (
        round(sum(uncleaned_overshoots) / len(uncleaned_overshoots), 2)
        if uncleaned_overshoots
        else 0.0
    )

    every_week_overshoots = all(
        float(row["uncleaned_forecast_positives"])
        > float(row["reveal_observed_positives"])
        for row in comparison_rows
    )
    uncleaned_visibly_overshoots = (
        len(comparison_rows) == REVEAL_HORIZON_WEEKS
        and every_week_overshoots
        and uncleaned_mean_overshoot_pct >= MIN_UNCLEANED_MEAN_OVERSHOOT_PCT
        and uncleaned_wape >= clean_wape + MIN_UNCLEANED_WAPE_GAP_POINTS
    )

    return {
        "weeks_evaluated": len(comparison_rows),
        "total_reveal_observed_positives": total_observed,
        "clean_wape": clean_wape,
        "uncleaned_wape": uncleaned_wape,
        "clean_mean_error_pct": clean_mean_error_pct,
        "uncleaned_mean_overshoot_pct": uncleaned_mean_overshoot_pct,
        "every_week_overshoots": every_week_overshoots,
        "uncleaned_visibly_overshoots": uncleaned_visibly_overshoots,
    }


def render_reveal_chart_svg(comparison_rows: Sequence[Mapping[str, Any]]) -> str:
    """Render a self-contained SVG chart comparing Reveal observed counts against both forecasts."""
    if not comparison_rows:
        raise ValueError("Cannot render Reveal SVG chart from empty comparison_rows.")

    metrics = evaluate_reveal_overshoot(comparison_rows)
    width = 860
    height = 480
    pad_left = 90
    pad_right = 50
    pad_top = 80
    pad_bottom = 85
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    all_values = [
        val
        for row in comparison_rows
        for val in (
            float(row["reveal_observed_positives"]),
            float(row["clean_forecast_positives"]),
            float(row["uncleaned_forecast_positives"]),
        )
    ]
    min_val = max(0.0, min(all_values) * 0.85)
    max_val = max(all_values) * 1.08
    val_span = max(max_val - min_val, 1.0)

    n_pts = len(comparison_rows)

    def _x(idx: int) -> float:
        if n_pts <= 1:
            return float(pad_left + plot_w / 2.0)
        return round(pad_left + (idx / (n_pts - 1)) * plot_w, 1)

    def _y(val: float) -> float:
        norm = (val - min_val) / val_span
        return round(pad_top + plot_h - norm * plot_h, 1)

    obs_pts = " ".join(
        f"{_x(i)},{_y(float(r['reveal_observed_positives']))}"
        for i, r in enumerate(comparison_rows)
    )
    clean_pts = " ".join(
        f"{_x(i)},{_y(float(r['clean_forecast_positives']))}"
        for i, r in enumerate(comparison_rows)
    )
    unclean_pts = " ".join(
        f"{_x(i)},{_y(float(r['uncleaned_forecast_positives']))}"
        for i, r in enumerate(comparison_rows)
    )

    grid_lines: list[str] = []
    for step in range(5):
        gv = min_val + (val_span * step / 4.0)
        gy = _y(gv)
        grid_lines.append(
            f'  <line x1="{pad_left}" y1="{gy}" x2="{width - pad_right}" y2="{gy}" '
            'stroke="#e8eaed" stroke-width="1" />'
        )
        grid_lines.append(
            f'  <text x="{pad_left - 12}" y="{gy + 4}" text-anchor="end" '
            f'font-size="11" fill="#5f6368">{round(gv)}</text>'
        )

    x_labels: list[str] = []
    point_markers: list[str] = []
    for i, row in enumerate(comparison_rows):
        cx = _x(i)
        wk_label = str(row["week_start"])
        x_labels.append(
            f'  <text x="{cx}" y="{height - pad_bottom + 24}" text-anchor="middle" '
            f'font-size="11" fill="#3c4043">{wk_label}</text>'
        )
        obs_y = _y(float(row["reveal_observed_positives"]))
        clean_y = _y(float(row["clean_forecast_positives"]))
        unclean_y = _y(float(row["uncleaned_forecast_positives"]))
        point_markers.append(
            f'  <circle cx="{cx}" cy="{obs_y}" r="4.5" fill="#137333" />'
        )
        point_markers.append(
            f'  <circle cx="{cx}" cy="{clean_y}" r="4.0" fill="#1a73e8" />'
        )
        point_markers.append(
            f'  <circle cx="{cx}" cy="{unclean_y}" r="4.5" fill="#d93025" />'
        )

    svg_lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif">',
        f'  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" rx="8" />',
        '  <text x="90" y="34" font-size="17" font-weight="600" fill="#202124">Northeast Weekly Positive Flu Tests: Post-Cutoff Reveal vs. Forecasts</text>',
        (
            f'  <text x="90" y="56" font-size="12" fill="#5f6368">'
            f"Clean Forecast WAPE: {metrics['clean_wape']:.2f}% | "
            f"Uncleaned Forecast WAPE: {metrics['uncleaned_wape']:.2f}% "
            f"(Mean Overshoot: +{metrics['uncleaned_mean_overshoot_pct']:.1f}%)"
            f"</text>"
        ),
        *grid_lines,
        f'  <polyline fill="none" stroke="#d93025" stroke-width="3" points="{unclean_pts}" />',
        f'  <polyline fill="none" stroke="#137333" stroke-width="3" points="{obs_pts}" />',
        f'  <polyline fill="none" stroke="#1a73e8" stroke-width="2.5" stroke-dasharray="6,4" points="{clean_pts}" />',
        *point_markers,
        *x_labels,
        f'  <text x="{pad_left + plot_w / 2}" y="{height - 20}" text-anchor="middle" font-size="12" fill="#5f6368">Post-Cutoff Reveal Week Start (MMWR Sunday)</text>',
        '  <g transform="translate(500, 24)" font-size="11" fill="#202124">',
        '    <line x1="0" y1="8" x2="22" y2="8" stroke="#137333" stroke-width="3" />',
        '    <text x="28" y="12">Reveal Observed</text>',
        '    <line x1="130" y1="8" x2="152" y2="8" stroke="#1a73e8" stroke-width="2.5" stroke-dasharray="5,3" />',
        '    <text x="158" y="12">Clean Forecast</text>',
        '    <line x1="0" y1="26" x2="22" y2="26" stroke="#d93025" stroke-width="3" />',
        '    <text x="28" y="30">Uncleaned Forecast (Overshoots)</text>',
        "  </g>",
        "</svg>",
    ]
    return "\n".join(svg_lines) + "\n"


def render_reveal_chart_ascii(comparison_rows: Sequence[Mapping[str, Any]]) -> str:
    """Render a terminal ASCII / Markdown comparison chart for the 6 post-Cutoff Reveal weeks."""
    if not comparison_rows:
        raise ValueError("Cannot render Reveal ASCII chart from empty comparison_rows.")

    metrics = evaluate_reveal_overshoot(comparison_rows)
    max_val = max(float(row["uncleaned_forecast_positives"]) for row in comparison_rows)
    bar_scale = 36.0 / max(max_val, 1.0)

    lines = [
        "================================================================================",
        "Northeast Post-Cutoff Reveal: Observed Positive Tests vs. Clean & Uncleaned Forecasts",
        "================================================================================",
        f"{'Week Start':<12} | {'Reveal Obs':>10} | {'Clean Fcst':>10} | {'Uncleaned Fcst':>14} | {'Overshoot':>10}",
        "-" * 80,
    ]
    for row in comparison_rows:
        wk = str(row["week_start"])
        obs = int(row["reveal_observed_positives"])
        clean_fc = float(row["clean_forecast_positives"])
        unclean_fc = float(row["uncleaned_forecast_positives"])
        overshoot_pct = float(row["uncleaned_overshoot_pct"])
        lines.append(
            f"{wk:<12} | {obs:>10d} | {clean_fc:>10.1f} | {unclean_fc:>14.1f} | {overshoot_pct:>+9.1f}%"
        )
        obs_bar = "#" * max(1, round(obs * bar_scale))
        clean_bar = "=" * max(1, round(clean_fc * bar_scale))
        unclean_bar = "!" * max(1, round(unclean_fc * bar_scale))
        lines.append(f"  Reveal Observed    : {obs_bar} ({obs})")
        lines.append(f"  Clean Forecast     : {clean_bar} ({clean_fc:.1f})")
        lines.append(
            f"  Uncleaned Forecast : {unclean_bar} ({unclean_fc:.1f} -> overshoots +{overshoot_pct:.1f}%)"
        )

    lines.extend(
        [
            "-" * 80,
            (
                f"Summary: Clean Forecast WAPE = {metrics['clean_wape']:.2f}% | "
                f"Uncleaned Forecast WAPE = {metrics['uncleaned_wape']:.2f}% | "
                f"Mean Uncleaned Overshoot = +{metrics['uncleaned_mean_overshoot_pct']:.2f}%"
            ),
            "================================================================================",
        ]
    )
    return "\n".join(lines)
