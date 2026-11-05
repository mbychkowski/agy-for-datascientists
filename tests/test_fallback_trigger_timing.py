"""Window 2 fallback trigger times must follow the 60-second rule.

Each trigger is computed from docs/recorded_runtimes.json: the step's start
time plus its recorded (or estimated) runtime plus 60 seconds, rounded up to
the next whole minute. The test then checks that DEMO.md states the computed
times, so editing a runtime or a start time without the other fails. A slower live run recorded by bin/run-ws2-forecasts or
bin/run-pipeline-clean fails it too, on purpose: move the triggers in the docs.
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
}
RULE_SECONDS = 60


@dataclass(frozen=True)
class Step:
    segment: str
    # Clock time the agent's job starts (or, for 2D, the dispatch deadline).
    start: str
    # Job keys whose slowest runtime bounds the agent's job.
    jobs: tuple[str, ...]
    # Fallback A's runtime as (job key, field); field None means worst case.
    # None when the step has a single fallback and no Checkpoint after it.
    fallback_a: tuple[str, str | None] | None
    # First cell of the step's row in each doc's fallback trigger table.
    row_markers: dict[str, str]
    # Window 2 commands, mapped to "A" (Fallback A) or "B" (Checkpoint).
    commands: dict[str, str]


STEPS = (
    Step(
        "1C",
        "00:38",
        ("ws1_pipeline_clean_dataproc_runtime_3_0",),
        ("ws1_pipeline_clean_dataproc_runtime_3_0", "sql_fallback_observed_seconds"),
        {
            "DEMO.md": "| **Workstream 1C ",
        },
        {
            "./run-pipeline-clean --sql-fallback": "A",
            "./checkpoint ws1_staging_clean": "B",
        },
    ),
    Step(
        "2A",
        "00:50",
        ("ws2_seasonal_features_and_kmeans",),
        ("ws2_seasonal_features_and_kmeans", None),
        {
            "DEMO.md": "| **Workstream 2A ",
        },
        {
            "./run-ws2-cohorts": "A",
            "./checkpoint ws2_seasonal_features": "B",
            "./checkpoint ws2_hospital_cohorts": "B",
        },
    ),
    Step(
        "2B",
        "00:57",
        # The agent runs TimesFM while ARIMA_PLUS trains, so the slower bounds it.
        ("ws2_arima_plus_cohort_training", "ws2_timesfm_ai_forecast"),
        ("ws2_forecasts_reference_runner", None),
        {
            "DEMO.md": "| **Workstream 2B ",
        },
        {
            "./run-ws2-forecasts": "A",
            "./checkpoint ws2_experiment_trials": "B",
            "./checkpoint ws2_forecast_leaderboard": "B",
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
        },
        {"./run-cohort-forecast-refresh --period 2026-W44": "A"},
    ),
)


def _seconds(key: str, field: str | None = None) -> int:
    """A named field, else the worst case: the slower of baseline and last
    observed, or for a multi-job estimate the sum of its components."""
    entry = RUNTIMES[key]
    if field is not None:
        return entry[field]
    if "estimated_from" in entry:
        return sum(_seconds(part) for part in entry["estimated_from"])
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


def _is_subsequence(wanted: list[str], found: list[str]) -> bool:
    remaining = iter(found)
    return all(item in remaining for item in wanted)


class TestFallbackTriggerTiming(unittest.TestCase):
    def test_estimates_name_observed_component_jobs(self) -> None:
        for key, entry in RUNTIMES.items():
            if "estimated_from" not in entry:
                continue
            with self.subTest(key=key):
                self.assertTrue(entry["estimated_from"], f"{key} names no jobs")
                for part in entry["estimated_from"]:
                    self.assertIn("last_observed_seconds", RUNTIMES[part])

    def test_whole_runner_fallbacks_have_their_own_entry(self) -> None:
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
                        "recorded or estimated runtime + 60s, rounded up to the "
                        "minute (segments in order 1C, 2A, 2B, 2D)",
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
                    self.assertTrue(
                        _is_subsequence(wanted, times),
                        f"{name} {step.segment} row must state, in bold and in "
                        f"order, the start, Fallback A and Checkpoint times "
                        f"{wanted}; found {times}",
                    )

    def test_agenda_times_next_to_commands_match_computed_triggers(self) -> None:
        # Agenda rows annotate commands as `./cmd` *(`HH:MM`, Ns)*.
        expected = {}
        for step in STEPS:
            for command, which in step.commands.items():
                expected[command] = (
                    _trigger_a(step) if which == "A" else _trigger_b(step)
                )
        for name, path in DOCS.items():
            doc = path.read_text(encoding="utf-8")
            for command, clock in re.findall(r"`(\./[^`]+)` \*\(`(\d\d:\d\d)`", doc):
                with self.subTest(doc=name, command=command):
                    self.assertIn(command, expected, "unknown fallback command")
                    self.assertEqual(clock, expected[command])


if __name__ == "__main__":
    unittest.main()
