"""Window 2 fallback trigger times must follow the 60-second rule.

Each trigger is computed from docs/recorded_runtimes.json: the step's start
time plus its recorded runtime plus 60 seconds, rounded up to the next whole
minute. The test then checks that DEMO.md and the presenter runbook state the
computed times, so editing a runtime or a start time without the other fails.
"""

from __future__ import annotations

import json
import math
import re
import unittest
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIMES = json.loads(
    (REPO_ROOT / "docs" / "recorded_runtimes.json").read_text(encoding="utf-8")
)
DOCS = {
    "DEMO.md": REPO_ROOT / "DEMO.md",
    "docs/presenter-runbook.md": REPO_ROOT / "docs" / "presenter-runbook.md",
}
RULE_SECONDS = 60


@dataclass(frozen=True)
class Step:
    segment: str
    # Clock time the agent's job starts (or, for 2D, the dispatch deadline).
    start: str
    # Job keys whose slowest recorded runtime bounds the agent's job.
    jobs: tuple[str, ...]
    # Recorded runtime of Fallback A, or None when there is no Fallback B.
    fallback_a: tuple[str, str] | None
    # First cell of the step's row in each doc's fallback trigger table.
    row_markers: dict[str, str]


STEPS = (
    Step(
        "1C",
        "00:38",
        ("ws1_pipeline_clean_dataproc_runtime_3_0",),
        ("ws1_pipeline_clean_dataproc_runtime_3_0", "sql_fallback_observed_seconds"),
        {
            "DEMO.md": "| **Workstream 1C ",
            "docs/presenter-runbook.md": "| `ws1_pipeline_clean_dataproc_runtime_3_0` ",
        },
    ),
    Step(
        "2A",
        "00:50",
        ("ws2_seasonal_features_and_kmeans",),
        ("ws2_seasonal_features_and_kmeans", "seconds"),
        {
            "DEMO.md": "| **Workstream 2A ",
            "docs/presenter-runbook.md": "| `ws2_seasonal_features_and_kmeans` ",
        },
    ),
    Step(
        "2B",
        "00:57",
        ("ws2_arima_plus_cohort_training", "ws2_timesfm_ai_forecast"),
        ("ws2_forecasts_reference_runner", "seconds"),
        {
            "DEMO.md": "| **Workstream 2B ",
            "docs/presenter-runbook.md": "| `ws2_arima_plus_cohort_training` ",
        },
    ),
    # 2D's deadline is for dispatching the subagent, so no runtime is added.
    Step(
        "2D",
        "01:12",
        (),
        None,
        {
            "DEMO.md": "| **Workstream 2D ",
            "docs/presenter-runbook.md": "| `cohort-forecast-refresh` ",
        },
    ),
)


def _seconds(key: str, field: str = "seconds") -> int:
    """Worst-case runtime: an estimate, or the slower of baseline and last."""
    entry = RUNTIMES[key]
    if field != "seconds":
        return entry[field]
    if "estimated_seconds" in entry:
        return entry["estimated_seconds"]
    return max(entry["baseline_observed_seconds"], entry["last_observed_seconds"])


def _plus(clock: str, seconds: int) -> str:
    """Clock time `seconds` + 60s after `clock`, rounded up to the minute."""
    hours, minutes = map(int, clock.split(":"))
    total = hours * 60 + minutes + math.ceil((seconds + RULE_SECONDS) / 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _trigger_a(step: Step) -> str:
    return _plus(step.start, max((_seconds(job) for job in step.jobs), default=0))


def _trigger_b(step: Step) -> str | None:
    if step.fallback_a is None:
        return None
    return _plus(_trigger_a(step), _seconds(*step.fallback_a))


class TestFallbackTriggerTiming(unittest.TestCase):
    def test_estimated_runtimes_sum_their_components(self) -> None:
        for key, entry in RUNTIMES.items():
            if "estimated_seconds" not in entry:
                continue
            with self.subTest(key=key):
                parts = entry["estimated_from"]
                self.assertTrue(parts, f"{key} names no component jobs")
                self.assertEqual(
                    entry["estimated_seconds"],
                    sum(_seconds(part) for part in parts),
                    f"{key}.estimated_seconds must equal the worst-case sum of {parts}",
                )

    def test_whole_runner_fallbacks_have_their_own_runtime(self) -> None:
        # These runners chain several jobs, so the per-job entries understate them.
        for key, runner in (
            ("ws2_forecasts_reference_runner", "bin/run-ws2-forecasts"),
            ("ws2_cohort_forecast_refresh", "bin/run-cohort-forecast-refresh"),
        ):
            with self.subTest(key=key):
                self.assertIn(key, RUNTIMES)
                self.assertEqual(RUNTIMES[key]["runner"], runner)
                self.assertTrue((REPO_ROOT / runner).is_file(), f"missing {runner}")

    def test_segment_fallback_labels_follow_the_60_second_rule(self) -> None:
        expected_a = [_trigger_a(s) for s in STEPS if s.fallback_a]
        expected_b = [_trigger_b(s) for s in STEPS if s.fallback_a]
        expected_single = [_trigger_a(s) for s in STEPS if not s.fallback_a]
        for name, path in DOCS.items():
            doc = path.read_text(encoding="utf-8")
            for label, expected in (
                (r"Fallback A", expected_a),
                (r"Fallback B", expected_b),
                (r"Fallback", expected_single),
            ):
                with self.subTest(doc=name, label=label):
                    found = re.findall(
                        rf"Window 2 {label} \(trigger at `(\d\d:\d\d)`", doc
                    )
                    self.assertEqual(
                        found,
                        expected,
                        f"{name}: '{label}' trigger times must be start + "
                        "recorded runtime + 60s, rounded up to the minute "
                        "(segments in order 1C, 2A, 2B, 2D)",
                    )

    def test_trigger_table_rows_state_start_and_computed_triggers(self) -> None:
        for name, path in DOCS.items():
            lines = path.read_text(encoding="utf-8").splitlines()
            for step in STEPS:
                with self.subTest(doc=name, segment=step.segment):
                    rows = [
                        line
                        for line in lines
                        if line.startswith(step.row_markers[name])
                    ]
                    self.assertEqual(len(rows), 1, f"{step.segment} trigger row")
                    times = re.findall(r"\*\*`(\d\d:\d\d)`", rows[0])
                    wanted = [step.start, _trigger_a(step)]
                    if _trigger_b(step):
                        wanted.append(_trigger_b(step))
                    self.assertEqual(
                        times,
                        wanted,
                        f"{name} {step.segment} row must state start, Fallback "
                        "A trigger, then Checkpoint trigger in bold",
                    )


if __name__ == "__main__":
    unittest.main()
